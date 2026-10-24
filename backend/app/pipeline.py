import math
import threading
import time
from sqlalchemy import update, or_
from .config import settings
from .db import Session, Batch, Video, Shot, Job, uid
from .schemas import Plan, PlanShot
from .providers import ArkText, Seedream, Seedance, MiniMax, download
from .storage import storage
from . import media

def enqueue(db, video, action, shot_id=None):
    job_id=uid()
    result=db.execute(update(Video).where(Video.id==video.id,Video.active_job.is_(None)).values(active_job=job_id,status='queued',error=''))
    if result.rowcount != 1: raise ValueError('该视频已有任务执行中，请等待完成')
    job=Job(id=job_id, video_id=video.id, action=action, shot_id=shot_id)
    db.add(job); db.commit()
    return job

def demo_plan(video, batch, count):
    angles=['从细节发现故事','跟随光线旅行','由远及近的观察','一次意外的相遇','把日常拍成电影']
    angle=angles[(video.number+video.revision-2)%len(angles)]
    prompts=['全景建立环境，缓慢推进','中景展现主体，横向跟拍','特写捕捉质感，浅景深','低角度仰拍，柔和逆光','拉远收束，保留空间']
    return Plan(title=f'{batch.theme} · {angle}',shots=[PlanShot(
        narration=['故事从这里开始。','细节里藏着惊喜。','让这一刻慢下来。','沿着光继续前行。'][(i+video.number-1)%4],
        prompt=f'{batch.theme}。叙事角度：{angle}。{prompts[(i+video.number-1)%5]}。{batch.style}。{batch.brief}') for i in range(count)])

def plan_video(db, video, batch):
    count=max(1,math.ceil(batch.duration/5))
    video.status='planning'; db.commit()
    plan=demo_plan(video,batch,count) if batch.mode=='demo' else ArkText().plan(video,batch,count)
    if any(len(s.narration)>max(15,int(batch.duration/count*6)) for s in plan.shots):
        raise ValueError('模型输出口播过长，请重新策划或调整文本模型')
    # A successful response is persisted by the provider before replacing old shots.
    db.query(Shot).filter_by(video_id=video.id).delete()
    duration=round(batch.duration/count,3)
    for i,item in enumerate(plan.shots):
        db.add(Shot(video_id=video.id,position=i+1,duration=duration if i<count-1 else batch.duration-duration*(count-1),
                    narration=item.narration,prompt=item.prompt))
    video.title=plan.title; video.status='review'; video.output=None
    db.commit()

def image_step(db, video, batch, shot):
    if shot.image and storage.path(shot.image).exists(): return
    shot.image_status='running'; shot.error=''; video.status='generating'; db.commit()
    key=f'{video.id}/{shot.id}/image-{shot.image_revision}.png'; path=storage.path(key)
    if batch.mode=='demo': media.demo_image(batch,video,shot,path)
    elif batch.image_provider == 'comfyui':
        from .comfy import ComfyUIImage
        ComfyUIImage().generate(video,batch,shot,path)
    else: Seedream().generate(video,batch,shot,path)
    # Validate decoded image and normalize MIME for subsequent data URLs.
    from PIL import Image
    with Image.open(path) as image: image.convert('RGB').save(path,format='PNG')
    shot.image=key; shot.image_status='done'; db.commit()

def clip_step(db,video,batch,shot):
    if shot.clip and storage.path(shot.clip).exists(): return
    image_step(db,video,batch,shot)
    shot.clip_status='running'; shot.error=''; video.status='generating'; db.commit()
    key=f'{video.id}/{shot.id}/clip-{shot.clip_revision}.mp4'; target=storage.path(key)
    if batch.mode=='demo': media.demo_clip(storage.path(shot.image),target,shot.duration,batch.ratio)
    else:
        if not shot.task_id:
            shot.task_id=Seedance().submit(video,batch,shot,storage.path(shot.image)); db.commit()
        url=Seedance().poll(video.id,shot.task_id)
        download(url,target)
    shot.clip=key; shot.clip_status='done'; db.commit()

