import csv
import io
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Batch, Call, Video
from app.usage import aggregate_calls, normalize_usage
from app import usage_routes


def call(kind='text', usage=None, **kwargs):
    return {'provider': 'ark', 'kind': kind, 'model': kind + '-model',
            'attempts': 1, 'state': 'succeeded', 'usage': usage, 'created': 123.5, **kwargs}


def test_real_provider_shapes_preserve_units_and_nested_token_subsets():
    report = aggregate_calls([
        call(usage={'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130,
                    'prompt_tokens_details': {'cached_tokens': 40},
                    'completion_tokens_details': {'reasoning_tokens': 20}}, attempts=3),
        call('image', {'generated_images': 1, 'output_tokens': 17800, 'total_tokens': 17800}),
        call('video', {'completion_tokens': 103818, 'total_tokens': 103818}),
        call('speech', {'usage_characters': 14, 'audio_length': 2232, 'word_count': 7,
                        'audio_sample_rate': 32000}, provider='minimax'),
    ])
    stats = report['summary']
    assert stats['total_tokens'] == 121748
    assert stats['input_tokens'] == 100 and stats['output_tokens'] == 121648
    assert stats['cached_tokens'] == 40 and stats['reasoning_tokens'] == 20
    assert (stats['text_tokens'], stats['image_tokens'], stats['video_tokens']) == (130, 17800, 103818)
    assert stats['generated_images'] == 1 and stats['speech_characters'] == 14
    assert stats['audio_seconds'] == 2.232
    assert stats['calls'] == 4 and stats['attempts'] == 6
    assert stats['reported_calls'] == 4 and stats['missing_usage_calls'] == 0
    assert stats['token_reported_calls'] == 3
    assert all(row['last_called'] == 123.5 for row in report['models'])


def test_missing_and_explicit_zero_are_distinct_in_empty_and_partial_totals():
    empty = aggregate_calls([])
    assert empty['summary']['calls'] == 0 and empty['summary']['total_tokens'] is None
    assert empty['models'] == []
    result = aggregate_calls([call(usage={'total_tokens': 0}), call(usage=None),
                              call('image', {'generated_images': 0}),
                              call('video', {'completion_tokens': 8})])
    stats = result['summary']
    assert stats['total_tokens'] == 0 and stats['output_tokens'] == 8
    assert stats['generated_images'] == 0
    assert stats['speech_characters'] is None and stats['audio_seconds'] is None
    assert stats['reported_calls'] == 3 and stats['missing_usage_calls'] == 1
    assert stats['token_reported_calls'] == 2
    video = next(row for row in result['models'] if row['kind'] == 'video')
    assert video['total_tokens'] is None and video['video_tokens'] is None
    assert video['output_tokens'] == 8  # No guessed input count or complete total.


@pytest.mark.parametrize('bad', [True, False, -1, float('inf'), float('-inf'), float('nan'), '123', [], {}, 1.2])
def test_malformed_token_values_are_not_reported_or_serialized(bad):
    stats = aggregate_calls([call(usage={'total_tokens': bad, 'input_tokens': bad,
                                      'output_tokens': bad, 'generated_images': bad,
                                      'prompt_tokens_details': {'cached_tokens': bad},
                                      'completion_tokens_details': {'reasoning_tokens': bad}})])['summary']
    assert stats['total_tokens'] is None and stats['input_tokens'] is None
    assert stats['output_tokens'] is None and stats['generated_images'] is None
    assert stats['reported_calls'] == 0 and stats['missing_usage_calls'] == 1


@pytest.mark.parametrize('bad', [True, -1, float('inf'), float('nan'), '123', [], {}])
def test_invalid_minimax_values_do_not_become_seconds_or_characters(bad):
    values = normalize_usage(call('speech', {'usage_characters': bad, 'audio_length': bad, 'word_count': 120}))
    assert values['speech_characters'] is None and values['audio_seconds'] is None
    assert values['total_tokens'] is None


