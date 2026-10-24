"""Native ComfyUI contract tests: no external endpoint or paid model is used."""
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import comfy, providers
from app.db import Base, Call


def workflow(reference=False):
    graph = {
        '3': {'class_type': 'KSampler', 'inputs': {'seed': 0}},
        '5': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 512, 'height': 512}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'original'}},
        '9': {'class_type': 'SaveImage', 'inputs': {'images': ['8', 0]}}
    }
    bindings = {'seed': {'node': '3', 'input': 'seed'},
                'width': {'node': '5', 'input': 'width'},
                'height': {'node': '5', 'input': 'height'},
                'prompt': {'node': '6', 'input': 'text'}}
    if reference:
        graph['10'] = {'class_type': 'LoadImage', 'inputs': {'image': 'placeholder.png'}}
        bindings['reference'] = {'node': '10', 'input': 'image'}
    return {'id': 'contract-test', 'name': 'Contract test', 'workflow': graph,
            'bindings': bindings, 'output_node': '9', 'server_url': 'http://comfy.test:8188'}


def objects(reference=False, **batch_overrides):
    video = SimpleNamespace(id='video-test', number=2)
    shot = SimpleNamespace(id='shot-test', position=3, image_revision=2,
                           prompt='清晨稻田，缓慢推进', task_id='seedance-unchanged')
    fields = {'style': '电影感', 'ratio': '9:16', 'seed': 42,
              'reference_image': 'reference.png' if reference else None,
              'comfy_workflow': workflow(reference)}
    fields.update(batch_overrides)
    return video, SimpleNamespace(**fields), shot


def png_bytes():
    output = io.BytesIO()
    Image.new('RGB', (24, 32), 'green').save(output, format='PNG')
    return output.getvalue()


def history(prompt_id='prompt-test', **kwargs):
    entry = {'status': {'completed': True, 'status_str': 'success'},
             'outputs': {'9': {'images': [{'filename': 'result.png',
                                            'subfolder': 'studio', 'type': 'output'}]}}}
    entry.update(kwargs)
    return {prompt_id: entry}


@pytest.fixture
def isolation(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'calls.sqlite').as_posix())
    Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(providers, 'Session', session)
    monkeypatch.setattr(providers, 'throttle', lambda: None)
    for key, value in {'comfyui_base_url': 'http://comfy.test:8188',
                       'comfyui_api_key': 'test-only-token',
                       'comfyui_timeout_seconds': 30,
                       'comfyui_poll_interval_seconds': 0,
                       'execution_mode': 'local', 'request_timeout_seconds': 1}.items():
        monkeypatch.setattr(comfy.settings, key, value)
    original_client = httpx.Client
    requests = []

    def install(handler):
        def record(request):
            requests.append(request)
            return handler(request)
        transport = httpx.MockTransport(record)
        monkeypatch.setattr(httpx, 'Client',
                            lambda *args, **kwargs: original_client(*args, transport=transport, **kwargs))

    yield SimpleNamespace(session=session, requests=requests, install=install, tmp=tmp_path)
    engine.dispose()


def basic_handler(request):
    if request.url.path == '/prompt':
        return httpx.Response(200, json={'prompt_id': 'prompt-test', 'number': 1, 'node_errors': {}})
    if request.url.path.startswith('/history/'):
        return httpx.Response(200, json=history())
    if request.url.path == '/view':
        return httpx.Response(200, content=png_bytes(), headers={'content-type': 'image/png'})
    raise AssertionError(str(request.url))


@pytest.mark.parametrize('ratio,dimensions', [('9:16', (768, 1344)),
                                             ('16:9', (1344, 768)), ('1:1', (1024, 1024))])
def test_payload_dimensions_seed_snapshot_and_call_ledger(isolation, ratio, dimensions):
    isolation.install(basic_handler)
    video, batch, shot = objects(ratio=ratio)
    before = deepcopy(batch.comfy_workflow)
    target = isolation.tmp / 'result.png'
    comfy.ComfyUIImage().generate(video, batch, shot, target)
    posted = json.loads(isolation.requests[0].content)
    graph = posted['prompt']
    assert graph['3']['inputs']['seed'] == 101044
    assert (graph['5']['inputs']['width'], graph['5']['inputs']['height']) == dimensions
    assert '电影感' in graph['6']['inputs']['text'] and shot.prompt in graph['6']['inputs']['text']
    assert batch.comfy_workflow == before
    assert shot.task_id == 'seedance-unchanged'
    assert Image.open(target).size == (24, 32)
    assert all(r.headers['authorization'] == 'Bearer test-only-token' for r in isolation.requests)
    with isolation.session() as db:
        call = db.query(Call).one()
        assert call.provider == 'comfyui' and call.kind == 'image'
        assert call.model == 'contract-test' and call.attempts == 1
        assert call.result['prompt_id'] == 'prompt-test'
        assert 'test-only-token' not in json.dumps(call.request)


