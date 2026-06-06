from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    id: str
    created_at: datetime
    updated_at: datetime
    rubric_id: str
    topic: str
    caption: str
    image_prompt: str
    image_path: str = ""
    image_provider: str = ""
    status: str = "draft"
    approved_by: Optional[int] = None
    published_at: Optional[datetime] = None
    telegram_message_id: Optional[int] = None
    error_message: Optional[str] = None
