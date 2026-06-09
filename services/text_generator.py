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
    "openrouter/owl-alpha",
    "openai/gpt-oss-120b:free",
    "poolside/laguna-m.1:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]

ABSOLUTE_CAPTION_MAX = 950
REGULAR_CAPTION_MIN = 700
REGULAR_CAPTION_MAX = 900
MEME_CAPTION_MIN = 350
MEME_CAPTION_MAX = 500

EDITORIAL_SYSTEM_PROMPT = """Ты сильный русскоязычный редактор Telegram-канала digital-агентства и бизнес-медиа.
Твоя задача - писать живые, профессиональные посты про бизнес, рост, продажи, продукт, маркетинг, операционку и digital-системы.
Пиши как практикующая команда, которая видит бизнес целиком: оффер, клиентский путь, процессы, деньги, команду, сервис, аналитику и технологии.
Пиши конкретно: ситуация, действие, причина, результат. Убирай общие слова, если их нельзя проверить на реальном проекте.
Сохраняй разметку и placeholders строго по пользовательскому заданию. СТРОГО укладывайся в 900 символов, мы делаем caption для tg message, ЭТО ОЧЕНЬ ВАЖНО"""

VALID_PLACEHOLDERS = {
    "{{eyes}}",
    "{{bang}}",
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
    "{{up}}",
    "{{hundred}}",
    "{{smile}}",
    "{{cash}}",
}

PROMPT_PLACEHOLDERS = {
    "{{eyes}}",
    "{{bang}}",
    "{{money}}",
    "{{fire}}",
    "{{up}}",
    "{{hundred}}",
    "{{down}}",
    "{{bolt}}",
    "{{sparkles}}",
    "{{smile}}",
    "{{cash}}",
    "{{one}}",
    "{{two}}",
    "{{three}}",
    "{{four}}",
    "{{five}}",
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
    "оффер",
    "марж",
    "прибыл",
    "выруч",
    "себестоим",
    "юнит",
    "unit",
    "ltv",
    "cac",
    "чек",
    "повторн",
    "удержан",
    "сервис",
    "скрипт",
    "регламент",
    "отдел продаж",
    "воркфлоу",
    "команд",
    "найм",
    "KPI",
    "kpi",
    "план",
    "ассортимент",
    "ниш",
    "позиционирован",
    "ценообраз",
)