def audio_step(db,video,batch,shot):
    if not batch.voice or not shot.narration: return
    if shot.audio and storage.path(shot.audio).exists(): return
    key=f'{video.id}/{shot.id}/audio-{shot.revision}.'+('wav' if batch.mode=='demo' else 'mp3')
    if batch.mode=='demo': media.demo_audio(storage.path(key),shot.duration)
    else: MiniMax().generate(video,shot,storage.path(key))
    shot.audio=key; db.commit()

def execute(job_id):
    owner=uid(); now=time.time()
    with Session() as db:
        claim=db.execute(update(Job).where(Job.id==job_id,or_(Job.state=='queued',(Job.state=='running') & (Job.lease_until<now))).values(
            state='running',owner=owner,lease_until=now+settings.lease_seconds))
        db.commit()
        if claim.rowcount != 1: return
    done=threading.Event()
    def heartbeat():
        while not done.wait(max(1,settings.lease_seconds/3)):
            with Session() as hb:
                hb.execute(update(Job).where(Job.id==job_id,Job.owner==owner,Job.state=='running').values(lease_until=time.time()+settings.lease_seconds)); hb.commit()
    thread=threading.Thread(target=heartbeat,daemon=True); thread.start()
    try:
        with Session() as db:
            job=db.get(Job,job_id); video=db.get(Video,job.video_id); batch=db.get(Batch,video.batch_id)
            if job.action=='plan' or not db.query(Shot).filter_by(video_id=video.id).first():
                plan_video(db,video,batch)
                if not batch.auto:
                    job.state='done'; db.commit(); return
            shots=db.query(Shot).filter_by(video_id=video.id).order_by(Shot.position).all()
            if job.action in ('image','clip'):
                shot=next(s for s in shots if s.id==job.shot_id)
                if job.action=='image': image_step(db,video,batch,shot)
                else: clip_step(db,video,batch,shot)
                video.status='ready'
            else:
                if job.action=='compose' and any(not s.clip for s in shots):
                    raise ValueError('镜头尚未全部生成，请先生成视频')
                for shot in shots:
                    if job.action!='compose': clip_step(db,video,batch,shot)
                    audio_step(db,video,batch,shot)
                video.status='composing'; db.commit()
                key=f'{video.id}/final.mp4'
                media.compose(batch,video,shots,storage.path(key))
                video.output=key; video.status='completed'
            video.error=''; job.state='done'; db.commit()
    except Exception as e:
        with Session() as db:
            job=db.get(Job,job_id); job.state='failed'; job.error=str(e)[:1400]
            video=db.get(Video,job.video_id); video.status='failed'; video.error=job.error
            for shot in db.query(Shot).filter_by(video_id=video.id):
                if shot.image_status=='running': shot.image_status='failed'; shot.error=job.error
                if shot.clip_status=='running': shot.clip_status='failed'; shot.error=job.error
            db.commit()
    finally:
        done.set(); thread.join(timeout=2)
        with Session() as db:
            db.execute(update(Video).where(Video.active_job==job_id).values(active_job=None))
            db.commit()

def pending_ids():
    with Session() as db:
        # Repair the final commit / active_job clearing crash window.
        for video in db.query(Video).filter(Video.active_job.is_not(None)):
            job=db.get(Job,video.active_job)
            if job and job.state in ('done','failed'): video.active_job=None
        db.commit()
        return [j.id for j in db.query(Job).filter(or_(Job.state=='queued',(Job.state=='running') & (Job.lease_until<time.time()))).order_by(Job.created).all()]

def local_loop(stop):
    while not stop.is_set():
        try:
            for job_id in pending_ids():
                if stop.is_set(): break
                execute(job_id)
        except Exception:
            import logging
            logging.exception('Local worker dispatch error')
        stop.wait(1)
