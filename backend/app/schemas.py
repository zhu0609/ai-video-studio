from typing import Literal
from pydantic import BaseModel, Field, model_validator

class BatchCreate(BaseModel):
    theme: str = Field(min_length=2, max_length=200)
    brief: str = Field(default='', max_length=2000)
    count: int = Field(default=2, ge=1, le=20)
    duration: int = Field(default=12, ge=5, le=600)
    ratio: Literal['9:16', '16:9', '1:1'] = '9:16'
    style: str = Field(default='电影纪实', min_length=1, max_length=80)
    voice: bool = False
    subtitles: bool = True
    auto: bool = False
    mode: Literal['demo', 'live'] = 'demo'
    image_provider: Literal['seedream', 'comfyui'] = 'seedream'
    workflow_id: str | None = Field(default=None, max_length=100)
    reference_image: str | None = Field(default=None, max_length=200)
    seed: int = Field(default=2026, ge=0, le=2**31-1)

class ShotEdit(BaseModel):
    id: str
    duration: float = Field(ge=1, le=10)
    narration: str = Field(max_length=300)
    prompt: str = Field(min_length=2, max_length=3000)

class ScriptEdit(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    shots: list[ShotEdit] = Field(min_length=1, max_length=120)

class PlanShot(BaseModel):
    narration: str = Field(max_length=300)
    prompt: str = Field(min_length=2, max_length=3000)

class Plan(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    shots: list[PlanShot] = Field(min_length=1, max_length=120)

class Action(BaseModel):
    action: Literal['plan', 'generate', 'image', 'clip', 'compose', 'resume']
    shot_id: str | None = None

class Resolve(BaseModel):
    task_id: str = Field(default='', max_length=200)
    confirmed_not_accepted: bool = False
