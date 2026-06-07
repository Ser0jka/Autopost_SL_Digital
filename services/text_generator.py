import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BRAND_CONTEXT_PATH = BASE_DIR / "config" / "brand_context.json"
RUBRICS_PATH = BASE_DIR / "config" / "rubrics.json"
RUBRIC_SCHEDULE_PATH = BASE_DIR / "config" / "rubric_schedule.json"

FREE_LLM_MODEL_POOL = [
    "openai/gpt-oss-120b:free",
    "poolside/laguna-m.1:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/owl-alpha",
    "openrouter/free",
]

ABSOLUTE_CAPTION_MAX = 950
REGULAR_CAPTION_MIN = 700
REGULAR_CAPTION_MAX = 900
MEME_CAPTION_MIN = 350
MEME_CAPTION_MAX = 500

EDITORIAL_SYSTEM_PROMPT = """Ты сильный русскоязычный редактор Telegram-канала IT-агентства.
Твоя задача - писать живые, профессиональные посты, которые читаются как работа практикующей команды, а не как SEO-дайджест или корпоративная заготовка.
Пиши конкретно: ситуация, действие, причина, результат. Убирай общие слова, если их нельзя проверить на реальном проекте.
Сохраняй разметку и placeholders строго по пользовательскому заданию."""

VALID_PLACEHOLDERS = {
    "{{nut}}",
    "{{waynut}}",
    "{{money}}",
    "{{question}}",
    "{{check}}",
    "{{cross}}",
    "{{heart}}",
    "{{star}}",
    "{{growth}}",
    "{{like}}",
    "{{dot}}",
    "{{one}}",
    "{{two}}",
    "{{three}}",
    "{{four}}",
    "{{five}}",
    "{{terminal}}",
    "{{note}}",
    "{{bolt}}",
    "{{tools}}",
    "{{idea}}",
    "{{down}}",
    "{{gift}}",
    "{{rocket}}",
    "{{fire}}",
    "{{robot}}",
    "{{sparkles}}",
    "{{brain}}",
    "{{warning}}",
    "{{chart}}",
    "{{gear}}",
}

LIST_PLACEHOLDERS = ("one", "two", "three", "four", "five")

WEAK_CAPTION_PHRASES = (
    "эффективного управления",
    "наша команда имеет опыт",
    "комплексных it-решений",
    "это не только технологии",
    "важно правильно выбрать",
    "может помочь вашему бизнесу",
    "для вашего бизнеса",
    "реальные бизнес-задачи",
    "повысить эффективность",
    "оптимизировать процессы",
    "современные технологии",
    "индивидуальный подход",
    "качественные решения",
)

HARD_WEAK_CAPTION_PHRASES = (
    "мы собрали для вас",
    "ключевых мысл",
    "ключевых вывод",
    "бизнесы часто сталкиваются",
    "it-решения могут помочь",
    "дайджест из главных",
    "в современном мире",
    "в наше время",
    "сегодня бизнесу важно",
)

SPECIFICITY_MARKERS = (
    "mvp",
    "crm",
    "api",
    "бот",
    "заяв",
    "лид",
    "прототип",
    "метрик",
    "гипотез",
    "интеграц",
    "воронк",
    "сценари",
    "данн",
    "сайт",
    "форм",
    "менеджер",
    "клиент",
    "час",
    "день",
    "недел",
    "тест",
    "мокап",
    "админ",
    "кабинет",
    "сервер",
    "автоматизац",
)