BUSINESS_ANGLE_POOL = (
    "оффер и позиционирование",
    "первый экран и обещание для клиента",
    "воронка продаж и обработка заявок",
    "скрипты менеджеров и скорость ответа",
    "повторные продажи и удержание",
    "unit-экономика, маржа, средний чек",
    "упаковка продукта и тарифная сетка",
    "маркетинговые гипотезы и бюджет",
    "операционные процессы и регламенты",
    "сервис, клиентский опыт и доверие",
    "команда, найм и зоны ответственности",
    "аналитика, KPI и управленческие решения",
    "запуск нового направления или MVP",
    "контент как часть продаж, а не просто охваты",
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
                result = await self._parse_validate_or_repair(raw, rubric_id, route, route_name)
                result["_llm_provider"] = route["provider"]
                result["_llm_model"] = route["model"]
                logger.info("Text generated with LLM route: %s", route_name)
                return result
            except Exception as exc:
                log = logger.info if self._is_soft_llm_route_error(exc) else logger.warning
                log("LLM route failed: %s: %s", route_name, exc)
                errors.append(f"{route_name}: {exc}")

        detail = "; ".join(errors)
        raise TextGenerationError(f"All text LLM models failed: {detail}")

    async def _parse_validate_or_repair(
        self,
        raw: str,
        rubric_id: str,
        route: dict[str, str],
        route_name: str,
    ) -> dict:
        last_error: TextGenerationError | None = None
        for attempt in range(3):
            try:
                return self._parse_and_validate(raw, rubric_id)
            except TextGenerationError as exc:
                last_error = exc
                if not self._is_caption_length_error(exc) or attempt == 2:
                    raise
                logger.info("Caption length issue with LLM route %s, retrying rewrite: %s", route_name, exc)
                repair_prompt = self._build_caption_length_repair_prompt(raw, rubric_id, str(exc))
                raw = await self._call_llm(repair_prompt, route)

        raise last_error or TextGenerationError("Caption repair failed")

    async def plan_constructor_cover(
        self,
        post: dict,
        available_icons: list[str],
        request: str = "",
    ) -> dict:
        if not available_icons:
            raise TextGenerationError("No constructor icons found")

        prompt = f"""Подбери параметры для локального конструктора обложки SL Digital AI.

Доступные фоны из data/background, выбери строго один из списка:
{", ".join(available_icons)}

Пост:
topic: {post.get("topic", "")}
caption:
{post.get("caption", "")}

Дополнительный запрос админа:
{request or "нет"}

Верни только JSON:
{{
  "icon": "одно имя фона из списка без .png",
  "title": "яркий заголовок обложки до 34 символов",
  "subtitle": "подзаголовок до 60 символов",
  "details": ["2-3 коротких тезиса для нижнего блока, каждый до 38 символов"]
}}

Правила:
- title должен быть законченной мыслью: 2-5 слов, понятно о чем пост даже без subtitle.
- title не должен заканчиваться на предлог, союз, тире или голое число. Плохо: "AI-завод креативов за 2". Хорошо: "Креативы без рутины" или "200 креативов в месяц".
- если используешь число в title, рядом должна быть единица смысла: "за 2 дня", "200 идей в месяц", "5 ошибок в CRM".
- subtitle должен раскрывать пользу или конкретику, а не повторять title.
- не используй кавычки, хэштеги и эмодзи в title/subtitle.
- если тема про AI, нейросети или автоматизацию, чаще подходят AI-neural, automatisation-n8n.
- если тема про разработку, код, backend, MVP или веб-приложения, чаще подходят code-dev-work, terminal-programming-vibe.
- если тема про маркетинг, рекламу, продажи, упаковку и бизнес, чаще подходят marketing-work-buisness, buisness-promo-ourcorp-logo.
- если тема про контент, соцсети, Reels, Shorts или YouTube, чаще подходят contentmaker-sells, socialmedia-posts, youtube-feed-noise-tape.
- если тема про дизайн, визуал или брендинг, чаще подходит design-graphic.
- если тема про ошибки, хаос или проблемы, чаще подходит mistakes-problems-fuckups.
- title должен быть более дерзким и живым, но без крика и дешёвого инфобизнеса.
- subtitle должен звучать как конкретная выгода или интрига.
- details - это нижний блок "В фокусе": 2-3 коротких пункта, которые добавляют смысла к обложке.
- details должны быть конкретными и по теме поста: процесс, метрика, инструмент, результат или риск.
- не повторяй title/subtitle внутри details.
- не делай details рекламным CTA, длинной фразой или общими словами вроде "качество", "рост", "эффективность".
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
                title = self._clean_cover_text(str(result.get("title", "")), 44)
                subtitle = self._clean_cover_text(str(result.get("subtitle", "")), 72)
                details = self._clean_cover_details(result.get("details", []), title, subtitle)
                if not details:
                    details = self._fallback_cover_details(f"{post.get('topic', '')} {post.get('caption', '')}".lower())
                if not title:
                    raise TextGenerationError("LLM returned empty title")
                if self._is_bad_cover_title(title):
                    raise TextGenerationError(f"Bad cover title: {title}")
                return {"icon": icon, "title": title, "subtitle": subtitle, "details": details}
            except Exception as exc:
                logger.warning("Constructor cover planner failed: %s: %s", route_name, exc)
                errors.append(f"{route_name}: {exc}")

        logger.warning("All constructor planner models failed: %s", "; ".join(errors))
        return self._fallback_constructor_plan(post, available_icons)

    def _llm_routes(self) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []

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
            (("ai", "нейро", "искусствен", "автомат"), "AI-neural"),
            (("n8n", "автомат", "процесс", "интеграц"), "automatisation-n8n"),
            (("код", "backend", "разработ", "mvp", "api", "сайт"), "code-dev-work"),
            (("терминал", "сервер", "devops"), "terminal-programming-vibe"),
            (("продаж", "заяв", "лид", "ворон", "реклам", "маркет"), "marketing-work-buisness"),
            (("бизнес", "упаков", "запуск", "оффер"), "buisness-promo-ourcorp-logo"),
            (("контент", "reels", "shorts", "соцсет"), "contentmaker-sells"),
            (("youtube", "видео"), "youtube-feed-noise-tape"),
            (("дизайн", "визуал", "бренд"), "design-graphic"),
            (("ошиб", "сбой", "хаос", "проблем"), "mistakes-problems-fuckups"),
        ]
        icon = available_icons[0]
        for keywords, candidate in rules:
            if candidate in available_icons and any(keyword in text for keyword in keywords):
                icon = candidate
                break
        title, subtitle = self._fallback_cover_copy(text, str(post.get("topic", "")))
        details = self._fallback_cover_details(text)
        return {"icon": icon, "title": title, "subtitle": subtitle, "details": details}

    def _clean_cover_text(self, text: str, limit: int) -> str:
        text = re.sub(r"[#\"'`*_{}\[\]]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = self._remove_ellipsis(text)
        if len(text) > limit:
            cut = text[: limit - 1].rfind(" ")
            if cut < limit // 2:
                cut = limit - 1
            text = text[:cut]
        text = text.rstrip(".,:;!—- ")
        text = self._trim_bad_cover_tail(text)
        return text

    def _trim_bad_cover_tail(self, text: str) -> str:
        bad_tail = {
            "за",
            "для",
            "без",
            "и",
            "или",
            "в",
            "во",
            "на",
            "с",
            "со",
            "по",
            "от",
            "до",
            "к",
            "ко",
            "о",
            "об",
            "про",
            "через",
        }
        words = text.split()
        while words:
            last = words[-1].lower().strip(".,:;!—- ")
            if last in bad_tail or re.fullmatch(r"\d+", last):
                words.pop()
                continue
            break
        return " ".join(words).strip()

    def _is_bad_cover_title(self, title: str) -> bool:
        words = title.split()
        if len(words) < 2:
            return True
        return self._trim_bad_cover_tail(title) != title.strip().rstrip(".,:;!—- ")

    def _clean_cover_details(self, value: object, title: str, subtitle: str) -> list[str]:
        if isinstance(value, str):
            raw_items = re.split(r"[\n;]+", value)
        elif isinstance(value, list):
            raw_items = [str(item) for item in value]
        else:
            raw_items = []

        seen: set[str] = set()
        forbidden = {title.lower(), subtitle.lower()}
        details: list[str] = []
        for item in raw_items:
            item = self._clean_cover_text(item, 44)
            key = item.lower()
            if not item or key in seen or key in forbidden:
                continue
            if len(item.split()) < 2:
                continue
            details.append(item)
            seen.add(key)
            if len(details) >= 3:
                break
        return details

    def _fallback_cover_copy(self, text: str, topic: str) -> tuple[str, str]:
        options = [
            (("марж", "прибыл", "выруч", "чек", "юнит", "unit"), "Деньги любят систему", "Смотрим на маржу, чек и повторные продажи"),
            (("сервис", "удержан", "повторн", "лояльн"), "Сервис продает снова", "Повторные покупки дешевле вечной охоты"),
            (("оффер", "позиционирован", "упаков"), "Оффер без тумана", "Клиент должен понять ценность сразу"),
            (("команд", "найм", "роль", "ответствен"), "Команда без хаоса", "Роли и процессы важнее лишних созвонов"),
            (("контент", "креатив", "reels", "shorts", "пост"), "Креативы без рутины", "AI помогает выпускать больше без хаоса"),
            (("реклам", "трафик", "гипотез"), "Реклама без слива", "Тестируем каналы и масштабируем окупаемое"),
            (("продаж", "заяв", "лид", "crm", "ворон"), "Заявки без хаоса", "Сайт, бот и CRM работают в одной связке"),
            (("автомат", "интеграц", "n8n", "процесс"), "Автоматизация без хаоса", "Убираем ручную рутину из процессов"),
            (("сайт", "лендинг", "веб"), "Сайт ведет к заявке", "Упаковка, форма и аналитика в одной системе"),
            (("mvp", "прототип", "разработ", "backend", "api"), "MVP без лишнего кода", "Собираем основу, которую можно проверять"),
            (("дизайн", "бренд", "визуал"), "Визуал работает на смысл", "Делаем интерфейс понятным до первого клика"),
        ]
        for keywords, title, subtitle in options:
            if any(keyword in text for keyword in keywords):
                return title, subtitle

        cleaned_topic = self._clean_cover_text(topic, 44)
        if cleaned_topic and not self._is_bad_cover_title(cleaned_topic):
            return cleaned_topic, "Собираем digital в рабочую систему"
        return "Digital без хаоса", "Собираем сайт, контент и заявки в систему"

    def _fallback_cover_details(self, text: str) -> list[str]:
        options = [
            (("марж", "прибыл", "выруч", "чек", "юнит", "unit"), ["маржа", "средний чек", "повторные продажи"]),
            (("сервис", "удержан", "повторн", "лояльн"), ["скорость ответа", "доверие", "возврат клиента"]),
            (("оффер", "позиционирован", "упаков"), ["ценность", "сегмент", "первый экран"]),
            (("команд", "найм", "роль", "ответствен"), ["роли", "регламенты", "контроль задач"]),
            (("контент", "креатив", "reels", "shorts", "пост"), ["контент-план", "серии креативов", "быстрые тесты"]),
            (("реклам", "трафик", "гипотез"), ["гипотезы", "каналы", "окупаемость"]),
            (("продаж", "заяв", "лид", "crm", "ворон"), ["форма заявки", "CRM-статусы", "контроль лидов"]),
            (("автомат", "интеграц", "n8n", "процесс"), ["боты", "интеграции", "меньше ручной рутины"]),
            (("сайт", "лендинг", "веб"), ["структура", "форма заявки", "аналитика"]),
            (("mvp", "прототип", "разработ", "backend", "api"), ["прототип", "API", "быстрая проверка"]),
            (("дизайн", "бренд", "визуал"), ["смысл", "интерфейс", "первый экран"]),
        ]
        for keywords, details in options:
            if any(keyword in text for keyword in keywords):
                return details
        return ["сайт", "бот", "CRM"]

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
        contacts = b.get("contacts", {})
        telegram_url = contacts.get("telegram", "https://t.me/sl_digital")
        website_url = contacts.get("website", "")
        audience = b.get("audience", {})
        if isinstance(audience, dict):
            audience_str = "; ".join(
                f"{key}: {', '.join(value[:8]) if isinstance(value, list) else value}"
                for key, value in audience.items()
            )
        else:
            audience_str = str(audience)
        tone = b.get("tone", "")
        if isinstance(tone, dict):
            tone_str = f"{tone.get('general', '')}; {', '.join(tone.get('style', []))}"
            voice_examples = "\n".join(f"- {item}" for item in tone.get("voice_examples", [])[:8])
        else:
            tone_str = str(tone)
            voice_examples = ""
        services = b.get("services", {})
        service_directions = ", ".join(services.get("main_directions", [])[:12]) if isinstance(services, dict) else ""
        content_focus = ", ".join(b.get("content_focus", [])[:14])
        business_angles = "\n".join(f"- {item}" for item in BUSINESS_ANGLE_POOL)
        cta_examples = "\n".join(f"- {item}" for item in b.get("cta_examples", [])[:10])
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
- core idea: {b.get("core_idea", "")}
- философия: {b.get("brand_philosophy", "")}
- аудитория: {audience_str}
- направления: {service_directions}
- контент-фокус: {content_focus}
- бизнес-углы, на которые можно выходить шире digital:
{business_angles}
- тон: {tone_str}
- примеры голоса:
{voice_examples or "- Не отдельные услуги. Полная система роста."}
- нельзя: {", ".join(b["forbidden"])}
- Telegram-канал: {telegram_url}
- сайт: {website_url}

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
- Пиши как человек из команды SL Digital AI, который реально разбирает рабочую ситуацию. Не пиши как нейросеть, пресс-релиз, SEO-текст или "дайджест из главных выводов".
- Тон должен быть ярче и увереннее: чуть дерзко, бизнесово, с сильным хуком, но без дешёвого инфобизнеса и без обещаний "миллиона заявок".
- В каждом посте должна быть конкретика: сценарий, процесс, решение, критерий, ошибка, метрика, ограничение или практический вывод. Общие фразы без действия запрещены.
- Не начинай с "Мы собрали", "Внедрение IT-решений - это", "5 ключевых мыслей", "IT-решения помогают бизнесу". Это звучит скудно.
- Не используй формулировки "бизнесы часто сталкиваются", "наша команда имеет опыт", "важно правильно выбрать технологии", если дальше нет конкретного действия или примера.
- Можно использовать сильные формулы: "Хватит чинить симптомы", "Сайт без системы не продаёт", "Заявки не должны жить в хаосе", "Контент должен работать как воронка".
- Перед написанием внутренне выбери один угол поста из digital или широкого бизнеса: оффер, продажи, операционка, маркетинг, продукт, сервис, финансы, команда, аналитика, запуск, удержание, автоматизация. В JSON этот угол отдельно не выводи, но весь caption строй вокруг него.
- Не своди каждый пост к AI, ботам и CRM. Технологии должны быть инструментом, а не единственной темой.
- В тексте должен быть хотя бы один конкретный бизнес-артефакт: оффер, тариф, средний чек, маржа, LTV, CAC, скрипт продаж, регламент, KPI, форма заявки, CRM, бот, сайт, кабинет, метрика, сценарий клиента, таблица, воронка, менеджер, повторная продажа.
- Не перечисляй абстрактные преимущества. Покажи, что именно команда делает руками и зачем.
- Пиши фразами средней длины. Не делай подряд 5 коротких лозунгов и не делай длинные канцелярские предложения.
- Не используй многоточия вообще и не ставь три точки подряд. Каждый абзац должен выглядеть завершенным.
- Для premium emoji используй только эти placeholders: {", ".join(sorted(PROMPT_PLACEHOLDERS))}.
- Не используй обычные Unicode emoji вообще. Только placeholders для premium emoji. Если подходящего placeholder нет, пиши без emoji.
- Используй 3-7 placeholders, но не перегружай текст.
- Для форматирования используй только HTML-теги: <b>жирный</b>, <i>курсив</i>, <u>подчеркнутый</u>, <s>зачеркнутый</s>, <code>код</code>, <blockquote>цитата</blockquote>, <a href="{telegram_url}">текст ссылки</a>.
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
- CTA должен быть сильнее обычного: "Хочешь так же?", "Пора собрать систему?", "Хватит терять заявки?".
- В самом низу добавляй фирменную подписку отдельной строкой:
  {{eyes}} <a href="{telegram_url}">SL Digital - Подписаться</a>
- Перед строкой подписки поставь короткий CTA-абзац. Не дублируй ссылку на канал в других местах.
- Не пиши отдельное поле с текстом поста, только caption.
- image_prompt должен быть короткой темой/метафорой для обложки, а не полным техническим промптом.
- В image_prompt опиши, что именно должен символизировать главный 3D-объект.

Редакционный каркас для обычных рубрик:
1. <b>Хук</b>: конкретный тезис или рабочая ситуация.
2. Абзац контекста: что происходит в бизнесе/проекте и почему это важно.
3. Список: 3-4 практических шага, решения или наблюдения.
4. <blockquote>Короткий вывод</blockquote>
5. Финальный абзац: что получает бизнес / как SL Digital AI собирает задачу в систему.
6. CTA: ярко, коротко, без дешёвого давления.
7. Фирменная строка подписки ссылкой на канал.

Выбирай одну из композиционных формул:
- "ситуация -> как делаем -> почему так -> результат";
- "ошибка -> чем опасна -> как исправить -> что проверить";
- "гипотеза -> быстрый прототип -> тест -> решение";
- "хаос в процессе -> связка инструментов -> прозрачная воронка";
- "ручная работа -> автоматизация -> контроль -> экономия времени";
- "оффер -> трафик -> заявка -> продажа -> повторная покупка";
- "маржа -> процессы -> контроль -> рост без лишнего найма";
- "клиентский путь -> точки потерь -> решение -> метрика".

Перед финальным JSON мысленно проверь caption:
- есть ли живой хук, который хочется дочитать;
- есть ли конкретный проектный процесс, а не общие обещания;
- список стоит столбиком;
- quote звучит как вывод, а не как рекламный слоган;
- CTA звучит уверенно и не повторяет весь пост;
- текст похож на пост опытной команды SL Digital AI.

Пример уровня оформления и живости, к которому нужно стремиться:
<b>Тестируем MVP за 72 часа - как это реально?</b>

Сначала собираем гипотезы и формируем минимальный набор функций. Затем в команде делим задачи:

{{one}} дизайн-прототип за 6 часов
{{two}} backend-мокап без полной инфраструктуры
{{three}} юзабилити-тесты на реальных сценариях

<blockquote>Минимум кода - максимум обратной связи.</blockquote>

Так за 3 дня появляется не "красивая идея", а набор метрик: что подтвердилось, где пользователю непонятно и что стоит дорабатывать дальше.

Хочешь так же быстро проверить идею, а не спорить о ней месяцами? Пиши нам.

{{eyes}} <a href="{telegram_url}">SL Digital - Подписаться</a>

Верни JSON строго такой формы:
{{
  "topic": "название темы до 80 символов",
  "caption": "готовый caption для Telegram",
  "image_prompt": "тема и метафора для обложки, 1-2 предложения",
  "premium_emoji_plan": [
    {{"placeholder": "{{{{eyes}}}}", "meaning": "акцент внимания"}},
    {{"placeholder": "{{{{fire}}}}", "meaning": "сильный вывод"}}
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
            "max_tokens": 2200,
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
            reasoning = message.get("reasoning") or message.get("reasoning_details") or ""
            logger.info(
                "LLM returned empty final content. model=%s finish_reason=%s reasoning_preview=%s",
                data.get("model", model),
                finish_reason,
                str(reasoning)[:240],
            )
            raise TextGenerationError("LLM returned empty final content")

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
        return caption

    def _validate_caption_length(self, caption: str, rubric_id: str) -> None:
        min_len = MEME_CAPTION_MIN if rubric_id == "meme" else REGULAR_CAPTION_MIN
        max_len = MEME_CAPTION_MAX if rubric_id == "meme" else REGULAR_CAPTION_MAX
        if len(caption) < min_len:
            raise TextGenerationError(f"Caption too short: {len(caption)} chars, need at least {min_len}")
        if len(caption) > max_len:
            raise TextGenerationError(f"Caption too long: {len(caption)} chars, need at most {max_len}")
        if len(caption) > ABSOLUTE_CAPTION_MAX:
            raise TextGenerationError(f"Caption too long: {len(caption)} chars, absolute max {ABSOLUTE_CAPTION_MAX}")

    def _is_caption_length_error(self, exc: Exception) -> bool:
        message = str(exc)
        return message.startswith("Caption too short:") or message.startswith("Caption too long:")

    def _is_soft_llm_route_error(self, exc: Exception) -> bool:
        message = str(exc)
        return message.startswith("LLM returned empty final content")

    def _build_caption_length_repair_prompt(self, raw_json: str, rubric_id: str, reason: str) -> str:
        min_len = MEME_CAPTION_MIN if rubric_id == "meme" else REGULAR_CAPTION_MIN
        max_len = MEME_CAPTION_MAX if rubric_id == "meme" else REGULAR_CAPTION_MAX
        target = "850-900" if rubric_id != "meme" else "420-500"
        action = (
            "сожми текст, сохранив самые сильные мысли, конкретику, список, blockquote и CTA"
            if "too long" in reason
            else "расширь текст конкретикой без воды"
        )
        return f"""Предыдущий ответ почти подходит, но caption не попал в нужную длину: {reason}.

Твоя задача - доработать именно этот JSON, не начинать с нуля.

Предыдущий JSON:
{raw_json}

Верни только JSON той же формы:
{{
  "topic": "...",
  "caption": "...",
  "image_prompt": "...",
  "premium_emoji_plan": [...],
  "short_summary": "..."
}}

Правила доработки:
- caption должен быть {min_len}-{max_len} символов, абсолютный максимум {ABSOLUTE_CAPTION_MAX}.
- Целься в {target} символов.
- Главная операция: {action}.
- Сохрани тему, направление мысли, HTML-разметку и premium emoji placeholders.
- Не используй обычные Unicode emoji.
- Не используй многоточия.
- Добавь конкретики: процесс, артефакт, список или вывод из проекта.
- Не добавляй воду и общие фразы.
- Если исходник длинный, не обрезай механически: перепиши плотнее, убери повторы и оставь лучшие формулировки.
- Сохрани красивую Telegram-структуру: хук, контекст, список, blockquote, CTA, строка подписки.
"""

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
