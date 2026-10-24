from celery import Celery
from .config import settings
from .db import init_db
from .pipeline import execute, pending_ids

celery=Celery('studio',broker=settings.redis_url,backend=settings.redis_url)
celery.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,beat_schedule={'recover-outbox':{'task':'studio.dispatch','schedule':10.0}})

@celery.task(name='studio.execute')
def run_job(job_id):
    init_db(); execute(job_id)

@celery.task(name='studio.dispatch')
def dispatch():
    init_db()
    for job_id in pending_ids(): run_job.delay(job_id)
