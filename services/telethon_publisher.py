import json
import logging
import re
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import MessageEntityCustomEmoji

from app.config import get_config

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CUSTOM_EMOJI_PATH = BASE_DIR / "config" / "custom_emoji.json"
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}|\{(\w+)\}")

DEFAULT_EMOJI = {
    "{{rocket}}": "\U0001f680",
    "{{fire}}": "\U0001f525",
    "{{robot}}": "\U0001f916",
    "{{sparkles}}": "\u2728",
    "{{brain}}": "\U0001f9e0",
    "{{warning}}": "\u26a0\ufe0f",
    "{{chart}}": "\U0001f4c8",
    "{{gear}}": "\u2699\ufe0f",
}


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _normalize_placeholder(match: re.Match) -> str:
    name = match.group(1) or match.group(2)
    return f"{{{{{name}}}}}"


def _custom_emoji_config() -> dict:
    if not CUSTOM_EMOJI_PATH.exists():
        return {}
    return json.loads(CUSTOM_EMOJI_PATH.read_text(encoding="utf-8"))


def build_caption_entities(caption: str) -> tuple[str, list[MessageEntityCustomEmoji]]:
    emoji_config = _custom_emoji_config()
    result = ""
    entities: list[MessageEntityCustomEmoji] = []
    pos = 0

    for match in PLACEHOLDER_RE.finditer(caption):
        placeholder = _normalize_placeholder(match)
        result += caption[pos : match.start()]

        conf = emoji_config.get(placeholder, {})
        alt = conf.get("alt") or DEFAULT_EMOJI.get(placeholder, "")
        document_id = conf.get("document_id")

        if not alt:
            result += match.group(0)
            pos = match.end()
            continue

        offset = _utf16_len(result)
        result += alt

        if document_id:
            entities.append(
                MessageEntityCustomEmoji(
                    offset=offset,
                    length=_utf16_len(alt),
                    document_id=int(document_id),
                )
            )

        pos = match.end()

    result += caption[pos:]
    return result, entities


def render_plain_caption(caption: str) -> str:
    text, _entities = build_caption_entities(caption)
    return text


async def publish_photo_post(channel: str, image_path: str, caption: str) -> int:
    config = get_config()
    if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
        raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH must be set")

    caption_text, entities = build_caption_entities(caption)

    client = TelegramClient(
        config.TELETHON_SESSION_NAME,
        config.TELETHON_API_ID,
        config.TELETHON_API_HASH,
    )

    async with client:
        try:
            message = await client.send_file(
                entity=channel,
                file=image_path,
                caption=caption_text,
                formatting_entities=entities or None,
            )
        except Exception as exc:
            if not entities:
                raise
            logger.exception("Custom emoji entities failed, publishing plain caption: %s", exc)
            message = await client.send_file(
                entity=channel,
                file=image_path,
                caption=caption_text,
            )

    return int(message.id)
