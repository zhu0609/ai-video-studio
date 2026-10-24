"""Isolated integration tests: media output, recovery and paid-request ambiguity."""
import os
import tempfile
from pathlib import Path
import io
import zipfile
import pytest

from fastapi.testclient import TestClient
from app.main import app
from app.db import Session, init_db, Job, Call, Video, Shot, engine
from app.pipeline import execute, pending_ids
from app.config import settings
from app.providers import tracked_post, UncertainSubmission
from app.storage import storage

init_db()
client=TestClient(app)

@pytest.fixture(scope='session',autouse=True)
def cleanup():
    yield
    client.close()
    engine.dispose()

def make(**kwargs):
    r=client.post('/api/batches',json={'theme':'治愈系乡村生活','duration':12,'count':2,**kwargs})
    assert r.status_code==201,r.text
    return r.json()['id']

def detail(bid): return client.get('/api/batches/'+bid).json()
def run_pending():
    for jid in pending_ids(): execute(jid)

def test_review_batch_media_and_local_redo():
    bid=make()
    run_pending()
    batch=detail(bid)
    assert all(v['status']=='review' for v in batch['videos'])
    assert batch['videos'][0]['title']!=batch['videos'][1]['title']
    first=batch['videos'][0]
    # No media generation before review.
    assert all(s['image'] is None for s in first['shots'])
    assert client.get('/api/batches/'+bid+'/download').status_code==409
    for video in batch['videos']:
        assert client.post('/api/videos/'+video['id']+'/actions',json={'action':'generate'}).status_code==202
        assert client.post('/api/videos/'+video['id']+'/actions',json={'action':'generate'}).status_code==409
    run_pending()
    batch=detail(bid)
    assert all(v['status']=='completed' for v in batch['videos']),batch
    archive=client.get('/api/batches/'+bid+'/download')
    assert archive.status_code==200
    z=zipfile.ZipFile(io.BytesIO(archive.content))
    assert len(z.namelist())==4
    assert len(z.read('video-01.mp4'))>1000
    assert '00:00:12,000' in z.read('video-01.srt').decode()
    v=batch['videos'][0]; old=[s['clip'] for s in v['shots']]
    edit={'title':v['title'],'shots':[{k:s[k] for k in ['id','duration','narration','prompt']} for s in v['shots']]}
    edit['shots'][0]['narration']='一起走进乡村。'
    r=client.put('/api/videos/'+v['id']+'/script',json=edit); assert r.status_code==200,r.text
    edited=detail(bid)['videos'][0]
    assert edited['output'] is None
    assert [s['clip'] for s in edited['shots']]==old  # Voice edit preserves visuals.
    edit['shots'][0]['prompt']='清晨稻田，缓慢推进镜头'
    assert client.put('/api/videos/'+v['id']+'/script',json=edit).status_code==200
    edited=detail(bid)['videos'][0]
    assert edited['shots'][0]['clip'] is None
    assert edited['shots'][1]['clip']==old[1]
    assert client.post('/api/videos/'+v['id']+'/actions',json={'action':'resume'}).status_code==202
    run_pending()
    assert detail(bid)['videos'][0]['status']=='completed'

def test_auto_execution_and_voice_track():
    bid=make(count=1,duration=5,auto=True,voice=True,ratio='16:9')
    run_pending()
    v=detail(bid)['videos'][0]
    assert v['status']=='completed',v['error']
    assert v['shots'][0]['audio'].endswith('.wav')
    assert client.get('/api/videos/'+v['id']+'/download').status_code==200

def test_validation_and_live_configuration(monkeypatch):
    monkeypatch.setattr(settings,'ark_api_key','')
    assert client.post('/api/batches',json={'theme':'xx','mode':'live'}).status_code==422
    assert client.post('/api/batches',json={'theme':'xx','count':21}).status_code==422
    assert client.post('/api/batches',json={'theme':'xx','duration':601}).status_code==422

def test_reclaim_expired_job_without_duplicate_claim():
    bid=make(count=1,duration=5)
    with Session() as db:
        v=db.query(Video).filter_by(batch_id=bid).first()
        job=db.get(Job,v.active_job); jid=job.id
        job.state='running'; job.owner='dead-worker'; job.lease_until=0; db.commit()
    assert jid in pending_ids()
    execute(jid); execute(jid)
    with Session() as db:
        assert db.get(Job,jid).state=='done'
        assert db.query(Shot).filter_by(video_id=v.id).count()==1

def test_uncertain_submission_is_never_reposted(monkeypatch):
    import app.providers as p
    bid=make(count=1,duration=5); run_pending(); v=detail(bid)['videos'][0]
    monkeypatch.setattr(p,'throttle',lambda:None)
    attempts=[]
    original_post=p.httpx.Client.post
    def interrupted(*args,**kwargs):
        attempts.append(1)
        import httpx
        raise httpx.ReadTimeout('accepted but response lost')
    monkeypatch.setattr(p.httpx.Client,'post',interrupted)
    for _ in range(2):
        with pytest.raises(UncertainSubmission):
            tracked_post(v['id'],v['id']+':ambiguous','ark','video','test','https://example.com','secret',{'model':'test'})
    assert len(attempts)==1
    with Session() as db:
        c=db.query(Call).filter_by(key=v['id']+':ambiguous').one()
        cid=c.id
        assert c.state=='uncertain' and c.attempts==1
    monkeypatch.setattr(p.httpx.Client,'post',original_post)
    assert client.post('/api/calls/'+cid+'/resolve',json={'task_id':'cgt-existing-123'}).status_code==200
    monkeypatch.setattr(p.httpx.Client,'post',interrupted)
    result=tracked_post(v['id'],v['id']+':ambiguous','ark','video','test','https://example.com','secret',{})
    assert result=={'id':'cgt-existing-123'} and len(attempts)==1

@pytest.mark.parametrize('status,payload,expected', [
    (200, {'base_resp':{'status_code':1008,'status_msg':'insufficient balance'}}, '1008'),
    (401, {'error':{'code':'InvalidApiKey','message':'invalid test-secret-token'}}, 'InvalidApiKey'),
])
def test_provider_errors_are_actionable_and_redacted(monkeypatch,status,payload,expected):
    import app.providers as p
    import httpx
    bid=make(count=1,duration=5); run_pending(); vid=detail(bid)['videos'][0]['id']
    monkeypatch.setattr(p,'throttle',lambda:None)
    attempts=[]
    def rejected(*args,**kwargs):
        attempts.append(1)
        return httpx.Response(status,json=payload)
    monkeypatch.setattr(p.httpx.Client,'post',rejected)
    key=vid+':rejected'
    with pytest.raises(p.ProviderFailure,match=expected):
        tracked_post(vid,key,'minimax','speech','test','https://example.com','test-secret-token',{})
    with pytest.raises(p.ProviderFailure):
        tracked_post(vid,key,'minimax','speech','test','https://example.com','test-secret-token',{})
    with Session() as db:
        call=db.query(Call).filter_by(key=key).one()
        assert expected in call.error and call.state=='failed'
        assert 'test-secret-token' not in call.error
    assert len(attempts)==1
