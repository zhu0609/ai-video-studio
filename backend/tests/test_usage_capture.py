"""Provider usage persistence tests; no network calls or production database access."""
from uuid import uuid4

import httpx
import pytest

from app import providers as p
from app.db import Call, Session, init_db


@pytest.fixture(autouse=True)
def isolated_provider_calls(monkeypatch):
    init_db()
    monkeypatch.setattr(p, 'throttle', lambda: None)
    monkeypatch.setattr(p.time, 'sleep', lambda _: None)


@pytest.mark.parametrize('fields,expected', [
    ({'usage': {}}, {}),
    ({'usage': 0, 'extra_info': {'usage_characters': 4}}, 0),
    ({'extra_info': {'usage_characters': 0, 'audio_length': 0}},
     {'usage_characters': 0, 'audio_length': 0}),
    ({'usage': {}, 'extra_info': {'usage_characters': 5}}, {'usage_characters': 5}),
    ({'usage': {'total_tokens': 0, 'completion_tokens_details': {'reasoning_tokens': 0}},
      'extra_info': {'usage_characters': 7, 'audio_length': 1234, 'total_tokens': 99}},
     {'usage_characters': 7, 'audio_length': 1234, 'total_tokens': 0,
      'completion_tokens_details': {'reasoning_tokens': 0}}),
])
def test_success_keeps_raw_usage_and_cached_calls_do_not_request_again(monkeypatch, fields, expected):
    response = {'id': 'provider-operation', **fields}
    requests = []
    def post(*args, **kwargs):
        requests.append(1)
        return httpx.Response(200, json=response)
    monkeypatch.setattr(p.httpx.Client, 'post', post)
    key = 'usage-success-' + uuid4().hex
    for _ in range(2):
        assert p.tracked_post('test-video', key, 'minimax', 'speech', 'test-model',
                              'https://example.invalid', '', {}) == response
    with Session() as db:
        call = db.query(Call).filter_by(key=key).one()
        assert call.usage == expected
        assert call.result == response
        assert call.attempts == 1
    assert len(requests) == 1


@pytest.mark.parametrize('status,payload,error,state', [
    (400, {'error': {'code': 'Rejected', 'message': 'invalid'}, 'usage': {'total_tokens': 13}},
     p.ProviderFailure, 'failed'),
    (200, {'base_resp': {'status_code': 1001, 'status_msg': 'failed'},
           'extra_info': {'usage_characters': 3}}, p.ProviderFailure, 'failed'),
    (503, {'error': {'code': 'Unavailable'}, 'usage': {'total_tokens': 8}},
     p.UncertainSubmission, 'uncertain'),
])
def test_unsuccessful_responses_still_record_reported_usage(monkeypatch, status, payload, error, state):
    attempts = []
    def post(*args, **kwargs):
        attempts.append(1)
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(p.httpx.Client, 'post', post)
    key = 'usage-error-' + uuid4().hex
    with pytest.raises(error):
        p.tracked_post('test-video', key, 'ark', 'text', 'test-model',
                       'https://example.invalid', '', {})
    with Session() as db:
        call = db.query(Call).filter_by(key=key).one()
        assert call.usage == payload.get('usage', payload.get('extra_info'))
        assert call.state == state
        assert call.attempts == 1
    assert len(attempts) == 1


def make_video_call(task_id, usage=None, video_id=None):
    with Session() as db:
        call = Call(video_id=video_id or uuid4().hex, key=uuid4().hex,
                    provider='ark', kind='video', model='test-model',
                    state='succeeded', attempts=1, result={'id': task_id}, usage=usage)
        db.add(call)
        db.commit()
        return call.id, call.video_id


@pytest.mark.parametrize('fields', [{}, {'usage': None}, {'usage': {}}])
def test_missing_poll_usage_does_not_erase_previous_usage(monkeypatch, fields):
    existing = {'completion_tokens': 108900, 'total_tokens': 108900}
    call_id, video_id = make_video_call('poll-existing', existing)
    payload = {'status': 'succeeded', 'content': {'video_url': 'https://example.invalid/clip.mp4'}, **fields}
    monkeypatch.setattr(p, 'safe_get', lambda *args: httpx.Response(200, json=payload))
    assert p.Seedance().poll(video_id, 'poll-existing').endswith('clip.mp4')
    with Session() as db:
        call = db.get(Call, call_id)
        assert call.usage == existing
        assert call.state == 'succeeded' and call.attempts == 1


def test_polling_replaces_snapshots_without_adding_or_touching_other_tasks(monkeypatch):
    call_id, video_id = make_video_call('poll-updates', {'total_tokens': 1, 'old_field': 2})
    other_id, _ = make_video_call('different-task', {'total_tokens': 5}, video_id)
    replies = iter([
        {'status': 'running', 'usage': {'completion_tokens': 20, 'total_tokens': 20}},
        {'status': 'succeeded', 'usage': {'completion_tokens': 30, 'total_tokens': 30},
         'content': {'video_url': 'https://example.invalid/result.mp4'}},
        {'status': 'succeeded', 'usage': {'completion_tokens': 30, 'total_tokens': 30},
         'content': {'video_url': 'https://example.invalid/result.mp4'}},
    ])
    monkeypatch.setattr(p, 'safe_get', lambda *args: httpx.Response(200, json=next(replies)))
    for _ in range(2):
        p.Seedance().poll(video_id, 'poll-updates')
    with Session() as db:
        assert db.get(Call, call_id).usage == {'completion_tokens': 30, 'total_tokens': 30}
        assert db.get(Call, other_id).usage == {'total_tokens': 5}
        assert db.get(Call, call_id).attempts == 1


@pytest.mark.parametrize('terminal', ['failed', 'cancelled', 'expired'])
def test_terminal_failure_captures_usage_without_changing_submission_state(monkeypatch, terminal):
    call_id, video_id = make_video_call('poll-terminal', {'total_tokens': 1})
    payload = {'status': terminal, 'usage': {'completion_tokens': 0, 'total_tokens': 0}}
    monkeypatch.setattr(p, 'safe_get', lambda *args: httpx.Response(200, json=payload))
    with pytest.raises(p.ProviderFailure, match=terminal):
        p.Seedance().poll(video_id, 'poll-terminal')
    with Session() as db:
        call = db.get(Call, call_id)
        assert call.usage == {'completion_tokens': 0, 'total_tokens': 0}
        assert call.state == 'succeeded' and call.result == {'id': 'poll-terminal'}
        assert call.attempts == 1
