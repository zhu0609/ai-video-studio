"""Official HTTP adapters. POST ambiguity is stopped, never silently retried."""
import base64
import json
import threading
import time
from pathlib import Path
import httpx
from .config import settings
from .db import Session, Call
from .schemas import Plan

class UncertainSubmission(RuntimeError): pass
class ProviderFailure(RuntimeError): pass

def response_usage(data):
    """Keep the provider's fields and units; an explicit zero is still reported usage."""
    if not isinstance(data, dict): return None
    usage, extra = data.get('usage'), data.get('extra_info')
    if isinstance(usage, dict) and isinstance(extra, dict):
        # MiniMax may return audio metadata alongside a token usage object.
        # Keep flat field names compatible with existing ledger records.
        return {**extra, **usage}
    return usage if usage is not None else extra

def capture_usage(call, data):
    """Replace a usage snapshot, never sum repeated task polls or erase known values."""
    usage = response_usage(data)
    if usage is None: return
    if usage == {} and call.usage is not None and call.usage != {}: return
    call.usage = usage

def error_detail(data, token=''):
    """Retain actionable provider diagnostics without returning credentials or media."""
    if not isinstance(data, dict): return '响应未包含错误详情'
    error = data.get('error') or data.get('base_resp') or {}
    if isinstance(error, dict):
        code = error.get('code', error.get('status_code', 'unknown'))
        message = str(error.get('message', error.get('status_msg', '请求失败')))
    else:
        code, message = 'unknown', str(error)
    detail = f'{code}：{message}'
    if token: detail = detail.replace(token, '[redacted]')
    return detail[:500]

_lock = threading.Lock()
_last = 0.0

def throttle():
    global _last
    if settings.execution_mode == 'celery':
        from redis import Redis
        redis = Redis.from_url(settings.redis_url)
        # Global interval across API and all worker processes; fail closed if Redis fails.
        while not redis.set('studio:provider-rate', '1', nx=True, px=max(1, int(settings.provider_interval_seconds * 1000))):
            time.sleep(.25)
    else:
        with _lock:
            time.sleep(max(0, settings.provider_interval_seconds - (time.monotonic() - _last)))
            _last = time.monotonic()

def tracked_post(video_id, key, provider, kind, model, url, token, payload):
    with Session() as db:
        call = db.query(Call).filter_by(key=key).first()
        if call and call.state == 'succeeded':
            return call.result
        if call and call.state in ('submitted', 'uncertain'):
            call.state = 'uncertain'
            db.commit()
            raise UncertainSubmission('请求结果不确定，禁止自动重发。请在调用记录中绑定视频任务ID，或核实供应商未受理后解锁。')
        if call and call.state == 'failed':
            raise ProviderFailure('上次调用明确失败，请在调用记录核实并解锁后再重试。')
        if not call:
            call = Call(video_id=video_id, key=key, provider=provider, kind=kind, model=model,
                        request={k:v for k,v in payload.items() if k not in ('content',)}, state='ready')
            # Keep compact inputs; do not persist image base64 or auth headers in public ledger.
            if kind == 'video': call.request = {'model':model, 'duration':payload.get('duration'), 'ratio':payload.get('ratio')}
            db.add(call)
            db.commit()
        call_id = call.id
    for attempt in range(3):
        throttle()
        with Session() as db:
            call = db.get(Call, call_id)
            call.state = 'submitted'
            call.attempts += 1
            db.commit()  # Commit BEFORE network side effect.
        result = None
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=False) as client:
                response = client.post(url, headers={'Authorization':f'Bearer {token}'} if token else {}, json=payload)
            try: result = response.json()
            except ValueError: pass
            if response.status_code == 429:
                with Session() as db:
                    c = db.get(Call, call_id)
                    c.state = 'ready' if attempt < 2 else 'failed'
                    c.error = 'HTTP 429：供应商限流'
                    capture_usage(c, result)
                    db.commit()
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise ProviderFailure('供应商限流，已达到有限重试次数')
            if response.status_code >= 500:
                raise UncertainSubmission(f'供应商HTTP {response.status_code}，受理状态需核对')
            if response.status_code >= 400:
                detail = error_detail(result, token) if result is not None else '请核对模型权限、参数、余额'
                raise ProviderFailure(f'供应商HTTP {response.status_code}，{detail}')
            if not isinstance(result, dict):
                raise UncertainSubmission('供应商响应不完整，受理状态需核对')
            if result.get('base_resp', {}).get('status_code', 0) != 0 or result.get('error'):
                raise ProviderFailure('供应商业务错误 ' + error_detail(result, token))
            with Session() as db:
                c = db.get(Call, call_id)
                c.state, c.result = 'succeeded', result
                capture_usage(c, result)
                c.error = ''
                db.commit()
            return result
        except ProviderFailure as e:
            with Session() as db:
                c = db.get(Call, call_id)
                c.state, c.error = 'failed', str(e)
                capture_usage(c, result)
                db.commit()
            raise
        except Exception as e:
            with Session() as db:
                c = db.get(Call, call_id)
                c.state, c.error = 'uncertain', '连接中断、超时或响应不完整；请核对受理状态'
                capture_usage(c, result)
                db.commit()
            raise UncertainSubmission('提交结果不确定，已暂停；不会自动重新扣费。请核对供应商任务。') from e

def safe_get(url, token=''):
    for attempt in range(3):
        throttle()
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
                r = client.get(url, headers={'Authorization':f'Bearer {token}'} if token else {})
            if r.status_code == 429 or r.status_code >= 500:
                r.raise_for_status()
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 2: raise ProviderFailure('查询或下载失败，保留原任务ID，可稍后恢复')
            time.sleep(2 ** attempt)

