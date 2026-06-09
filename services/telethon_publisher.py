import json
import logging
import re
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageEntityBlockquote,
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityCustomEmoji,
    MessageEntityItalic,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
)

from app.config import get_config

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CUSTOM_EMOJI_PATH = BASE_DIR / "config" / "custom_emoji.json"
CAPTION_TOKEN_RE = re.compile(
    r"<br\s*/?>|<a\s+href=[\"'][^\"']+[\"']\s*>|</a\s*>|</?(?:b|strong|i|em|u|s|strike|code|blockquote)\s*>|\{\{(\w+)\}\}|\{(\w+)\}",
    re.IGNORECASE,
)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)

CUSTOM_EMOJI_ALT = {
    "{{eyes}}": "\U0001f440",
    "{{bang}}": "\u203c\ufe0f",
    "{{nut}}": "\U0001f95c",
    "{{waynut}}": "\U0001f95c",
    "{{money}}": "\U0001f4b2",
    "{{question}}": "\u2753",
    "{{check}}": "\u2714\ufe0f",
    "{{cross}}": "\u2716\ufe0f",
    "{{heart}}": "\U0001f9e1",
    "{{star}}": "\u2b50",
    "{{growth}}": "\u2197\ufe0f",
    "{{like}}": "\U0001f44d",
    "{{dot}}": "\u2022",
    "{{one}}": "1\ufe0f\u20e3",
    "{{two}}": "2\ufe0f\u20e3",
    "{{three}}": "3\ufe0f\u20e3",
    "{{four}}": "4\ufe0f\u20e3",
    "{{five}}": "5\ufe0f\u20e3",
    "{{terminal}}": "\U0001f4bb",
    "{{note}}": "\U0001f4dd",
    "{{bolt}}": "\u26a1",
    "{{tools}}": "\U0001f6e0\ufe0f",
    "{{idea}}": "\U0001f4a1",
    "{{down}}": "\u2b07\ufe0f",
    "{{gift}}": "\U0001f381",
    "{{rocket}}": "\U0001f680",
    "{{fire}}": "\U0001f525",
    "{{robot}}": "\U0001f916",
    "{{sparkles}}": "\u2728",
    "{{brain}}": "\U0001f9e0",
    "{{warning}}": "\u26a0\ufe0f",
    "{{chart}}": "\U0001f4c8",
    "{{gear}}": "\u2699\ufe0f",
    "{{up}}": "\U0001f53c",
    "{{hundred}}": "\U0001f4af",
    "{{smile}}": "\U0001f642",
    "{{cash}}": "\U0001f4b5",
}

ENTITY_BY_TAG = {
    "b": MessageEntityBold,
    "i": MessageEntityItalic,
    "u": MessageEntityUnderline,
    "s": MessageEntityStrike,
    "code": MessageEntityCode,
    "blockquote": MessageEntityBlockquote,
}

TAG_ALIASES = {
    "strong": "b",
    "em": "i",
    "strike": "s",
}


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _normalize_placeholder_name(name: str) -> str:
    return f"{{{{{name}}}}}"


def _custom_emoji_config() -> dict:
    if not CUSTOM_EMOJI_PATH.exists():
        return {}
    return json.loads(CUSTOM_EMOJI_PATH.read_text(encoding="utf-8"))


def _clean_rendered_caption(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^[ \t.,;:]+", "", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _caption_entity(
    entity_type: type,
    offset: int,
    length: int,
):
    return entity_type(offset=offset, length=length)


def _tag_name(token: str) -> str:
    name = token.strip("<>/ ").split()[0].lower()
    return TAG_ALIASES.get(name, name)


