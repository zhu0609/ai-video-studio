"""Read-only, conservative aggregation of provider-reported usage.

Counts are a partial ledger, never a price estimate. Missing data stays None;
cached/reasoning tokens remain subsets and attempts never multiply usage.
"""
from collections.abc import Mapping
import math


COUNT_FIELDS = (
    'calls', 'attempts', 'succeeded_calls', 'failed_calls', 'pending_calls',
    'uncertain_calls', 'reported_calls', 'missing_usage_calls',
    'token_reported_calls',
)
MEASURE_FIELDS = (
    'total_tokens', 'input_tokens', 'output_tokens', 'cached_tokens',
    'reasoning_tokens', 'generated_images', 'speech_characters',
    'audio_seconds', 'text_tokens', 'image_tokens', 'video_tokens',
)
TOKEN_FIELDS = (
    'total_tokens', 'input_tokens', 'output_tokens', 'cached_tokens',
    'reasoning_tokens',
)


def _get(row, name, default=None):
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, *, integer=True):
    # Do not reinterpret numeric strings, booleans, invalid or negative values.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0 or (integer and int(value) != value):
        return None
    return int(value) if integer else value


def _sources(row):
    usage = _mapping(_get(row, 'usage'))
    result = _mapping(_get(row, 'result'))
    # New persisted usage takes precedence, while legacy fields can fill holes.
    # Read snapshots independently; do not add the same snapshot twice.
    return [usage, _mapping(usage.get('usage')), _mapping(usage.get('extra_info')),
            _mapping(result.get('usage')), _mapping(result.get('extra_info'))]


def _find(sources, *paths, integer=True):
    for source in sources:
        for path in paths:
            value = source
            for part in path.split('.'):
                value = _mapping(value).get(part)
            number = _number(value, integer=integer)
            if number is not None:
                return number
    return None


def normalize_usage(row):
    """Return only recognized numerical usage, including legacy result fallbacks."""
    sources = _sources(row)
    values = {name: None for name in MEASURE_FIELDS}
    values['input_tokens'] = _find(sources, 'prompt_tokens', 'input_tokens')
    values['output_tokens'] = _find(sources, 'completion_tokens', 'output_tokens')
    values['total_tokens'] = _find(sources, 'total_tokens')
    if values['total_tokens'] is None and values['input_tokens'] is not None and values['output_tokens'] is not None:
        values['total_tokens'] = values['input_tokens'] + values['output_tokens']
    values['cached_tokens'] = _find(sources, 'prompt_tokens_details.cached_tokens', 'input_tokens_details.cached_tokens', 'cached_tokens')
    values['reasoning_tokens'] = _find(sources, 'completion_tokens_details.reasoning_tokens', 'output_tokens_details.reasoning_tokens', 'reasoning_tokens')
    values['generated_images'] = _find(sources, 'generated_images')
    values['speech_characters'] = _find(sources, 'usage_characters')
    audio_ms = _find(sources, 'audio_length', integer=False)
    values['audio_seconds'] = audio_ms / 1000 if audio_ms is not None else None
    kind = _get(row, 'kind')
    if kind in ('text', 'image', 'video'):
        values[kind + '_tokens'] = values['total_tokens']
    return values


def _empty_summary():
    return {**dict.fromkeys(COUNT_FIELDS, 0), **dict.fromkeys(MEASURE_FIELDS, None)}


def _accumulate(target, row, values):
    target['calls'] += 1
    target['attempts'] += _number(_get(row, 'attempts')) or 0
    state = _get(row, 'state')
    state_field = {'succeeded': 'succeeded_calls', 'failed': 'failed_calls',
                   'uncertain': 'uncertain_calls'}.get(state, 'pending_calls')
    target[state_field] += 1
    # Ready rows with zero attempts remain visible as recorded calls, not spend.
    reported = any(value is not None for value in values.values())
    target['reported_calls' if reported else 'missing_usage_calls'] += 1
    target['token_reported_calls'] += int(any(values[key] is not None for key in TOKEN_FIELDS))
    for name, value in values.items():
        if value is not None:
            target[name] = (target[name] if target[name] is not None else 0) + value


def aggregate_calls(call_rows):
    """Aggregate every provided call, including failures and old revisions.

    Callers must apply live/demo and time filters first. State counts describe
    submission responses, not completion of asynchronous video generation.
    """
    summary = _empty_summary()
    groups = {}
    for row in call_rows:
        key = (_get(row, 'provider') or 'unknown', _get(row, 'kind') or 'unknown',
               _get(row, 'model') or '未记录')
        group = groups.setdefault(key, {**_empty_summary(), 'provider': key[0],
                                       'kind': key[1], 'model': key[2],
                                       'reported_models': [], 'last_called': None})
        reported_model = _mapping(_get(row, 'result')).get('model')
        if isinstance(reported_model, str) and reported_model.strip() and reported_model not in group['reported_models']:
            group['reported_models'].append(reported_model)
            group['reported_models'].sort()
        values = normalize_usage(row)
        _accumulate(summary, row, values)
        _accumulate(group, row, values)
        created = _number(_get(row, 'created'), integer=False)
        if created is not None:
            group['last_called'] = max(group['last_called'] or 0, created)
    return {'summary': summary, 'models': sorted(groups.values(), key=lambda item: (item['provider'], item['kind'], item['model']))}
