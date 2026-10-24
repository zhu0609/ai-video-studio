import time
import uuid
from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, JSON, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

engine = create_engine(settings.database_url, connect_args={'check_same_thread': False, 'timeout': 30} if settings.database_url.startswith('sqlite') else {}, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()
def uid(): return uuid.uuid4().hex

class Batch(Base):
    __tablename__ = 'batches'
    id = Column(String, primary_key=True, default=uid)
    theme = Column(Text, nullable=False)
    brief = Column(Text, default='')
    count = Column(Integer)
    duration = Column(Integer)
    ratio = Column(String)
    style = Column(String)
    voice = Column(Boolean)
    subtitles = Column(Boolean)
    auto = Column(Boolean)
    mode = Column(String)
    image_provider = Column(String, default='seedream', server_default='seedream')
    workflow_id = Column(String, nullable=True)
    reference_image = Column(String, nullable=True)
    seed = Column(Integer, default=2026, server_default='2026')
    comfy_workflow = Column(JSON, nullable=True)
    created = Column(Float, default=time.time)

class Video(Base):
    __tablename__ = 'videos'
    id = Column(String, primary_key=True, default=uid)
    batch_id = Column(String, index=True)
    number = Column(Integer)
    title = Column(Text, default='准备策划')
    status = Column(String, default='queued')
    revision = Column(Integer, default=1)
    output = Column(String, nullable=True)
    error = Column(Text, default='')
    active_job = Column(String, nullable=True)

class Shot(Base):
    __tablename__ = 'shots'
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, index=True)
    position = Column(Integer)
    duration = Column(Float)
    narration = Column(Text)
    prompt = Column(Text)
    revision = Column(Integer, default=1)
    image_revision = Column(Integer, default=1)
    clip_revision = Column(Integer, default=1)
    image = Column(String, nullable=True)
    clip = Column(String, nullable=True)
    audio = Column(String, nullable=True)
    image_status = Column(String, default='pending')
    clip_status = Column(String, default='pending')
    task_id = Column(String, nullable=True)
    error = Column(Text, default='')

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, index=True)
    action = Column(String)
    shot_id = Column(String, nullable=True)
    state = Column(String, default='queued', index=True)
    lease_until = Column(Float, default=0)
    owner = Column(String, nullable=True)
    error = Column(Text, default='')
    created = Column(Float, default=time.time)

class Call(Base):
    __tablename__ = 'calls'
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, index=True)
    key = Column(String, unique=True)
    provider = Column(String)
    kind = Column(String)
    model = Column(String)
    method = Column(String, default='POST')
    attempts = Column(Integer, default=0)
    state = Column(String, default='ready')
    request = Column(JSON, default=dict)
    result = Column(JSON, nullable=True)
    usage = Column(JSON, nullable=True)
    error = Column(Text, default='')
    created = Column(Float, default=time.time)

def init_db():
    with engine.begin() as conn:
        if engine.dialect.name == 'postgresql':
            from sqlalchemy import text
            conn.execute(text('SELECT pg_advisory_xact_lock(84579201)'))
        Base.metadata.create_all(conn)
        # Additive migration for databases created before optional ComfyUI support.
        from sqlalchemy import inspect, text
        columns = {c['name'] for c in inspect(conn).get_columns('batches')}
        additions = {
            'image_provider': "VARCHAR DEFAULT 'seedream'",
            'workflow_id': 'VARCHAR',
            'reference_image': 'VARCHAR',
            'seed': 'INTEGER DEFAULT 2026',
            'comfy_workflow': 'JSON',
        }
        for name, sql_type in additions.items():
            if name not in columns:
                conn.execute(text(f'ALTER TABLE batches ADD COLUMN {name} {sql_type}'))
