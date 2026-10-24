"""Configure isolation before importing any application module."""
import os
import tempfile
from pathlib import Path
import pytest

_temporary=tempfile.TemporaryDirectory(prefix='frameflow-tests-')
os.environ['DATABASE_URL']='sqlite:///'+(Path(_temporary.name)/'studio.db').as_posix()
os.environ['MEDIA_DIR']=str(Path(_temporary.name)/'media')
os.environ['EXECUTION_MODE']='local'
for name in ('ARK_API_KEY','MINIMAX_API_KEY','TEXT_MODEL','SEEDREAM_MODEL','SEEDANCE_MODEL','MINIMAX_MODEL','COMFYUI_API_KEY','COMFYUI_BASE_URL'):
    os.environ[name]=''

@pytest.fixture(scope='session',autouse=True)
def clean_database():
    yield
    from app.db import engine
    engine.dispose()
    _temporary.cleanup()
