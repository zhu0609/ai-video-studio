"""Local management endpoints for workflow imports and reference images."""
import io
import json
import uuid
import warnings
from urllib.parse import urlsplit
import httpx
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from .config import settings
from .storage import storage
from . import workflows

router=APIRouter(prefix='/api')

async def limited_body(request, limit):
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>limit: raise HTTPException(413,'文件过大')
    return bytes(body)

@router.get('/comfy/config')
def comfy_config():
    try: url=workflows.server_url()
    except ValueError: url=''
    return {'base_url':url,'configured':bool(url),'api_key_configured':bool(settings.comfyui_api_key),
        'workflows':workflows.catalog(),
        'notice':'支持原生ComfyUI HTTP API及其反向代理。示例需安装对应模型；不包含云GPU、模型权重或真实参考人物一致性保证。'}

@router.post('/comfy/workflows',status_code=201)
async def import_workflow(request:Request):
    try:
        raw=await limited_body(request,2*1024*1024)
        packet=workflows.import_workflow(json.loads(raw))
        return workflows.summary(packet)
    except (ValueError,UnicodeDecodeError) as e:
        raise HTTPException(422,str(e))

@router.get('/comfy/workflows/{workflow_id}/download')
def download_workflow(workflow_id:str):
    try: packet=workflows.get_workflow(workflow_id)
    except ValueError as e: raise HTTPException(404,str(e))
    return Response(json.dumps(packet,ensure_ascii=False,indent=2),media_type='application/json',
        headers={'Content-Disposition':f'attachment; filename="{workflow_id}.json"'})

@router.post('/references/upload',status_code=201)
async def upload_reference(request:Request):
    content_type=request.headers.get('content-type','').split(';')[0]
    if content_type not in ('image/png','image/jpeg','image/webp'):
        raise HTTPException(415,'仅支持PNG、JPEG或WEBP参考图')
    raw=await limited_body(request,10*1024*1024)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG','WEBP'): raise ValueError('不支持的图片格式')
                if image.width*image.height>25_000_000: raise ValueError('参考图不得超过2500万像素')
                image.load()
                result=image.convert('RGB')
                width,height=result.size
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise HTTPException(422,'参考图无法读取、格式不支持或像素过大')
    key=f'references/{uuid.uuid4().hex}.png'
    result.save(storage.path(key),format='PNG')
    return {'key':key,'url':storage.url(key),'width':width,'height':height}

@router.post('/comfy/check')
async def check_connection(request:Request):
    try:
        body=await limited_body(request,4096)
        payload=json.loads(body) if body else {}
        if not isinstance(payload,dict): raise ValueError('请求体必须为对象')
        url=workflows.server_url()
        packet=workflows.get_workflow(payload['workflow_id']) if payload.get('workflow_id') else None
    except (ValueError,KeyError) as e: raise HTTPException(422,str(e))
    headers={'Authorization':f'Bearer {settings.comfyui_api_key}'} if settings.comfyui_api_key else {}
    try:
        # Never follow redirects carrying authentication to another host.
        with httpx.Client(timeout=10,follow_redirects=False) as client:
            response=client.get(url+'/system_stats',headers=headers)
            response.raise_for_status()
            info=response.json()
            if not isinstance(info,dict) or not isinstance(info.get('devices'),list):
                raise ValueError('响应不是原生ComfyUI的/system_stats协议，请检查服务地址')
            devices=[{'name':str(d.get('name','unknown'))[:150],'vram_total':d.get('vram_total')} for d in info['devices'] if isinstance(d,dict)]
            missing=[]; notes=[]
            if packet:
                r=client.get(url+'/object_info',headers=headers)
                r.raise_for_status(); object_info=r.json()
                if not isinstance(object_info,dict): raise ValueError('/object_info响应格式不正确')
                classes={n['class_type'] for n in packet['workflow'].values()}
                missing=sorted(classes-set(object_info))
                for node in packet['workflow'].values():
                    inputs=node['inputs']
                    if 'ckpt_name' in inputs:
                        selected=inputs['ckpt_name']
                        if selected=='REPLACE_WITH_INSTALLED_CHECKPOINT.safetensors':
                            notes.append('示例checkpoint仍为占位符，请替换为服务中已安装的模型后重新导入')
                        else:
                            options=object_info.get(node['class_type'],{}).get('input',{}).get('required',{}).get('ckpt_name',[])
                            if options and isinstance(options[0],list) and selected not in options[0]:
                                notes.append(f'服务中未找到checkpoint：{str(selected)[:120]}')
            ok=not missing and not notes
            return {'ok':ok,'message':'连接与所选工作流基础检查通过' if ok else '已连接，但工作流尚未就绪',
                    'devices':devices,'missing_nodes':missing,'warnings':list(dict.fromkeys(notes))}
    except httpx.HTTPStatusError as e:
        code=e.response.status_code
        return {'ok':False,'message':f'ComfyUI连接返回HTTP {code}，请核对地址及鉴权','devices':[],'warnings':[],'missing_nodes':[]}
    except (httpx.HTTPError,ValueError):
        return {'ok':False,'message':'连接失败或响应格式不正确，请确认ComfyUI服务已启动且地址可访问','devices':[],'warnings':[],'missing_nodes':[]}
