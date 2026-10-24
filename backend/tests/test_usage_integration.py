"""Verify project/video usage stays consistent with the independent reporting route."""
import uuid
import pytest
from fastapi.testclient import TestClient
from app.db import Batch, Call, Session, Video, init_db
from app.main import app


@pytest.fixture
def usage_project():
    init_db()
    batch_id, video_id = uuid.uuid4().hex, uuid.uuid4().hex
    with Session() as db:
        db.add(Batch(id=batch_id, theme='Usage integration', count=1, duration=5,
                     ratio='9:16', style='test', mode='live'))
        db.add(Video(id=video_id, batch_id=batch_id, number=1, title='Usage video', status='completed'))
        db.add_all([
            Call(video_id=video_id, key=uuid.uuid4().hex, provider='ark', kind='text',
                 model='test-endpoint', state='succeeded', attempts=3,
                 usage={'prompt_tokens': 20, 'completion_tokens': 100, 'total_tokens': 120,
                        'prompt_tokens_details': {'cached_tokens': 5},
                        'completion_tokens_details': {'reasoning_tokens': 40}},
                 result={'model': 'provider-returned-model', 'usage': {'total_tokens': 120}}),
            Call(video_id=video_id, key=uuid.uuid4().hex, provider='ark', kind='text',
                 model='test-endpoint', state='failed', attempts=1,
                 usage={'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}),
            Call(video_id=video_id, key=uuid.uuid4().hex, provider='minimax', kind='speech',
                 model='speech-test', state='failed', attempts=1,
                 usage={'usage_characters': 14, 'audio_length': 2000}),
        ])
        db.commit()
    yield batch_id, video_id
    with Session() as db:
        db.query(Call).filter_by(video_id=video_id).delete()
        db.query(Video).filter_by(id=video_id).delete()
        db.query(Batch).filter_by(id=batch_id).delete()
        db.commit()


def test_video_detail_matches_usage_scope(usage_project):
    batch_id, video_id = usage_project
    client = TestClient(app)
    project = client.get('/api/batches/' + batch_id).json()
    report = client.get('/api/usage', params={'video_id': video_id}).json()
    actual = project['videos'][0]['usage_summary']
    assert actual['summary'] == report['summary']
    assert actual['models'] == report['models']
    assert actual['summary']['total_tokens'] == 130
    assert actual['summary']['attempts'] == 5
    assert actual['summary']['cached_tokens'] == 5
    assert actual['summary']['reasoning_tokens'] == 40
    assert actual['summary']['speech_characters'] == 14
    assert actual['summary']['audio_seconds'] == 2
    assert any('provider-returned-model' in model['reported_models'] for model in actual['models'])


def test_demo_usage_not_presented_as_real_consumption(usage_project):
    batch_id, video_id = usage_project
    with Session() as db:
        db.get(Batch, batch_id).mode = 'demo'
        db.commit()
    client = TestClient(app)
    project = client.get('/api/batches/' + batch_id).json()
    report = client.get('/api/usage', params={'video_id': video_id}).json()
    assert project['videos'][0]['usage_summary']['summary']['calls'] == 0
    assert report['summary']['calls'] == 0
    assert report['summary']['total_tokens'] is None