def test_legacy_result_fallback_is_fieldwise_and_never_counts_snapshot_twice():
    row = SimpleNamespace(**call(usage={'prompt_tokens': 10, 'total_tokens': 20},
        result={'usage': {'prompt_tokens': 999, 'completion_tokens': 5, 'total_tokens': 1000,
                          'prompt_tokens_details': {'cached_tokens': 3}},
                'extra_info': {'usage_characters': 14, 'audio_length': 2232}}))
    values = normalize_usage(row)
    assert values['input_tokens'] == 10 and values['output_tokens'] == 5
    assert values['total_tokens'] == 20 and values['cached_tokens'] == 3
    assert values['speech_characters'] == 14 and values['audio_seconds'] == 2.232
    assert normalize_usage(call(usage={}, result={'usage': {}, 'extra_info': {'usage_characters': 0}}))['speech_characters'] == 0
    nested = normalize_usage(call(usage={'usage': {'input_tokens': 3, 'output_tokens': 4},
                                        'extra_info': {'audio_length': 1000}}))
    assert nested['total_tokens'] == 7 and nested['audio_seconds'] == 1


def test_total_is_derived_only_with_complete_input_and_output():
    assert normalize_usage(call(usage={'input_tokens': 3, 'output_tokens': 4}))['total_tokens'] == 7
    assert normalize_usage(call(usage={'prompt_tokens': 0, 'completion_tokens': 0}))['total_tokens'] == 0
    assert normalize_usage(call(usage={'output_tokens': 4}))['total_tokens'] is None
    assert normalize_usage(call(usage={'input_tokens': 3}))['total_tokens'] is None
    assert normalize_usage(call(usage={'total_tokens': 2, 'input_tokens': 3, 'output_tokens': 4}))['total_tokens'] == 2


def test_reported_models_are_explicit_deduplicated_and_do_not_change_configured_group():
    rows = [call(result={'model': 'version-b'}), call(result={'model': 'version-a'}),
            call(result={'model': 'version-b'}), call(result={'model': None})]
    result = aggregate_calls(rows)
    assert len(result['models']) == 1
    assert result['models'][0]['model'] == 'text-model'
    assert result['models'][0]['reported_models'] == ['version-a', 'version-b']


def test_grouping_keeps_revisions_repairs_failures_and_statuses_without_attempt_multiplier():
    rows = [call(usage={'total_tokens': 11}, key='old-plan-revision', attempts=3),
            call(usage={'total_tokens': 7}, key='new-plan-revision', state='failed', attempts=2),
            call(usage={'total_tokens': 5}, key='plan-repair', state='succeeded'),
            call('video', state='submitted'), call('image', state='uncertain'),
            call('speech', state='ready', attempts=0)]
    result = aggregate_calls(rows)
    stats = result['summary']
    assert stats['calls'] == 6 and stats['attempts'] == 8
    assert stats['total_tokens'] == 23
    assert (stats['succeeded_calls'], stats['failed_calls'], stats['pending_calls'], stats['uncertain_calls']) == (2, 1, 2, 1)
    text_model = next(row for row in result['models'] if row['kind'] == 'text')
    assert text_model['calls'] == 3 and text_model['total_tokens'] == 23
    assert stats['reported_calls'] + stats['missing_usage_calls'] == stats['calls']


@pytest.fixture
def usage_client(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'usage.db').as_posix(), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(usage_routes, 'Session', factory)
    monkeypatch.setattr(usage_routes, 'time', SimpleNamespace(time=lambda: 2_000_000))
    with factory() as db:
        db.add_all([Batch(id='live', theme='真实批次', mode='live'), Batch(id='other', theme='其他真实批次', mode='live'),
                    Batch(id='demo', theme='演示批次', mode='demo')])
        db.add_all([Video(id='v-live', batch_id='live'), Video(id='v-other', batch_id='other'), Video(id='v-demo', batch_id='demo')])
        for id, video, kind, usage, created in [
            ('old', 'v-live', 'text', {'total_tokens': 100}, 1),
            ('current', 'v-live', 'text', {'total_tokens': 25}, 1_999_000),
            ('other-current', 'v-other', 'image', {'generated_images': 2}, 1_999_000),
            ('demo-call', 'v-demo', 'text', {'total_tokens': 99999}, 1_999_000),
        ]:
            db.add(Call(id=id, key=id, video_id=video, provider='ark', kind=kind, model='test-' + kind,
                        state='succeeded', attempts=1, usage=usage, created=created,
                        request={'api_key': 'SECRET-REQUEST'}, result={'sensitive': 'SECRET-RESULT'}))
        db.commit()
    app = FastAPI()
    app.include_router(usage_routes.router)
    client = TestClient(app)
    yield client, factory
    client.close()
    engine.dispose()