def download(url, target: Path):
    if not url.startswith('https://'): raise ProviderFailure('供应商素材地址必须使用HTTPS')
    data = safe_get(url).content
    tmp = target.with_suffix(target.suffix + '.tmp')
    tmp.write_bytes(data)
    tmp.replace(target)

class ArkText:
    def plan(self, video, batch, count):
        instruction = f'''你是短视频导演。仅输出JSON对象，结构为{{"title":"标题","shots":[{{"narration":"中文口播","prompt":"完整画面及运镜描述"}}]}}。
主题：{batch.theme}。补充要求：{batch.brief}。风格：{batch.style}。比例：{batch.ratio}。
这是同主题第{video.number}个版本，修订{video.revision}，采用不同叙事角度和镜头，避免雷同。
必须输出{count}个镜头，总时长{batch.duration}秒。每镜头约{batch.duration/count:.1f}秒，口播按每秒不超过3个汉字编写。
所有镜头保持相同人物、服装、商品、色彩设定。不要生成字幕和画面文字。'''
        from .planner import response_text, parse_plan, output_format
        try: formatting=output_format(settings.text_response_format,settings.text_model,count)
        except ValueError as e: raise ProviderFailure(str(e))
        data = tracked_post(video.id, f'{video.id}:plan:{video.revision}', 'ark', 'text', settings.text_model,
            settings.ark_base_url + '/chat/completions', settings.ark_api_key,
            {'model':settings.text_model,'messages':[{'role':'user','content':instruction}], 'stream':False,**formatting})
        raw=''
        try:
            raw=response_text(data)
            return parse_plan(raw,count,batch.duration)
        except ValueError as e:
            reason=str(e)[:300]
        # Only a successful provider response with invalid content reaches here.
        # Transport errors and ambiguous submissions above never initiate repair.
        repair=tracked_post(video.id,f'{video.id}:plan:{video.revision}:repair','ark','text',settings.text_model,
            settings.ark_base_url+'/chat/completions',settings.ark_api_key,
            {'model':settings.text_model,'stream':False,**formatting,'messages':[
                {'role':'user','content':instruction},
                {'role':'assistant','content':raw[:50000] or '未返回脚本内容'},
                {'role':'user','content':f'上次脚本校验失败：{reason}。请仅修复并输出完整JSON对象，必须恰好{count}个镜头，每个镜头都包含narration和prompt。不要添加解释或占位镜头。'}]})
        try: return parse_plan(response_text(repair),count,batch.duration)
        except ValueError as e:
            raise ProviderFailure(f'脚本自动纠错后仍不符合要求：{str(e)[:250]}。请修改主题要求或重新策划。') from e

class Seedream:
    def generate(self, video, batch, shot, target):
        data = tracked_post(video.id, f'{shot.id}:image:{shot.image_revision}', 'ark', 'image', settings.seedream_model,
            settings.ark_base_url + '/images/generations', settings.ark_api_key,
            {'model':settings.seedream_model,'prompt':f'{batch.style}，画幅比例{batch.ratio}。{shot.prompt}',
             'size':settings.seedream_size,'response_format':'url'})
        item = data['data'][0]
        if item.get('b64_json'): target.write_bytes(base64.b64decode(item['b64_json']))
        else: download(item['url'], target)

class Seedance:
    def submit(self, video, batch, shot, image):
        data_url = 'data:image/png;base64,' + base64.b64encode(image.read_bytes()).decode()
        result = tracked_post(video.id, f'{shot.id}:clip:{shot.clip_revision}', 'ark', 'video', settings.seedance_model,
            settings.ark_base_url + '/contents/generations/tasks', settings.ark_api_key,
            {'model':settings.seedance_model,'content':[{'type':'text','text':shot.prompt},
                {'type':'image_url','image_url':{'url':data_url}}],
             'duration':settings.seedance_clip_seconds, 'ratio':batch.ratio,
             'resolution':settings.seedance_resolution, 'generate_audio':False})
        return result['id']

    def poll(self, video_id, task_id):
        started = time.monotonic()
        while time.monotonic() - started < settings.video_timeout_seconds:
            data = safe_get(settings.ark_base_url + '/contents/generations/tasks/' + task_id, settings.ark_api_key).json()
            if response_usage(data) is not None:
                with Session() as db:
                    c = db.query(Call).filter_by(video_id=video_id, kind='video').all()
                    for call in c:
                        if (call.result or {}).get('id') == task_id:
                            capture_usage(call, data)
                    db.commit()
            if data['status'] == 'succeeded':
                return data['content']['video_url']
            if data['status'] in ('failed','cancelled','expired'):
                raise ProviderFailure(f'视频任务{data["status"]}，原ID保留；可显式重新生成镜头。')
            time.sleep(settings.poll_interval_seconds)
        raise ProviderFailure('轮询已超时，原任务ID保留；使用“恢复执行”继续查询，不会重新提交。')

class MiniMax:
    def generate(self, video, shot, target):
        data = tracked_post(video.id, f'{shot.id}:audio:{shot.revision}', 'minimax', 'speech', settings.minimax_model,
            settings.minimax_base_url + '/t2a_v2', settings.minimax_api_key,
            {'model':settings.minimax_model, 'text':shot.narration, 'stream':False, 'output_format':'hex',
             'voice_setting':{'voice_id':settings.minimax_voice, 'speed':1},
             'audio_setting':{'sample_rate':32000,'format':'mp3','channel':1}})
        target.write_bytes(bytes.fromhex(data['data']['audio']))

class WanVideo:
    """Reserved provider contract, deliberately unavailable until implemented and verified."""
    def submit(self, *args, **kwargs):
        raise NotImplementedError('万相适配器是扩展接口，第一版尚未实现。请选择Seedance。')