def test_reference_upload_is_injected_and_not_uploaded_again_on_recovery(isolation, monkeypatch):
    (isolation.tmp / 'reference.png').write_bytes(png_bytes())
    monkeypatch.setattr(comfy, 'storage', SimpleNamespace(path=lambda key: isolation.tmp / key))

    def handler(request):
        if request.url.path == '/upload/image':
            assert b'name="image"' in request.content
            assert b'studio-reference-' in request.content
            assert b'name="overwrite"' in request.content
            return httpx.Response(200, json={'name': 'uploaded.png', 'subfolder': 'refs', 'type': 'input'})
        return basic_handler(request)

    isolation.install(handler)
    video, batch, shot = objects(reference=True)
    adapter = comfy.ComfyUIImage()
    adapter.generate(video, batch, shot, isolation.tmp / 'first.png')
    adapter.generate(video, batch, shot, isolation.tmp / 'recovered.png')
    posted = next(r for r in isolation.requests if r.url.path == '/prompt')
    assert json.loads(posted.content)['prompt']['10']['inputs']['image'] == 'refs/uploaded.png'
    assert sum(r.url.path == '/upload/image' for r in isolation.requests) == 1
    assert sum(r.url.path == '/prompt' for r in isolation.requests) == 1


def test_download_failure_recovers_without_resubmitting(isolation):
    fail = True

    def handler(request):
        if request.url.path == '/view' and fail:
            return httpx.Response(200, text='not an image')
        return basic_handler(request)

    isolation.install(handler)
    video, batch, shot = objects()
    target = isolation.tmp / 'result.png'
    with pytest.raises(providers.ProviderFailure, match='不是可用图片'):
        comfy.ComfyUIImage().generate(video, batch, shot, target)
    assert not target.exists()
    fail = False
    comfy.ComfyUIImage().generate(video, batch, shot, target)
    assert target.is_file()
    assert sum(r.url.path == '/prompt' for r in isolation.requests) == 1


def test_queued_missing_history_then_success_is_read_only(isolation):
    checks = []

    def handler(request):
        if request.url.path.startswith('/history/'):
            checks.append(1)
            return httpx.Response(200, json={} if len(checks) == 1 else history())
        return basic_handler(request)

    isolation.install(handler)
    comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert len(checks) == 2
    assert sum(r.url.path == '/prompt' for r in isolation.requests) == 1


def test_timeout_retains_prompt_and_resume_uses_it(isolation, monkeypatch):
    isolation.install(basic_handler)
    monkeypatch.setattr(comfy.settings, 'comfyui_timeout_seconds', 0)
    with pytest.raises(providers.ProviderFailure, match='超时'):
        comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    monkeypatch.setattr(comfy.settings, 'comfyui_timeout_seconds', 30)
    comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert sum(r.url.path == '/prompt' for r in isolation.requests) == 1


def test_lost_submission_response_never_reposts(isolation):
    def handler(request):
        raise httpx.ReadTimeout('response lost after accepted', request=request)

    isolation.install(handler)
    for _ in range(2):
        with pytest.raises(providers.UncertainSubmission):
            comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert len(isolation.requests) == 1


@pytest.mark.parametrize('unsafe', [
    {'filename': '../../secret.png'}, {'filename': 'http://evil.test/image.png'},
    {'filename': 'image.png', 'subfolder': '../secret'},
    {'filename': 'image.png', 'subfolder': 'C:\\secret'},
])
def test_output_path_cannot_escape_or_choose_another_host(isolation, unsafe):
    def handler(request):
        if request.url.path.startswith('/history/'):
            return httpx.Response(200, json=history(outputs={'9': {'images': [unsafe]}}))
        return basic_handler(request)

    isolation.install(handler)
    with pytest.raises(providers.ProviderFailure, match='路径不安全'):
        comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert not any(r.url.path == '/view' for r in isolation.requests)


def test_download_redirect_is_never_followed(isolation):
    def handler(request):
        if request.url.path == '/view':
            return httpx.Response(302, headers={'location': 'https://evil.test/leak'})
        return basic_handler(request)

    isolation.install(handler)
    with pytest.raises(providers.ProviderFailure, match='重定向'):
        comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert all(r.url.host == 'comfy.test' for r in isolation.requests)


def test_server_change_blocked_before_network(isolation, monkeypatch):
    isolation.install(basic_handler)
    monkeypatch.setattr(comfy.settings, 'comfyui_base_url', 'http://another.test:8188')
    with pytest.raises(providers.ProviderFailure, match='服务地址已改变'):
        comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert isolation.requests == []


@pytest.mark.parametrize('reference,has_binding', [(False, True), (True, False)])
def test_reference_contract_is_not_silently_ignored(isolation, reference, has_binding):
    isolation.install(basic_handler)
    video, batch, shot = objects(reference=reference)
    batch.comfy_workflow = workflow(has_binding)
    with pytest.raises(providers.ProviderFailure, match='参考图'):
        comfy.ComfyUIImage().generate(video, batch, shot, isolation.tmp / 'result.png')
    assert isolation.requests == []


def test_execution_error_keeps_id_and_never_downloads(isolation):
    def handler(request):
        if request.url.path.startswith('/history/'):
            return httpx.Response(200, json=history(status={'completed': False, 'status_str': 'error'}, outputs={}))
        return basic_handler(request)

    isolation.install(handler)
    for _ in range(2):
        with pytest.raises(providers.ProviderFailure, match='工作流执行失败'):
            comfy.ComfyUIImage().generate(*objects(), isolation.tmp / 'result.png')
    assert sum(r.url.path == '/prompt' for r in isolation.requests) == 1
    assert not any(r.url.path == '/view' for r in isolation.requests)
