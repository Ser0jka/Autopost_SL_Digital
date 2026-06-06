import json
import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BRAND_CONTEXT_PATH = BASE_DIR / "config" / "brand_context.json"
RUBRICS_PATH = BASE_DIR / "config" / "rubrics.json"
RUBRIC_SCHEDULE_PATH = BASE_DIR / "config" / "rubric_schedule.json"

ABSOLUTE_CAPTION_MAX = 950
REGULAR_CAPTION_MIN = 500
REGULAR_CAPTION_MAX = 900
MEME_CAPTION_MIN = 250
MEME_CAPTION_MAX = 500

VALID_PLACEHOLDERS = {
    "{{rocket}}",
    "{{fire}}",
    "{{robot}}",
    "{{sparkles}}",
    "{{brain}}",
    "{{warning}}",
    "{{chart}}",
    "{{gear}}",
}

IMAGE_PROMPT_TEMPLATE = """Create a 16:9 cover image for a Telegram post in one consistent modern brand style.
Image style: premium 3D render, clean digital / AI / startup style, soft studio lighting, neat volumetric shapes, minimalism, expensive technological visual, smooth abstract background waves, clean composition, lots of free space, depth, soft shadows, high quality.
Color palette: warm light background, orange / yellow accents, deep black or graphite details, and optionally one additional contrasting color if it fits the topic.
Composition: the main 3D object is centered or slightly below center, large, expressive, and directly connected to the post theme.
Background: abstract, branded, not overloaded.
The image must look good in a Telegram feed and remain readable at small size.
Post theme: {theme}
What to depict: create a metaphorical 3D object that visually communicates the post theme. Use clear symbols only when they fit: robot, neural network, API, automation, money, growth, project launch, testing, calendar, rocket, interface, code, documents, charts, funnel, chatbot, server, cloud, gears, brain, cursor, cards, checklist.
Restrictions: no text in the image, no letters, no captions, no logos of famous companies, no watermarks, no faces of real people, no realistic people, no chaos, no tiny unreadable details, no screenshots of known service interfaces.
Quality: ultra clean, premium 3D illustration, high detail, smooth shapes, soft gradients, cinematic lighting, professional Telegram cover, 16:9 aspect ratio."""


class TextGenerationError(Exception):
    pass


