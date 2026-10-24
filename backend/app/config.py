from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore')
    database_url: str = 'sqlite:///' + (ROOT / 'data/studio.db').as_posix()
    redis_url: str = 'redis://localhost:6379/0'
    execution_mode: str = 'local'
    media_dir: Path = ROOT / 'data/media'
    frontend_dir: Path = ROOT / 'frontend/dist'
    ffmpeg_path: str = ''
    font_path: str = ''
    ark_api_key: str = ''
    ark_base_url: str = 'https://ark.cn-beijing.volces.com/api/v3'
    text_model: str = ''
    text_response_format: str = 'auto'
    seedream_model: str = ''
    seedance_model: str = ''
    seedream_size: str = '2K'
    seedance_resolution: str = '720p'
    output_short_edge: int = 720
    seedance_clip_seconds: int = 5
    minimax_api_key: str = ''
    minimax_base_url: str = 'https://api.minimax.cn/v1'
    minimax_model: str = ''
    minimax_voice: str = 'male-qn-qingse'
    comfyui_base_url: str = ''
    comfyui_api_key: str = ''
    comfyui_timeout_seconds: int = 900
    comfyui_poll_interval_seconds: float = 2
    provider_interval_seconds: float = 2
    poll_interval_seconds: float = 10
    video_timeout_seconds: int = 1800
    request_timeout_seconds: int = 180
    lease_seconds: int = 120

settings = Settings()
settings.media_dir.mkdir(parents=True, exist_ok=True)
(ROOT / 'data').mkdir(exist_ok=True)

def missing_config(voice: bool = True, image_provider: str = 'seedream'):
    names = ['ark_api_key', 'text_model', 'seedance_model']
    names += ['comfyui_base_url'] if image_provider == 'comfyui' else ['seedream_model']
    if voice:
        names += ['minimax_api_key', 'minimax_model', 'minimax_voice']
    return [n.upper() for n in names if not getattr(settings, n)]
