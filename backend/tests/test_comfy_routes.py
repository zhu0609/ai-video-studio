import io
import json
from PIL import Image
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, text, inspect
from app import workflows, comfy_routes
from app.config import settings
from app.db import init_db
from app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    init_db()
    monkeypatch.setattr(workflows,'IMPORTED',tmp_path/'workflows')
    workflows.IMPORTED.mkdir()
    client=TestClient(app)
    yield client
    client.close()

def image_bytes():
    data=io.BytesIO(); Image.new('RGB',(30,40),'blue').save(data,format='PNG'); return data.getvalue()

def test_reference_upload_checks_content_and_batch_reference_contract(client):
    r=client.post('/api/references/upload',content=image_bytes(),headers={'Content-Type':'image/png'})
    assert r.status_code==201,r.text
    uploaded=r.json(); assert (uploaded['width'],uploaded['height'])==(30,40)
    result=client.post('/api/batches',json={'theme':'参考图协议测试','count':1,'duration':5,'image_provider':'comfyui',
        'workflow_id':'sdxl-reference','reference_image':uploaded['key'],'mode':'demo'})
    assert result.status_code==201,result.text
    detail=client.get('/api/batches/'+result.json()['id']).json()
    assert detail['comfy_workflow']['bindings']['reference']['node']=='10'
    assert detail['reference_image']==uploaded['key']
    assert client.post('/api/references/upload',content=b'not png',headers={'Content-Type':'image/png'}).status_code==422
    assert client.post('/api/references/upload',content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}).status_code==415

def test_example_catalog_and_import_rejects_canvas_and_keys(client):
    config=client.get('/api/comfy/config').json()
    assert {w['id'] for w in config['workflows']}=={'sdxl-basic','sdxl-reference'}
    packet=client.get('/api/comfy/workflows/sdxl-basic/download').json()
    packet['name']='我的工作流'; packet['workflow']['4']['inputs']['ckpt_name']='test.safetensors'
    r=client.post('/api/comfy/workflows',json=packet); assert r.status_code==201,r.text
    assert client.get('/api/comfy/workflows/'+r.json()['id']+'/download').status_code==200
    assert client.post('/api/comfy/workflows',json={'nodes':[],'links':[]}).status_code==422
    packet['workflow']['4']['inputs']['api_key']='do-not-store'
    assert client.post('/api/comfy/workflows',json=packet).status_code==422
    assert len(list(workflows.IMPORTED.glob('*.json')))==1

def test_live_comfy_requires_server_and_reference_binding(client,monkeypatch):
    monkeypatch.setattr(settings,'comfyui_base_url','')
    response=client.post('/api/batches',json={'theme':'无服务测试','mode':'live','image_provider':'comfyui','workflow_id':'sdxl-basic'})
    assert response.status_code==422 and 'COMFYUI_BASE_URL' in response.json()['detail']
    assert client.post('/api/batches',json={'theme':'无参考图测试','image_provider':'comfyui','workflow_id':'sdxl-reference'}).status_code==422
    assert client.post('/api/batches',json={'theme':'无效参考图','image_provider':'comfyui','workflow_id':'sdxl-reference','reference_image':'../.env'}).status_code==422

def test_connection_check_is_read_only_and_reports_missing_models(client,monkeypatch):
    monkeypatch.setattr(settings,'comfyui_base_url','http://test-comfy:8188')
    called=[]; original=httpx.Client
    def handler(request):
        called.append((request.method,request.url.path))
        if request.url.path=='/system_stats': return httpx.Response(200,json={'devices':[{'name':'Protocol test (not a real GPU)','vram_total':0}]})
        if request.url.path=='/object_info': return httpx.Response(200,json={})
        raise AssertionError(request.url)
    monkeypatch.setattr(comfy_routes.httpx,'Client',lambda *args,**kwargs:original(*args,transport=httpx.MockTransport(handler),**kwargs))
    r=client.post('/api/comfy/check',json={'workflow_id':'sdxl-basic'}).json()
    assert not r['ok'] and 'SaveImage' in r['missing_nodes']
    assert called==[('GET','/system_stats'),('GET','/object_info')]

def test_old_database_additive_migration_preserves_rows(tmp_path,monkeypatch):
    from app import db
    engine=create_engine('sqlite:///'+(tmp_path/'legacy.db').as_posix())
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE batches (id VARCHAR PRIMARY KEY, theme TEXT)'))
        conn.execute(text("INSERT INTO batches (id,theme) VALUES ('old','preserve me')"))
    monkeypatch.setattr(db,'engine',engine)
    db.init_db(); db.init_db()
    with engine.connect() as conn:
        row=conn.execute(text('SELECT theme,image_provider,seed,comfy_workflow FROM batches')).one()
        assert tuple(row)==('preserve me','seedream',2026,None)
    engine.dispose()

def test_pipeline_uses_comfy_and_recovers_existing_image_task(tmp_path,monkeypatch):
    from app.db import Session,Batch,Video,Shot,Call
    from app.pipeline import image_step
    from app import providers
    from app.storage import storage
    init_db()
    monkeypatch.setattr(settings,'comfyui_base_url','http://protocol-only:8188')
    monkeypatch.setattr(settings,'comfyui_poll_interval_seconds',0)
    monkeypatch.setattr(providers,'throttle',lambda:None)
    packet=workflows.get_workflow('sdxl-basic'); packet['server_url']=settings.comfyui_base_url
    posted=[]; original=httpx.Client
    def handler(request):
        if request.url.path=='/prompt':
            posted.append(json.loads(request.content))
            return httpx.Response(200,json={'prompt_id':'existing-prompt'})
        if request.url.path=='/history/existing-prompt':
            return httpx.Response(200,json={'existing-prompt':{'status':{'completed':True},'outputs':{'9':{'images':[{'filename':'frame.png','subfolder':'','type':'output'}]}}}})
        if request.url.path=='/view': return httpx.Response(200,content=image_bytes())
        raise AssertionError(str(request.url))
    monkeypatch.setattr(httpx,'Client',lambda *args,**kwargs:original(*args,transport=httpx.MockTransport(handler),**kwargs))
    with Session() as db:
        batch=Batch(theme='协议模拟，不是真实模型',count=1,duration=5,ratio='9:16',style='纪实',mode='live',voice=False,
            image_provider='comfyui',seed=42,comfy_workflow=packet)
        db.add(batch); db.flush()
        video=Video(batch_id=batch.id,number=1); db.add(video); db.flush()
        shot=Shot(video_id=video.id,position=1,duration=5,narration='早安。',prompt='测试分镜。'); db.add(shot); db.commit()
        image_step(db,video,batch,shot)
        assert shot.image_status=='done' and storage.path(shot.image).is_file()
        storage.path(shot.image).unlink()
        image_step(db,video,batch,shot)
        assert storage.path(shot.image).is_file() and len(posted)==1
        call=db.query(Call).filter_by(video_id=video.id,provider='comfyui').one()
        assert call.attempts==1 and call.result['prompt_id']=='existing-prompt'
