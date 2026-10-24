import io
import shutil
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .config import settings, missing_config
from .db import Session, init_db, Batch, Video, Shot, Job, Call
from .schemas import BatchCreate, ScriptEdit, Action, Resolve
from .pipeline import enqueue, local_loop
from .storage import storage
from .comfy_routes import router as comfy_router
from .usage_routes import router as usage_router
from .usage import aggregate_calls
from . import workflows

@asynccontextmanager
async def lifespan(app):
    init_db(); stop=threading.Event()
    thread=None
    if settings.execution_mode=='local':
        thread=threading.Thread(target=local_loop,args=(stop,),daemon=True); thread.start()
    yield
    stop.set()
    if thread: thread.join(timeout=3)

app=FastAPI(title='映序 Topic Video Studio',lifespan=lifespan)
app.include_router(comfy_router)
app.include_router(usage_router)

def obj(row):
    return {c.name:getattr(row,c.name) for c in row.__table__.columns}

def get_video(db, video_id):
    video=db.get(Video,video_id)
    if not video: raise HTTPException(404,'视频不存在')
    return video

def idle(video):
    if video.active_job: raise HTTPException(409,'该视频有任务执行中，请稍后操作')

def check_uncertain(db,video):
    if db.query(Call).filter(Call.video_id==video.id,Call.state.in_(['uncertain','submitted'])).first():
        raise HTTPException(409,'存在受理状态不确定的调用，请先在调用记录中核对解锁')

@app.get('/api/health')
def health():
    from .media import ffmpeg
    return {'ok':True,'execution_mode':settings.execution_mode,'database':'sqlite' if settings.database_url.startswith('sqlite') else 'postgresql',
            'ffmpeg':Path(ffmpeg()).exists() or bool(shutil.which(ffmpeg())),
            'missing_config':missing_config(),'demo_notice':'演示画面由程序绘制，配音选项为提示音；非真实AI生成。',
            'providers':{'text':settings.text_model or '未配置','image':settings.seedream_model or '未配置',
                         'video':settings.seedance_model or '未配置','speech':settings.minimax_model or '未配置'}}

@app.post('/api/batches',status_code=201)
def create_batch(data:BatchCreate):
    snapshot=None
    if data.image_provider=='comfyui':
        try:
            snapshot=workflows.get_workflow(data.workflow_id)
            if data.mode=='live': snapshot['server_url']=workflows.server_url()
            if data.mode=='live' and any(n['inputs'].get('ckpt_name')=='REPLACE_WITH_INSTALLED_CHECKPOINT.safetensors' for n in snapshot['workflow'].values()):
                raise ValueError('示例checkpoint尚未配置。请下载模板，替换为已安装模型并调通后重新导入')
            if snapshot['requires_reference'] and not data.reference_image:
                raise ValueError('所选工作流需要参考图，请先上传')
            if data.reference_image and not snapshot['requires_reference']:
                raise ValueError('所选工作流不支持参考图，请切换参考图工作流或移除参考图')
        except ValueError as e: raise HTTPException(422,str(e))
    elif data.reference_image:
        raise HTTPException(422,'当前参考图入口用于ComfyUI，请选择支持参考图的ComfyUI工作流')
    if data.reference_image:
        import re
        if not re.fullmatch(r'references/[a-f0-9]{32}\.png',data.reference_image) or not storage.path(data.reference_image).is_file():
            raise HTTPException(422,'参考图不存在，请重新上传')
    if data.mode=='live':
        missing=missing_config(data.voice,data.image_provider)
        if missing: raise HTTPException(422,'缺少服务端配置：'+', '.join(missing))
    with Session() as db:
        batch=Batch(**data.model_dump(),comfy_workflow=snapshot); db.add(batch); db.commit()
        for i in range(data.count):
            video=Video(batch_id=batch.id,number=i+1); db.add(video); db.flush()
            enqueue(db,video,'plan')
        return {'id':batch.id}

@app.get('/api/batches')
def batches():
    with Session() as db:
        result=[]
        for batch in db.query(Batch).order_by(Batch.created.desc()).all():
            videos=db.query(Video).filter_by(batch_id=batch.id).order_by(Video.number).all()
            result.append({**obj(batch),'videos':[obj(v) for v in videos]})
        return result

@app.get('/api/batches/{batch_id}')
def detail(batch_id:str):
    with Session() as db:
        batch=db.get(Batch,batch_id)
        if not batch: raise HTTPException(404,'批次不存在')
        videos=[]
        for video in db.query(Video).filter_by(batch_id=batch.id).order_by(Video.number):
            shots=[obj(s) for s in db.query(Shot).filter_by(video_id=video.id).order_by(Shot.position)]
            calls=[]
            call_rows=db.query(Call).filter_by(video_id=video.id).order_by(Call.created).all()
            for c in call_rows:
                calls.append({'id':c.id,'provider':c.provider,'kind':c.kind,'model':c.model,'attempts':c.attempts,
                    'state':c.state,'usage':c.usage,'error':c.error,
                    'task_id':((c.result or {}).get('prompt_id') or (c.result or {}).get('id')) if c.kind=='video' or c.provider=='comfyui' else None})
            videos.append({**obj(video),'shots':shots,'calls':calls,
                           'usage_summary':aggregate_calls(call_rows if batch.mode=='live' else []),
                           'jobs':[obj(j) for j in db.query(Job).filter_by(video_id=video.id).order_by(Job.created.desc()).limit(5)]})
        return {**obj(batch),'videos':videos}

