"""Usage reporting over existing live call records; never invokes a provider."""
import csv
import io
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from .db import Batch, Video, Call, Session
from .usage import COUNT_FIELDS, MEASURE_FIELDS, aggregate_calls


router = APIRouter(prefix='/api/usage', tags=['usage'])


def usage_report(batch_id=None, video_id=None, days=None):
    if days is not None and days not in (7, 30):
        raise HTTPException(422, '时间范围仅支持 7 天、30 天或全部')
    now = time.time()
    since = now - days * 86400 if days is not None else None
    with Session() as db:
        if batch_id is not None and not db.get(Batch, batch_id):
            raise HTTPException(404, '批次不存在')
        if video_id is not None:
            video = db.get(Video, video_id)
            if not video:
                raise HTTPException(404, '视频不存在')
            if batch_id is not None and video.batch_id != batch_id:
                raise HTTPException(422, '视频不属于所选批次')
        # Project only the small allowlisted fields from JSON results. Loading
        # whole result objects would repeatedly read speech hex/image base64.
        query = db.query(Call.provider, Call.kind, Call.model, Call.state, Call.attempts, Call.usage, Call.created,
                         Call.result['usage'].label('result_usage'),
                         Call.result['extra_info'].label('result_extra_info'),
                         Call.result['model'].label('result_model')).join(Video, Call.video_id == Video.id).join(Batch, Video.batch_id == Batch.id).filter(Batch.mode == 'live')
        if batch_id is not None:
            query = query.filter(Batch.id == batch_id)
        if video_id is not None:
            query = query.filter(Video.id == video_id)
        if since is not None:
            query = query.filter(Call.created >= since)
        def compact_rows():
            for row in query:
                values = dict(row._mapping)
                values['result'] = {'usage': values.pop('result_usage'),
                                    'extra_info': values.pop('result_extra_info'),
                                    'model': values.pop('result_model')}
                yield values
        aggregate = aggregate_calls(compact_rows())
    return {'scope': {'batch_id': batch_id, 'video_id': video_id, 'days': days, 'since': since},
            **aggregate, 'generated_at': now}


@router.get('')
def get_usage(batch_id: str | None = None, video_id: str | None = None,
              days: int | None = Query(default=None)):
    return usage_report(batch_id, video_id, days)


def _csv_value(value):
    if value is None:
        return ''
    if isinstance(value, str):
        # CSV quoting alone does not prevent spreadsheet formula evaluation.
        original = value
        value = value.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
        if original.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@')):
            value = "'" + value
    return value


@router.get('/export.csv')
def export_usage(batch_id: str | None = None, video_id: str | None = None,
                 days: int | None = Query(default=None)):
    report = usage_report(batch_id, video_id, days)
    # Explicit allowlist: never export requests, provider results or credentials.
    columns = ('provider', 'kind', 'model', 'reported_models', *COUNT_FIELDS, *MEASURE_FIELDS, 'last_called')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(columns)
    for model in report['models']:
        writer.writerow([_csv_value('; '.join(model.get(column, [])) if column == 'reported_models' else model.get(column)) for column in columns])
    return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="model-usage.csv"', 'Cache-Control': 'no-store'})