def build_caption_entities(caption: str, *, include_custom_emoji: bool = True) -> tuple[str, list]:
    emoji_config = _custom_emoji_config()
    result = ""
    entities: list = []
    open_tags: list[tuple[str, int, str | None]] = []
    pos = 0

    for match in CAPTION_TOKEN_RE.finditer(caption):
        result += caption[pos : match.start()]
        token = match.group(0)

        if token.lower().startswith("<br"):
            result += "\n"
            pos = match.end()
            continue

        if token.startswith("<"):
            closing = token.startswith("</")
            tag = _tag_name(token)
            if tag not in ENTITY_BY_TAG and tag != "a":
                pos = match.end()
                continue

            if closing:
                for index in range(len(open_tags) - 1, -1, -1):
                    open_tag, offset, url = open_tags[index]
                    if open_tag != tag:
                        continue
                    del open_tags[index]
                    length = _utf16_len(result) - offset
                    if length > 0:
                        if tag == "a" and url:
                            entities.append(MessageEntityTextUrl(offset=offset, length=length, url=url))
                        else:
                            entities.append(_caption_entity(ENTITY_BY_TAG[tag], offset, length))
                    break
            else:
                url = None
                if tag == "a":
                    href_match = HREF_RE.search(token)
                    url = href_match.group(1) if href_match else None
                open_tags.append((tag, _utf16_len(result), url))
            pos = match.end()
            continue

        name = match.group(1) or match.group(2)
        placeholder = _normalize_placeholder_name(name)
        conf = emoji_config.get(placeholder, {})
        document_id = conf.get("document_id")
        if not include_custom_emoji or not document_id:
            pos = match.end()
            continue

        alt = conf.get("alt") or CUSTOM_EMOJI_ALT.get(placeholder) or "\u25cc"
        offset = _utf16_len(result)
        result += alt
        entities.append(
            MessageEntityCustomEmoji(
                offset=offset,
                length=_utf16_len(alt),
                document_id=int(document_id),
            )
        )

        pos = match.end()

    result += caption[pos:]
    end_offset = _utf16_len(result)
    for tag, offset, url in reversed(open_tags):
        length = end_offset - offset
        if length > 0:
            if tag == "a" and url:
                entities.append(MessageEntityTextUrl(offset=offset, length=length, url=url))
            elif tag in ENTITY_BY_TAG:
                entities.append(_caption_entity(ENTITY_BY_TAG[tag], offset, length))

    entities.sort(key=lambda entity: (entity.offset, -entity.length))
    return result, entities


def render_plain_caption(caption: str) -> str:
    text, _entities = build_caption_entities(caption, include_custom_emoji=False)
    return _clean_rendered_caption(text)


def render_preview_caption(caption: str) -> str:
    emoji_config = _custom_emoji_config()

    def replace(match: re.Match) -> str:
        name = match.group(1) or match.group(2)
        placeholder = _normalize_placeholder_name(name)
        return emoji_config.get(placeholder, {}).get("alt") or CUSTOM_EMOJI_ALT.get(placeholder) or ""

    return _clean_rendered_caption(re.sub(r"\{\{(\w+)\}\}|\{(\w+)\}", replace, caption))


def telethon_session():
    config = get_config()
    if config.TELETHON_SESSION_STRING:
        return StringSession(config.TELETHON_SESSION_STRING)
    return config.TELETHON_SESSION_NAME


async def publish_photo_post(channel: str, image_path: str, caption: str) -> int:
    config = get_config()
    if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
        raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH must be set")

    caption_text, entities = build_caption_entities(caption)

    client = TelegramClient(telethon_session(), config.TELETHON_API_ID, config.TELETHON_API_HASH)

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
            fallback_text, fallback_entities = build_caption_entities(caption, include_custom_emoji=False)
            logger.exception("Custom emoji entities failed, publishing without premium emoji: %s", exc)
            message = await client.send_file(
                entity=channel,
                file=image_path,
                caption=fallback_text,
                formatting_entities=fallback_entities or None,
            )

    return int(message.id)


async def publish_text_post(channel: str, text: str) -> int:
    config = get_config()
    if not config.TELETHON_API_ID or not config.TELETHON_API_HASH:
        raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH must be set")

    caption_text, entities = build_caption_entities(text)
    client = TelegramClient(telethon_session(), config.TELETHON_API_ID, config.TELETHON_API_HASH)

    async with client:
        try:
            message = await client.send_message(
                entity=channel,
                message=caption_text,
                formatting_entities=entities or None,
            )
        except Exception as exc:
            if not entities:
                raise
            fallback_text, fallback_entities = build_caption_entities(text, include_custom_emoji=False)
            logger.exception("Custom emoji entities failed, publishing without premium emoji: %s", exc)
            message = await client.send_message(
                entity=channel,
                message=fallback_text,
                formatting_entities=fallback_entities or None,
            )

    return int(message.id)