UNICODE_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\uFE0F"
    "\u20E3"
    "]+"
)

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

    async def generate_post_text(
        self,
        rubric_id: str,
        recent_posts: list[dict],
        custom_topic: str = "",
    ) -> dict:
        rubric = self.rubrics.get(rubric_id)
        if not rubric:
            raise TextGenerationError(f"Unknown rubric: {rubric_id}")

        recent_topics = [p.get("topic", "") for p in recent_posts if p.get("topic")]
        prompt = self._build_prompt(rubric_id, rubric, recent_topics, custom_topic=custom_topic)
        return await self._call_and_parse_with_model_pool(prompt, rubric_id)

    async def revise_post_text(
        self,
        rubric_id: str,
        post: dict,
        revision_request: str,
    ) -> dict:
        rubric = self.rubrics.get(rubric_id)
        if not rubric:
            raise TextGenerationError(f"Unknown rubric: {rubric_id}")

        prompt = self._build_prompt(
            rubric_id,
            rubric,
            recent_topics=[],
            custom_topic=post.get("topic", ""),
            revision_request=revision_request,
            old_post=post,
        )
        return await self._call_and_parse_with_model_pool(prompt, rubric_id)

    async def _call_and_parse_with_model_pool(self, prompt: str, rubric_id: str) -> dict:
        errors: list[str] = []
        for route in self._llm_routes():
            route_name = self._route_name(route)
            try:
                raw = await self._call_llm(prompt, route)
                result = self._parse_and_validate(raw, rubric_id)
                result["_llm_provider"] = route["provider"]
                result["_llm_model"] = route["model"]
                logger.info("Text generated with LLM route: %s", route_name)
                return result
            except Exception as exc:
                logger.warning("LLM route failed: %s: %s", route_name, exc)
                errors.append(f"{route_name}: {exc}")

        detail = "; ".join(errors)
        raise TextGenerationError(f"All text LLM models failed: {detail}")

    async def plan_constructor_cover(
        self,
        post: dict,
        available_icons: list[str],
        request: str = "",
    ) -> dict:
        if not available_icons:
            raise TextGenerationError("No constructor icons found")

        prompt = f"""Подбери параметры для локального конструктора обложки Waynut.

Доступные иконки, выбери строго одну из списка:
{", ".join(available_icons)}

Пост:
topic: {post.get("topic", "")}
caption:
{post.get("caption", "")}

Дополнительный запрос админа:
{request or "нет"}

Верни только JSON:
{{
  "icon": "одно имя из списка без .png",
  "title": "короткий заголовок обложки до 32 символов",
  "subtitle": "подзаголовок до 56 символов"
}}

Правила:
- title должен отражать суть поста и быть читаемым на картинке.
- subtitle должен раскрывать пользу или конкретику.
- не используй кавычки, хэштеги и эмодзи в title/subtitle.
- если тема про продажи или заявки, чаще подходят sales, piplines, handshake.
- если тема про AI или ботов, чаще подходят ai, idea-bot.
- если тема про разработку, backend, код или архитектуру, чаще подходят program-monitor, vs-code, servers.
- если тема про сбои или проблемы, чаще подходят wifi-off, servers.
"""

        errors: list[str] = []
        for route in self._llm_routes():
            route_name = self._route_name(route)
            try:
                raw = await self._call_llm(prompt, route)
                result = self._parse_json(raw)
                icon = str(result.get("icon", "")).strip()
                if icon not in available_icons:
                    raise TextGenerationError(f"LLM chose unknown icon: {icon}")
                title = self._clean_cover_text(str(result.get("title", "")), 42)
                subtitle = self._clean_cover_text(str(result.get("subtitle", "")), 70)
                if not title:
                    raise TextGenerationError("LLM returned empty title")
                return {"icon": icon, "title": title, "subtitle": subtitle}
            except Exception as exc:
                logger.warning("Constructor cover planner failed: %s: %s", route_name, exc)
                errors.append(f"{route_name}: {exc}")

        logger.warning("All constructor planner models failed: %s", "; ".join(errors))
        return self._fallback_constructor_plan(post, available_icons)

    def _llm_routes(self) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []

        if (self.config.GROQ_API_KEY or "").strip():
            for model in self._split_models(self.config.GROQ_MODEL):
                routes.append(
                    {
                        "provider": "groq",
                        "base_url": self.config.GROQ_BASE_URL,
                        "api_key": self.config.GROQ_API_KEY,
                        "model": model,
                    }
                )

        if (self.config.TEXT_LLM_API_KEY or "").strip():
            for model in self._openrouter_model_pool():
                routes.append(
                    {
                        "provider": "openrouter",
                        "base_url": self.config.TEXT_LLM_BASE_URL,
                        "api_key": self.config.TEXT_LLM_API_KEY,
                        "model": model,
                    }
                )

        if not routes:
            raise TextGenerationError("GROQ_API_KEY or TEXT_LLM_API_KEY must be set")

        return routes

    def _openrouter_model_pool(self) -> list[str]:
        primary_model = (self.config.TEXT_LLM_MODEL or "").strip()
        if primary_model and primary_model not in FREE_LLM_MODEL_POOL:
            models = [primary_model, *FREE_LLM_MODEL_POOL]
        else:
            models = [*FREE_LLM_MODEL_POOL]
        seen = set()
        result = []
        for model in models:
            model = (model or "").strip()
            if model and model not in seen:
                seen.add(model)
                result.append(model)
        return result

    def _split_models(self, value: str) -> list[str]:
        return [model.strip() for model in (value or "").split(",") if model.strip()]

    def _route_name(self, route: dict[str, str]) -> str:
        return f"{route['provider']}:{route['model']}"

    def _fallback_constructor_plan(self, post: dict, available_icons: list[str]) -> dict:
        text = f"{post.get('topic', '')} {post.get('caption', '')}".lower()
        rules = [
            (("продаж", "заяв", "лид", "ворон"), "sales"),
            (("crm", "pipeline", "ворон"), "piplines"),
            (("бот", "ai", "нейро", "автомат"), "idea-bot"),
            (("код", "backend", "архитект", "разработ"), "program-monitor"),
            (("сервер", "систем", "инфраструкт"), "servers"),
            (("ошиб", "сбой", "не работает"), "wifi-off"),
            (("иде", "концепц"), "ai"),
        ]
        icon = available_icons[0]
        for keywords, candidate in rules:
            if candidate in available_icons and any(keyword in text for keyword in keywords):
                icon = candidate
                break
        title = self._clean_cover_text(str(post.get("topic", "")), 42) or "IT без хаоса"
        return {"icon": icon, "title": title, "subtitle": "Решение для роста бизнеса"}

    def _clean_cover_text(self, text: str, limit: int) -> str:
        text = re.sub(r"[#\"'`*_{}\[\]]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = self._remove_ellipsis(text)
        if len(text) <= limit:
            return text
        cut = text[: limit - 1].rfind(" ")
        if cut < limit // 2:
            cut = limit - 1
        return text[:cut].rstrip(".,:;")

    def _build_prompt(
        self,
        rubric_id: str,
        rubric: dict,
        recent_topics: list[str],
        custom_topic: str = "",
        revision_request: str = "",
        old_post: Optional[dict] = None,
    ) -> str:
        b = self.brand
        is_meme = rubric_id == "meme"
        min_len = MEME_CAPTION_MIN if is_meme else REGULAR_CAPTION_MIN
        max_len = MEME_CAPTION_MAX if is_meme else REGULAR_CAPTION_MAX
        recent_str = "\n".join(f"- {topic}" for topic in recent_topics[-20:]) or "нет"
        topic_block = f"\nТема от админа: {custom_topic}\n" if custom_topic else ""
        revision_block = ""
        if revision_request and old_post:
            revision_block = f"""
Доработка существующего поста.
Запрос админа: {revision_request}
Старый topic: {old_post.get("topic", "")}
Старый caption:
{old_post.get("caption", "")}

Сделай новую версию. Можно изменить caption, topic и метафору для картинки, если запрос этого требует.
"""

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
{topic_block}
{revision_block}

Требования:
- Верни только валидный JSON без markdown.
- Поле caption: {min_len}-{max_len} символов.
- Целевой объем caption для обычных рубрик: 750-900 символов. Для meme: 350-500 символов.
- Не делай короткий пост: лучше 3-4 содержательных абзаца и список, чем 1-2 общие фразы.
- Абсолютный максимум caption: {ABSOLUTE_CAPTION_MAX} символов.
- Пиши как человек из команды, который реально разбирает рабочую ситуацию. Не пиши как нейросеть, пресс-релиз, SEO-текст или "дайджест из главных выводов".
- В каждом посте должна быть конкретика: сценарий, процесс, решение, критерий, ошибка, метрика, ограничение или практический вывод. Общие фразы без действия запрещены.
- Не начинай с "Мы собрали", "Внедрение IT-решений - это", "5 ключевых мыслей", "IT-решения помогают бизнесу". Это звучит скудно.
- Не используй формулировки "бизнесы часто сталкиваются", "наша команда имеет опыт", "важно правильно выбрать технологии", если дальше нет конкретного действия или примера.
- Перед написанием внутренне выбери один угол поста: рабочий процесс, ошибка клиента, запуск MVP, автоматизация заявки, интеграция CRM, снижение ручной работы, проверка гипотезы, метрика, ограничение проекта. В JSON этот угол отдельно не выводи, но весь caption строй вокруг него.
- В тексте должен быть хотя бы один конкретный артефакт: прототип, API, CRM, форма заявки, бот, кабинет, метрика, мокап, сценарий пользователя, интеграция, таблица, воронка, заявка, менеджер.
- Не перечисляй абстрактные преимущества. Покажи, что именно команда делает руками и зачем.
- Пиши фразами средней длины. Не делай подряд 5 коротких лозунгов и не делай длинные канцелярские предложения.
- Не используй многоточия вообще и не ставь три точки подряд. Каждый абзац должен выглядеть завершенным.
- Для premium emoji используй только эти placeholders: {", ".join(sorted(VALID_PLACEHOLDERS))}.
- Не используй обычные Unicode emoji вообще. Только placeholders для premium emoji. Если подходящего placeholder нет, пиши без emoji.
- Используй 3-7 placeholders, но не перегружай текст.
- Для форматирования используй только HTML-теги: <b>жирный</b>, <i>курсив</i>, <u>подчеркнутый</u>, <s>зачеркнутый</s>, <code>код</code>, <blockquote>цитата</blockquote>.
- Не используй Markdown-оформление: **жирный**, __жирный__, `код`, > цитата.
- Оформляй caption красиво для Telegram: сильный первый хук, короткие абзацы, 3-4 смысловых блока, список из 3-4 пунктов, короткий вывод и мягкий CTA.
- Первый хук выделяй через <b>текст хука</b>. Внутри хука должна быть конкретная идея, а не название темы.
- Короткую важную мысль оформляй через <blockquote>текст вывода</blockquote>. Цитата должна быть не длиннее 120 символов.
- Для списков используй placeholders {{one}}, {{two}}, {{three}}, {{four}}, {{five}} или акцентные markers {{check}}, {{dot}}, {{growth}}.
- Каждый пункт списка пиши строго с новой строки. Не пиши несколько пунктов в одной строке.
- Перед списком и после списка ставь пустую строку.
- Формат списка:
  {{one}} первый пункт
  {{two}} второй пункт
  {{three}} третий пункт
- Не используй обычные цифры 1, 2, 3 как маркеры списка, только placeholders.
- После placeholder не ставь точку, двоеточие или тире. Пиши так: {{check}} текст пункта.
- Пункты списка делай короткими: 3-9 слов на пункт, без длинных сложных предложений.
- Не начинай CTA с {{dot}} или точки. CTA должен быть отдельным коротким абзацем.
- В конце добавляй мягкий CTA Waynut: @Waynut_Contact, сообщения каналу или info@waynut.ru, когда это уместно.
- Не пиши отдельное поле с текстом поста, только caption.
- image_prompt должен быть короткой темой/метафорой для обложки, а не полным техническим промптом.
- В image_prompt опиши, что именно должен символизировать главный 3D-объект.

Редакционный каркас для обычных рубрик:
1. <b>Хук</b>: конкретный тезис или рабочая ситуация.
2. Абзац контекста: что происходит в бизнесе/проекте и почему это важно.
3. Список: 3-4 практических шага, решения или наблюдения.
4. <blockquote>Короткий вывод</blockquote>
5. Финальный абзац: что получает бизнес / как Waynut подходит к задаче.
6. CTA: коротко, без давления.

Выбирай одну из композиционных формул:
- "ситуация -> как делаем -> почему так -> результат";
- "ошибка -> чем опасна -> как исправить -> что проверить";
- "гипотеза -> быстрый прототип -> тест -> решение";
- "хаос в процессе -> связка инструментов -> прозрачная воронка";
- "ручная работа -> автоматизация -> контроль -> экономия времени".

Перед финальным JSON мысленно проверь caption:
- есть ли живой хук, который хочется дочитать;
- есть ли конкретный проектный процесс, а не общие обещания;
- список стоит столбиком;
- quote звучит как вывод, а не как рекламный слоган;
- CTA не давит и не повторяет весь пост;
- текст похож на пост опытной команды Waynut.

Пример уровня оформления и живости, к которому нужно стремиться:
<b>Тестируем MVP за 72 часа - как это реально?</b>

Сначала собираем гипотезы и формируем минимальный набор функций. Затем в команде делим задачи:

{{one}} дизайн-прототип за 6 часов
{{two}} backend-мокап без полной инфраструктуры
{{three}} юзабилити-тесты на реальных сценариях

<blockquote>Минимум кода - максимум обратной связи.</blockquote>

Так за 3 дня появляется не "красивая идея", а набор метрик: что подтвердилось, где пользователю непонятно и что стоит дорабатывать дальше.

Готовы проверить идею в таком темпе? Напишите @Waynut_Contact или info@waynut.ru.

Верни JSON строго такой формы:
{{
  "topic": "название темы до 80 символов",
  "caption": "готовый caption для Telegram",
  "image_prompt": "тема и метафора для обложки, 1-2 предложения",
  "premium_emoji_plan": [
    {{"placeholder": "{{{{nut}}}}", "meaning": "бренд Waynut"}},
    {{"placeholder": "{{{{check}}}}", "meaning": "результат"}}
  ],
  "short_summary": "1-2 предложения о посте"
}}"""

    async def _call_llm(self, prompt: str, route: dict[str, str]) -> str:
        api_key = (route.get("api_key") or "").strip()
        base_url = (route.get("base_url") or "").strip().rstrip("/")
        model = (route.get("model") or "").strip()
        if not api_key or not base_url or not model:
            raise TextGenerationError(f"Invalid LLM route: {self._route_name(route)}")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": EDITORIAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.9,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                if response.status_code != 400:
                    raise
                logger.warning("LLM rejected response_format, retrying without JSON mode: %s", response.text[:500])
                payload.pop("response_format", None)
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
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
        self._validate_caption_length(result["caption"], rubric_id)
        self._validate_caption_quality(result["caption"], rubric_id)
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
        caption = self._strip_unicode_emoji(caption)
        caption = self._remove_ellipsis(caption)
        caption = self._format_caption_layout(caption)
        max_len = MEME_CAPTION_MAX if rubric_id == "meme" else REGULAR_CAPTION_MAX
        hard_max = min(max_len, ABSOLUTE_CAPTION_MAX)

        if len(caption) > hard_max:
            logger.warning("Caption length %s > %s, truncating", len(caption), hard_max)
            caption = self._truncate(caption, hard_max)

        if len(caption) > ABSOLUTE_CAPTION_MAX:
            caption = self._truncate(caption, ABSOLUTE_CAPTION_MAX)

        return caption

    def _validate_caption_length(self, caption: str, rubric_id: str) -> None:
        min_len = MEME_CAPTION_MIN if rubric_id == "meme" else REGULAR_CAPTION_MIN
        if len(caption) < min_len:
            raise TextGenerationError(f"Caption too short: {len(caption)} chars, need at least {min_len}")

    def _validate_caption_quality(self, caption: str, rubric_id: str) -> None:
        if rubric_id == "meme":
            return

        lower = caption.lower()
        if "..." in caption or "…" in caption:
            raise TextGenerationError("Caption contains ellipsis")

        hard_hits = [phrase for phrase in HARD_WEAK_CAPTION_PHRASES if phrase in lower]
        if hard_hits:
            raise TextGenerationError(f"Caption uses weak template phrase: {hard_hits[0]}")

        weak_hits = [phrase for phrase in WEAK_CAPTION_PHRASES if phrase in lower]
        if len(weak_hits) >= 2:
            raise TextGenerationError(f"Caption is too generic: {', '.join(weak_hits[:3])}")

        specificity_hits = [marker for marker in SPECIFICITY_MARKERS if marker in lower]
        if len(set(specificity_hits)) < 2:
            raise TextGenerationError("Caption lacks concrete project details")

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", caption) if part.strip()]
        if len(paragraphs) < 4:
            raise TextGenerationError("Caption needs at least 4 visual blocks")

        if not re.search(r"<b>[^<]{18,}</b>", caption):
            raise TextGenerationError("Caption needs a meaningful bold hook")

        has_list = bool(re.search(r"^{{(?:one|two|three|four|five|check|dot|growth)}}\s+", caption, re.MULTILINE))
        has_quote = "<blockquote>" in caption and "</blockquote>" in caption
        if not has_list:
            raise TextGenerationError("Caption needs a vertical practical list")
        if not has_quote:
            raise TextGenerationError("Caption needs a short blockquote insight")

    def _strip_unicode_emoji(self, text: str) -> str:
        return UNICODE_EMOJI_RE.sub("", text)

    def _remove_ellipsis(self, text: str) -> str:
        text = re.sub(r"\.{3,}", ".", text)
        text = text.replace("…", ".")
        text = re.sub(r"\s+\.", ".", text)
        return text

    def _format_caption_layout(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*({{(?:one|two|three|four|five)}})\s+", r"\n\1 ", text)
        text = re.sub(r"(?<!\n)\s+({{(?:check|dot|growth)}})\s+", r"\n\1 ", text)
        text = re.sub(r"(?m)^({{(?:one|two|three|four|five|check|dot|growth)}})[ \t.,;:]+", r"\1 ", text)

        lines = [line.strip() for line in text.splitlines()]
        result: list[str] = []
        previous_was_list = False

        for line in lines:
            if not line:
                if result and result[-1] != "":
                    result.append("")
                previous_was_list = False
                continue

            line = re.sub(r"^[\s.,;:]+", "", line).strip()
            is_list = bool(re.match(r"^{{(?:one|two|three|four|five|check|dot|growth)}}\s+", line))

            if is_list and result and result[-1] != "" and not previous_was_list:
                result.append("")
            if not is_list and previous_was_list and result and result[-1] != "":
                result.append("")

            result.append(line)
            previous_was_list = is_list

        text = "\n".join(result)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        cut = text[: limit - 3].rfind("\n")
        if cut < limit // 2:
            cut = text[: limit - 3].rfind(".")
        if cut < limit // 2:
            cut = limit - 3
        result = text[:cut].rstrip(" \n\t.,;:—-")
        if result and result[-1] not in ".!?":
            result += "."
        return result

    def _parse_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found")
        json_text = text[start:end]
        try:
            return json.loads(json_text, strict=False)
        except json.JSONDecodeError:
            return json.loads(self._escape_control_chars_in_strings(json_text), strict=False)

    def _fix_json(self, text: str) -> str:
        text = re.sub(r",\s*}", "}", text)
        return re.sub(r",\s*]", "]", text)

    def _escape_control_chars_in_strings(self, text: str) -> str:
        result = []
        in_string = False
        escaped = False
        for char in text:
            if escaped:
                result.append(char)
                escaped = False
                continue
            if char == "\\":
                result.append(char)
                escaped = True
                continue
            if char == '"':
                result.append(char)
                in_string = not in_string
                continue
            if in_string and char in {"\n", "\r", "\t"}:
                result.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
                continue
            result.append(char)
        return "".join(result)

    def _sanitize_placeholders(self, text: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1) or match.group(2)
            placeholder = f"{{{{{name}}}}}"
            return placeholder if placeholder in VALID_PLACEHOLDERS else ""

        return re.sub(r"\{\{(\w+)\}\}|\{(\w+)\}", replace, text)
