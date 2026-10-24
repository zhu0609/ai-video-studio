from pathlib import Path
from typing import Protocol
from .config import settings

class Storage(Protocol):
    def path(self, key: str) -> Path: ...
    def url(self, key: str) -> str: ...

class LocalStorage:
    """Replace this implementation with an object-store adapter; keys remain portable."""
    def path(self, key: str) -> Path:
        target = (settings.media_dir / key).resolve()
        if not target.is_relative_to(settings.media_dir.resolve()):
            raise ValueError('Invalid media key')
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
    def url(self, key: str) -> str:
        return '/media/' + key

storage: Storage = LocalStorage()