class TextGenerator:
    def __init__(self, config):
        self.config = config
        self.brand = json.loads(BRAND_CONTEXT_PATH.read_text(encoding="utf-8"))
        self.rubrics = json.loads(RUBRICS_PATH.read_text(encoding="utf-8"))
        self.rubric_schedule = json.loads(RUBRIC_SCHEDULE_PATH.read_text(encoding="utf-8"))

    async def generate_post_text(self, rubric_id: str, recent_posts: list[dict]) -> dict:
        rubric = self.rubrics.get(rubric_id)
        if not rubric:
            raise TextGenerationError(f"Unknown rubric: {rubric_id}")

        recent_topics = [p.get("topic", "") for p in recent_posts if p.get("topic")]
        prompt = self._build_prompt(rubric_id, rubric, recent_topics)
        raw = await self._call_llm(prompt)
        return self._parse_and_validate(raw, rubric_id)

    def _build_prompt(self, rubric_id: str, rubric: dict, recent_topics: list[str]) -> str:
        b = self.brand
        is_meme = rubric_id == "meme"
        min_len = MEME_CAPTION_MIN if is_meme else REGULAR_CAPTION_MIN
        max_len = MEME_CAPTION_MAX if is_meme else REGULAR_CAPTION_MAX
        recent_str = "\n".join(f"- {topic}" for topic in recent_topics[-20:]) or "нет"

        return f"""Ты контент-менеджер агентства {b["brand_name"]}.
Пиши для Telegram-канала. Пост будет опубликован одним сообщением: картинка и caption под ней.

Бренд:
- слоган: {b["slogan"]}
- позиционирование: {b["positioning"]}
- описание: {b["description"]}
- аудитория: {b["audience"]}
- тон: {b["tone"]}
- нельзя: {", ".join(b["forbidden"])}

Рубрика:
- id: {rubric_id}
- название: {rubric["name"]}
- описание: {rubric["description"]}
- цель: {rubric["goal"]}
- тон рубрики: {rubric["tone"]}
- формат: {rubric["format"]}

Недавние темы, их нельзя повторять:
{recent_str}

Требования:
- Верни только валидный JSON без markdown.
- Поле caption: {min_len}-{max_len} символов.
- Абсолютный максимум caption: {ABSOLUTE_CAPTION_MAX} символов.
- Для premium emoji используй только эти placeholders: {", ".join(sorted(VALID_PLACEHOLDERS))}.
- Используй 1-3 placeholders, не придумывай другие.
- Не пиши отдельное поле с текстом поста, только caption.
- image_prompt должен быть короткой темой/метафорой для обложки, а не полным техническим промптом.
- В image_prompt опиши, что именно должен символизировать главный 3D-объект.

Верни JSON строго такой формы:
{{
  "topic": "название темы до 80 символов",
  "caption": "готовый caption для Telegram",
  "image_prompt": "тема и метафора для обложки, 1-2 предложения",
  "premium_emoji_plan": [
    {{"placeholder": "{{{{rocket}}}}", "meaning": "рост"}}
  ],
  "short_summary": "1-2 предложения о посте"
}}"""

    async def _call_llm(self, prompt: str) -> str:
        if not self.config.TEXT_LLM_API_KEY:
            raise TextGenerationError("TEXT_LLM_API_KEY not set")

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.config.TEXT_LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.TEXT_LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.TEXT_LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 1800,
                },
            )
            response.raise_for_status()

        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Unexpected LLM response shape: %s", data)
            raise TextGenerationError("LLM returned an unexpected response") from exc

        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not content:
            finish_reason = data.get("choices", [{}])[0].get("finish_reason")
            logger.error("LLM returned empty content. finish_reason=%s response=%s", finish_reason, data)
            raise TextGenerationError(
                "LLM returned empty content. Check TEXT_LLM_MODEL or try another model."
            )

        return str(content).strip()

    def _parse_and_validate(self, raw: str, rubric_id: str) -> dict:
        try:
            result = self._parse_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("JSON parse failed (%s), retrying with simple cleanup", exc)
            result = self._parse_json(self._fix_json(raw))

        for field in ("topic", "caption", "image_prompt"):
            if not result.get(field):
                raise TextGenerationError(f"LLM response missing field: {field}")

        result["topic"] = str(result["topic"]).strip()[:80]
        result["caption"] = self._normalize_caption(str(result["caption"]), rubric_id)
        result["image_prompt"] = self._build_image_prompt(str(result["image_prompt"]).strip())
        result.setdefault("premium_emoji_plan", [])
        result.setdefault("short_summary", "")
        return result

    def _build_image_prompt(self, theme: str) -> str:
        theme = re.sub(r"\s+", " ", theme).strip()
        if not theme:
            theme = "digital automation and AI growth for business"
        return IMAGE_PROMPT_TEMPLATE.format(theme=theme)

    def _normalize_caption(self, caption: str, rubric_id: str) -> str:
        caption = self._sanitize_placeholders(caption.strip())
        max_len = MEME_CAPTION_MAX if rubric_id == "meme" else REGULAR_CAPTION_MAX
        hard_max = min(max_len, ABSOLUTE_CAPTION_MAX)

        if len(caption) > hard_max:
            logger.warning("Caption length %s > %s, truncating", len(caption), hard_max)
            caption = self._truncate(caption, hard_max)

        if len(caption) > ABSOLUTE_CAPTION_MAX:
            caption = self._truncate(caption, ABSOLUTE_CAPTION_MAX)

        return caption

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        cut = text[: limit - 3].rfind("\n")
        if cut < limit // 2:
            cut = text[: limit - 3].rfind(".")
        if cut < limit // 2:
            cut = limit - 3
        return text[:cut].rstrip() + "..."

    def _parse_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found")
        return json.loads(text[start:end])

    def _fix_json(self, text: str) -> str:
        text = re.sub(r",\s*}", "}", text)
        return re.sub(r",\s*]", "]", text)

    def _sanitize_placeholders(self, text: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1) or match.group(2)
            placeholder = f"{{{{{name}}}}}"
            return placeholder if placeholder in VALID_PLACEHOLDERS else ""

        return re.sub(r"\{\{(\w+)\}\}|\{(\w+)\}", replace, text)