def test_routes_exclude_demo_and_filter_on_call_time_without_deleting_old_revisions(usage_client):
    client, _ = usage_client
    result = client.get('/api/usage').json()
    assert result['summary']['calls'] == 3 and result['summary']['total_tokens'] == 125
    assert result['scope'] == {'batch_id': None, 'video_id': None, 'days': None, 'since': None}
    assert result['generated_at'] == 2_000_000
    recent = client.get('/api/usage?days=7').json()
    assert recent['summary']['calls'] == 2 and recent['summary']['total_tokens'] == 25
    assert recent['scope']['since'] == 2_000_000 - 7 * 86400
    assert client.get('/api/usage?days=30').status_code == 200
    scoped = client.get('/api/usage?batch_id=live&video_id=v-live').json()
    assert scoped['summary']['calls'] == 2 and scoped['summary']['total_tokens'] == 125
    assert client.get('/api/usage?video_id=v-other').json()['summary']['generated_images'] == 2
    assert client.get('/api/usage?batch_id=demo').json()['summary']['calls'] == 0
    assert client.get('/api/usage?video_id=v-demo').json()['summary']['total_tokens'] is None


def test_report_queries_project_usage_fields_and_recover_legacy_result(usage_client):
    client, factory = usage_client
    with factory() as db:
        row = db.get(Call, 'current')
        row.usage = None
        row.result = {'usage': {'total_tokens': 44}, 'extra_info': {'usage_characters': 7},
                      'model': 'reported-version', 'data': {'audio': 'LARGE-PRIVATE-MEDIA'}}
        db.commit()
    result = client.get('/api/usage?video_id=v-live').json()
    assert result['summary']['total_tokens'] == 144
    assert result['summary']['speech_characters'] == 7
    assert result['models'][0]['reported_models'] == ['reported-version']
    assert 'LARGE-PRIVATE-MEDIA' not in str(result)


@pytest.mark.parametrize('query,status', [('days=1', 422), ('days=0', 422), ('days=-7', 422), ('days=all', 422),
    ('batch_id=missing', 404), ('video_id=missing', 404), ('batch_id=live&video_id=v-other', 422)])
def test_report_and_csv_share_filter_validation(usage_client, query, status):
    client, _ = usage_client
    assert client.get('/api/usage?' + query).status_code == status
    assert client.get('/api/usage/export.csv?' + query).status_code == status


def test_csv_has_model_rows_safe_spreadsheet_cells_and_no_sensitive_columns(usage_client):
    client, factory = usage_client
    with factory() as db:
        db.add(Call(id='formula', key='formula', video_id='v-live', provider='=1+1', kind='text',
                    model=' \t@HYPERLINK("https://invalid")', attempts=1, state='succeeded',
                    usage={'total_tokens': 0}, created=1_999_999, request={'api_key': 'SECRET-REQUEST'},
                    result={'sensitive': 'SECRET-RESULT'}))
        db.commit()
    result = client.get('/api/usage/export.csv?batch_id=live')
    assert result.status_code == 200 and result.content.startswith(b'\xef\xbb\xbf')
    assert result.headers['content-disposition'] == 'attachment; filename="model-usage.csv"'
    decoded = result.content.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(decoded)))
    assert len(rows) == 2
    formula = next(row for row in rows if '1+1' in row['provider'])
    assert formula['provider'].startswith("'=") and formula['model'].startswith("'")
    assert formula['total_tokens'] == '0'
    assert formula['speech_characters'] == ''
    assert not any(secret in decoded for secret in ('SECRET', 'request', 'result', 'api_key', 'demo-call'))