@app.put('/api/videos/{video_id}/script')
def edit_script(video_id:str, data:ScriptEdit):
    with Session() as db:
        video=get_video(db,video_id); idle(video); check_uncertain(db,video)
        shots=db.query(Shot).filter_by(video_id=video_id).order_by(Shot.position).all()
        if {s.id for s in shots}!={s.id for s in data.shots} or len(shots)!=len(data.shots):
            raise HTTPException(422,'镜头ID不匹配；第一版支持编辑已有镜头，不支持增删')
        batch=db.get(Batch,video.batch_id)
        if abs(sum(s.duration for s in data.shots)-batch.duration)>.05:
            raise HTTPException(422,f'镜头总时长必须为{batch.duration}秒')
        edits={s.id:s for s in data.shots}
        for s in shots:
            edit=edits[s.id]
            if len(edit.narration)>max(15,int(edit.duration*6)):
                raise HTTPException(422,f'镜头{s.position}口播过长，请缩短到每秒6字以内')
        changed=video.title!=data.title
        for s in shots:
            edit=edits[s.id]
            if s.prompt!=edit.prompt:
                s.image=None; s.clip=None; s.task_id=None; s.image_revision+=1; s.clip_revision+=1
                s.image_status='pending'; s.clip_status='pending'; changed=True
            if s.narration!=edit.narration:
                s.audio=None; s.revision+=1; changed=True
            if s.duration!=edit.duration: changed=True
            s.prompt=edit.prompt; s.narration=edit.narration; s.duration=edit.duration
        video.title=data.title
        if changed: video.output=None; video.status='review'; video.error=''
        db.commit(); return {'ok':True}

@app.post('/api/videos/{video_id}/actions',status_code=202)
def action(video_id:str,data:Action):
    with Session() as db:
        video=get_video(db,video_id); idle(video)
        if data.action!='resume': check_uncertain(db,video)
        batch=db.get(Batch,video.batch_id)
        if batch.mode=='live' and missing_config(batch.voice,batch.image_provider):
            raise HTTPException(422,'真实模式配置不完整，请填写.env并重启')
        if data.action=='plan':
            video.revision+=1; video.output=None
        elif data.action in ('image','clip'):
            shot=db.get(Shot,data.shot_id)
            if not shot or shot.video_id!=video.id: raise HTTPException(404,'镜头不存在')
            if data.action=='image':
                shot.image=None; shot.image_revision+=1; shot.image_status='pending'
            shot.clip=None; shot.task_id=None; shot.clip_revision+=1; shot.clip_status='pending'; shot.error=''; video.output=None
        job=enqueue(db,video,data.action,data.shot_id)
        return {'job_id':job.id}

@app.post('/api/calls/{call_id}/resolve')
def resolve(call_id:str,data:Resolve):
    with Session() as db:
        call=db.get(Call,call_id)
        if not call: raise HTTPException(404,'调用不存在')
        video=get_video(db,call.video_id); idle(video)
        if call.state not in ('uncertain','submitted','failed'): raise HTTPException(409,'该调用不需要解锁')
        if data.task_id:
            if call.kind!='video' and call.provider!='comfyui': raise HTTPException(422,'只有视频或ComfyUI图片提交可以绑定任务ID')
            if not all(c.isalnum() or c in '-_' for c in data.task_id): raise HTTPException(422,'任务ID格式不正确')
            call.result={'prompt_id' if call.provider=='comfyui' else 'id':data.task_id}; call.state='succeeded'
        elif data.confirmed_not_accepted:
            call.state='ready'
        else: raise HTTPException(422,'请提供已核实的任务ID，或确认供应商未受理')
        call.error=''; db.commit(); return {'ok':True}

@app.get('/api/videos/{video_id}/download')
def video_download(video_id:str):
    with Session() as db:
        video=get_video(db,video_id)
        if not video.output or not storage.path(video.output).exists(): raise HTTPException(409,'成片尚未就绪')
        return FileResponse(storage.path(video.output),media_type='video/mp4',filename=f'video-{video.number:02d}.mp4')

@app.get('/api/batches/{batch_id}/download')
def batch_download(batch_id:str):
    with Session() as db:
        if not db.get(Batch,batch_id): raise HTTPException(404,'批次不存在')
        videos=db.query(Video).filter_by(batch_id=batch_id).all()
        if not videos or any(v.status!='completed' or not v.output for v in videos):
            raise HTTPException(409,'请等待该批次全部视频完成后下载')
        # Spool to disk for long videos instead of accumulating complete ZIP in memory.
        import tempfile
        archive=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
            for v in videos:
                z.write(storage.path(v.output),f'video-{v.number:02d}.mp4')
                srt=storage.path(v.output).with_suffix('.srt')
                if srt.exists(): z.write(srt,f'video-{v.number:02d}.srt')
        archive.seek(0)
        def stream():
            try:
                while chunk:=archive.read(1024*1024): yield chunk
            finally: archive.close()
        return StreamingResponse(stream(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="batch-{batch_id[:8]}.zip"'})

app.mount('/media',StaticFiles(directory=settings.media_dir),name='media')

@app.get('/{path:path}',include_in_schema=False)
def frontend(path:str):
    if path.startswith('api/'): raise HTTPException(404,'接口不存在')
    root=settings.frontend_dir.resolve(); target=(root/path).resolve()
    if not target.is_relative_to(root): raise HTTPException(404)
    if target.is_file(): return FileResponse(target)
    if (root/'index.html').exists(): return FileResponse(root/'index.html')
    raise HTTPException(503,'请先构建前端：在frontend执行pnpm install及pnpm build')
