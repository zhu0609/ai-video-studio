"""Native, self-hosted ComfyUI image adapter (not the Comfy Cloud API).

Only /prompt is a tracked generation submission. Once its prompt_id is saved,
recovery reads the same history/output, including after download failures.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
from pathlib import Path, PurePosixPath
import threading
import time
from urllib.parse import quote, urlsplit

import httpx
from PIL import Image

from .config import settings
from . import providers
from .providers import ProviderFailure, tracked_post
from .storage import storage


_generation_lock = threading.Lock()
_SIZES = {'9:16': (768, 1344), '16:9': (1344, 768), '1:1': (1024, 1024)}


def _base_url():
    value = settings.comfyui_base_url.strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProviderFailure('请配置有效的 COMFYUI_BASE_URL（原生 ComfyUI HTTP/HTTPS 服务地址）')
    return value


def _headers():
    token = settings.comfyui_api_key
    return {'Authorization': f'Bearer {token}'} if token else {}


@contextmanager
def _serial_generation(base):
    """One workflow at a time; a Redis lock spans all Celery worker processes."""
    with _generation_lock:
        if settings.execution_mode != 'celery':
            yield
            return
        from redis import Redis
        server_key = hashlib.sha256(base.encode()).hexdigest()[:20]
        # Covers upload, bounded history polling and output retries. Fail closed
        # if Redis is unavailable rather than accidentally overloading the GPU.
        lease = (settings.comfyui_timeout_seconds
                 + settings.request_timeout_seconds * 5 + 120)
        redis = Redis.from_url(settings.redis_url)
        lock = redis.lock('studio:comfyui:' + server_key, timeout=lease,
                          blocking_timeout=settings.comfyui_timeout_seconds + 60)
        try:
            acquired = lock.acquire()
        except Exception as exc:
            raise ProviderFailure('ComfyUI 并发锁不可用，请检查 Redis；尚未提交生成任务') from exc
        if not acquired:
            raise ProviderFailure('ComfyUI 正在处理其他工作流，请稍后恢复任务')
        try:
            yield
        finally:
            try:
                lock.release()
            except Exception:
                # A completed image must not be lost merely because releasing
                # the coordination lease fails; Redis expires the lease.
                pass


def _get(base, route, *, params=None):
    """GET only the configured origin. Redirects are never followed."""
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds,
                              follow_redirects=False) as client:
                response = client.get(base + route, headers=_headers(), params=params)
            if 300 <= response.status_code < 400:
                raise ProviderFailure('ComfyUI 返回重定向，已阻止；请填写最终服务地址')
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if attempt == 2:
                raise ProviderFailure('ComfyUI 查询或下载失败；原 prompt_id 已保留，恢复执行不会重新提交') from exc
            time.sleep(2 ** attempt)


def _json(response):
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('not an object')
        return data
    except (ValueError, TypeError) as exc:
        raise ProviderFailure('ComfyUI 响应不是有效 JSON 对象；原任务保留，请检查服务地址') from exc


def _safe_image_location(image):
    """Use output metadata as query values, never as a URL or local path."""
    filename = image.get('filename')
    folder = image.get('subfolder', '')
    kind = image.get('type', 'output')
    if (not isinstance(filename, str) or not filename or filename in ('.', '..')
            or any(c in filename for c in '/\\:\x00')
            or not isinstance(folder, str) or '\\' in folder or ':' in folder
            or '\x00' in folder or PurePosixPath(folder).is_absolute()
            or '..' in PurePosixPath(folder).parts or kind != 'output'):
        raise ProviderFailure('ComfyUI 返回的图片路径不安全或不是 SaveImage 输出')
    return {'filename': filename, 'subfolder': folder, 'type': kind}


def _bind(graph, bindings, name, value):
    binding = bindings.get(name)
    if not isinstance(binding, dict):
        raise ProviderFailure(f'ComfyUI 工作流缺少 {name} 输入绑定')
    node, field = str(binding.get('node', '')), binding.get('input')
    inputs = graph.get(node, {}).get('inputs', {})
    if not isinstance(field, str) or field not in inputs:
        raise ProviderFailure(f'ComfyUI 工作流 {name} 绑定无效，请重新导入 API 格式工作流')
    inputs[field] = value


class ComfyUIImage:
    def generate(self, video, batch, shot, target: Path):
        base = _base_url()
        snapshot = batch.comfy_workflow
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('workflow'), dict):
            raise ProviderFailure('当前项目没有 ComfyUI 工作流快照，请创建项目时选择已配置的工作流')
        original_server = snapshot.get('server_url')
        if original_server and original_server.rstrip('/') != base:
            raise ProviderFailure('ComfyUI 服务地址已改变，请恢复原服务配置或创建新项目；不会向新服务提交旧任务')
        with _serial_generation(base):
            key = f'{shot.id}:image:{shot.image_revision}'
            # Avoid even re-uploading the reference when /prompt already
            # succeeded. tracked_post returns the durable cached response.
            with providers.Session() as db:
                previous = db.query(providers.Call).filter_by(key=key).first()
                submitted = previous is not None and previous.state != 'ready'
            if submitted:
                result = tracked_post(video.id, key, 'comfyui', 'image',
                                      str(snapshot.get('id') or snapshot.get('name') or 'workflow'),
                                      base + '/prompt', settings.comfyui_api_key, {})
            else:
                graph = self._prepare(snapshot, video, batch, shot, base)
                result = tracked_post(video.id, key, 'comfyui', 'image',
                                      str(snapshot.get('id') or snapshot.get('name') or 'workflow'),
                                      base + '/prompt', settings.comfyui_api_key,
                                      {'prompt': graph, 'client_id': f'studio-{video.id}'})
            # Accept `id` too: the existing call-ledger resolve UI binds an
            # operator-verified prompt ID in this field after an ambiguous POST.
            prompt_id = result.get('prompt_id') or result.get('id')
            if not isinstance(prompt_id, str) or not prompt_id:
                raise ProviderFailure('ComfyUI 未返回 prompt_id；禁止自动重提，请核查调用记录')
            params = self._poll(base, prompt_id, str(snapshot.get('output_node', '')))
            response = _get(base, '/view', params=params)
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + '.tmp')
            try:
                with Image.open(io.BytesIO(response.content)) as image:
                    image.load()
                    image.convert('RGB').save(temporary, format='PNG')
                temporary.replace(target)
            except (OSError, ValueError) as exc:
                temporary.unlink(missing_ok=True)
                raise ProviderFailure('ComfyUI 输出不是可用图片；原 prompt_id 保留，可恢复下载') from exc

    def _prepare(self, snapshot, video, batch, shot, base):
        graph = deepcopy(snapshot['workflow'])
        bindings = snapshot.get('bindings', {})
        if not isinstance(bindings, dict):
            raise ProviderFailure('ComfyUI 工作流 bindings 必须是对象')
        output = graph.get(str(snapshot.get('output_node', '')), {})
        if output.get('class_type') != 'SaveImage':
            raise ProviderFailure('请将 ComfyUI 输出节点绑定到 SaveImage 节点')
        width, height = _SIZES.get(batch.ratio, (None, None))
        if width is None:
            raise ProviderFailure('ComfyUI 暂支持 9:16、16:9 和 1:1 画幅')
        seed = (batch.seed + (video.number - 1) * 1000 + shot.position - 1
                + (shot.image_revision - 1) * 100000)
        for name, value in [('prompt', f'{batch.style}，画幅比例{batch.ratio}。{shot.prompt}'),
                            ('width', width), ('height', height), ('seed', seed)]:
            _bind(graph, bindings, name, value)
        reference = getattr(batch, 'reference_image', None)
        if bindings.get('reference'):
            if not reference:
                raise ProviderFailure('这个 ComfyUI 工作流需要参考图，请上传参考图后创建项目')
            image_name = self._upload_reference(base, reference)
            _bind(graph, bindings, 'reference', image_name)
        elif reference:
            raise ProviderFailure('所选 ComfyUI 工作流没有参考图绑定，请使用支持参考图的工作流')
        return graph

    def _upload_reference(self, base, key):
        try:
            source = storage.path(key)
        except ValueError as exc:
            raise ProviderFailure('参考图存储路径无效') from exc
        if not source.is_file():
            raise ProviderFailure('参考图文件不存在，请重新上传')
        content = source.read_bytes()
        filename = 'studio-reference-' + hashlib.sha256(content).hexdigest()[:24] + '.png'
        # Multipart upload is not a generation call. Deterministic name with
        # overwrite prevents duplicate reference files on an explicit recovery.
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=False) as client:
                response = client.post(base + '/upload/image', headers=_headers(),
                                       files={'image': (filename, content, 'image/png')},
                                       data={'type': 'input', 'overwrite': 'true'})
            if 300 <= response.status_code < 400:
                raise ProviderFailure('ComfyUI 上传返回重定向，请填写最终服务地址')
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            raise ProviderFailure('ComfyUI 参考图上传失败，尚未提交生成任务') from exc
        result = _json(response)
        # The server may place an input file in a subfolder; reuse the same
        # strict path rules while requiring its returned type to be input.
        if result.get('type', 'input') != 'input':
            raise ProviderFailure('ComfyUI 参考图上传未返回 input 文件')
        location = _safe_image_location({'filename': result.get('name'),
                                         'subfolder': result.get('subfolder', ''), 'type': 'output'})
        return '/'.join(p for p in (location['subfolder'], location['filename']) if p)

    def _poll(self, base, prompt_id, output_node):
        started = time.monotonic()
        while time.monotonic() - started < settings.comfyui_timeout_seconds:
            data = _json(_get(base, '/history/' + quote(prompt_id, safe='')))
            entry = data.get(prompt_id)
            if entry is not None:
                if not isinstance(entry, dict):
                    raise ProviderFailure('ComfyUI 历史记录格式错误，原 prompt_id 已保留')
                status = entry.get('status') or {}
                messages = status.get('messages') or []
                if (status.get('status_str') in ('error', 'failed', 'interrupted')
                        or any(isinstance(m, (list, tuple)) and m
                               and m[0] in ('execution_error', 'execution_interrupted') for m in messages)):
                    raise ProviderFailure('ComfyUI 工作流执行失败；请检查模型、节点和显存，原 prompt_id 已保留')
                outputs = entry.get('outputs') or {}
                images = outputs.get(output_node, {}).get('images') or []
                if images:
                    return _safe_image_location(images[0])
                if status.get('completed'):
                    raise ProviderFailure('ComfyUI 已结束但指定 SaveImage 节点没有图片，请检查输出节点绑定')
            # An empty history can mean queued, running, or history cleared.
            # All are read-only waiting states; never infer permission to POST.
            time.sleep(settings.comfyui_poll_interval_seconds)
        raise ProviderFailure('ComfyUI 等待超时或历史记录缺失；原 prompt_id 保留，恢复执行只会继续查询')
