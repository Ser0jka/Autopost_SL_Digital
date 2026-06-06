import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_config
from app.keyboards import get_approval_keyboard
from models.post import Post
from services.image_generator import ImageGenerationError, ImageGenerator
from services.telethon_publisher import publish_photo_post, render_plain_caption
from services.text_generator import TextGenerator
from services.vk_publisher import VKPublishError, publish_vk_photo_post, vk_is_configured
from storage.excel_storage import ExcelStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now()


def _post_id() -> str:
    return uuid4().hex[:12]


def _parse_daily_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.strip().split(":", 1)
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        logger.warning("Invalid DAILY_POST_TIME=%r, using 10:00", value)
        return 10, 0


async def main() -> None:
    config = get_config()

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env")
        sys.exit(1)

    storage = ExcelStorage()
    text_generator = TextGenerator(config)
    image_generator = ImageGenerator(config)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

    rubrics = text_generator.rubrics

    def is_admin(message_or_callback) -> bool:
        user = message_or_callback.from_user
        return bool(user and user.id in config.admin_ids_list)

    def today_rubric_id() -> str:
        schedule = text_generator.rubric_schedule
        weekday = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%A").lower()
        return schedule.get(weekday, "guide")

    async def send_preview(admin_chat_id: int, post: Post) -> None:
        await bot.send_photo(
            chat_id=admin_chat_id,
            photo=FSInputFile(post.image_path),
            caption=render_plain_caption(post.caption),
            reply_markup=get_approval_keyboard(post.id),
            parse_mode=None,
        )

    async def generate_post_for_review(rubric_id: str, admin_chat_id: int) -> None:
        rubric = rubrics.get(rubric_id)
        if not rubric:
            await bot.send_message(admin_chat_id, f"Неизвестная рубрика: {rubric_id}")
            return

        post_id = _post_id()
        now = _now()
        recent_posts = [p.__dict__ for p in storage.list_recent_posts(limit=20)]

        try:
            generated = await text_generator.generate_post_text(rubric_id, recent_posts)
        except Exception as exc:
            logger.exception("Text generation failed")
            storage.add_post(
                Post(
                    id=post_id,
                    created_at=now,
                    updated_at=now,
                    rubric_id=rubric_id,
                    topic="",
                    caption="",
                    image_prompt="",
                    status="generation_failed",
                    error_message=str(exc),
                )
            )
            await bot.send_message(admin_chat_id, f"⚠️ Не удалось сгенерировать пост: {exc}")
            return

        try:
            image = await image_generator.generate_image(generated["image_prompt"], post_id)
        except ImageGenerationError as exc:
            logger.exception("Image generation failed")
            storage.add_post(
                Post(
                    id=post_id,
                    created_at=now,
                    updated_at=now,
                    rubric_id=rubric_id,
                    topic=generated["topic"],
                    caption=generated["caption"],
                    image_prompt=generated["image_prompt"],
                    status="image_failed",
                    error_message=str(exc),
                )
            )
            await bot.send_message(
                admin_chat_id,
                "⚠️ Картинку не удалось сгенерировать.\n"
                "Я попробовал все подключенные API: Hugging Face, Stability AI, ModelsLab и Fal.ai.\n"
                "Подробности записал в Excel и bot.log.",
            )
            return

        post = Post(
            id=post_id,
            created_at=now,
            updated_at=now,
            rubric_id=rubric_id,
            topic=generated["topic"],
            caption=generated["caption"],
            image_prompt=generated["image_prompt"],
            image_path=image.path,
            image_provider=image.provider,
            status="review",
        )
        storage.add_post(post)
        await send_preview(admin_chat_id, post)

    async def run_daily_generation() -> None:
        rubric_id = today_rubric_id()
        rubric_name = rubrics.get(rubric_id, {}).get("name", rubric_id)
        for admin_id in config.admin_ids_list:
            await bot.send_message(admin_id, f"Генерирую ежедневный пост по рубрике: {rubric_name}...")
            await generate_post_for_review(rubric_id, admin_id)

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Бот запущен.\n"
            "/post <rubric> - сгенерировать пост\n"
            "/today - сгенерировать пост по рубрике дня\n"
            "/rubrics - список рубрик\n"
            "/download - скачать Excel\n"
            "/help - помощь"
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Основной сценарий: /post guide, затем проверь preview и нажми "
            "✅ Опубликовать или ❌ Отклонить.\n\n"
            "Публикация в канал идет одним сообщением: фото + caption."
        )

    @dp.message(Command("rubrics"))
    async def cmd_rubrics(message: Message) -> None:
        if not is_admin(message):
            return
        lines = ["Доступные рубрики:"]
        for rubric_id, rubric in rubrics.items():
            lines.append(f"{rubric_id} - {rubric.get('name', rubric_id)}")
        await message.answer("\n".join(lines))

    @dp.message(Command("download"))
    async def cmd_download(message: Message) -> None:
        if not is_admin(message):
            return
        path = storage.export_path()
        if path.exists():
            await message.answer_document(FSInputFile(path), caption="Excel с постами")
        else:
            await message.answer("Файл с постами пока пуст.")

    @dp.message(Command("post"))
    async def cmd_post(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            return
        rubric_id = (command.args or "").strip()
        if not rubric_id:
            await message.answer("Укажи рубрику: /post guide")
            return
        rubric = rubrics.get(rubric_id)
        if not rubric:
            await message.answer(f"Неизвестная рубрика: {rubric_id}. Смотри /rubrics")
            return
        await message.answer(f"Генерирую пост по рубрике: {rubric.get('name', rubric_id)}...")
        await generate_post_for_review(rubric_id, message.chat.id)

    @dp.message(Command("today"))
    async def cmd_today(message: Message) -> None:
        if not is_admin(message):
            return
        rubric_id = today_rubric_id()
        rubric = rubrics.get(rubric_id, {})
        await message.answer(f"Генерирую пост по рубрике дня: {rubric.get('name', rubric_id)}...")
        await generate_post_for_review(rubric_id, message.chat.id)

    @dp.callback_query(F.data.startswith("approve:"))
    async def cb_approve(callback: CallbackQuery) -> None:
        if not is_admin(callback):
            await callback.answer("Нет доступа", show_alert=True)
            return
        post_id = callback.data.split(":", 1)[1]
        post = storage.get_post(post_id)
        if not post:
            await callback.answer("Пост не найден", show_alert=True)
            return
        if post.status == "published":
            await callback.answer("Пост уже опубликован", show_alert=True)
            return
        if not post.image_path or not Path(post.image_path).exists():
            storage.update_post(post_id, {"status": "image_failed", "error_message": "Image file not found"})
            await callback.answer("Файл картинки не найден", show_alert=True)
            return
        if not config.TARGET_CHANNEL:
            await callback.answer("TARGET_CHANNEL не задан", show_alert=True)
            return

        try:
            message_id = await publish_photo_post(
                channel=config.TARGET_CHANNEL,
                image_path=post.image_path,
                caption=post.caption,
            )
        except Exception as exc:
            logger.exception("Publishing failed for post %s", post_id)
            storage.update_post(post_id, {"error_message": str(exc)})
            await callback.answer("Не удалось опубликовать", show_alert=True)
            return

        vk_status_message = ""
        vk_error_message = ""
        if vk_is_configured():
            try:
                vk_post_id = await publish_vk_photo_post(
                    image_path=post.image_path,
                    caption=render_plain_caption(post.caption),
                )
                vk_status_message = f"\n✅ VK: опубликовано, post_id={vk_post_id}"
            except VKPublishError as exc:
                logger.exception("VK publishing failed for post %s", post_id)
                vk_error_message = f"VK publish failed: {exc}"
                vk_status_message = f"\n⚠️ VK: не удалось опубликовать ({exc})"
            except Exception as exc:
                logger.exception("Unexpected VK publishing error for post %s", post_id)
                vk_error_message = f"Unexpected VK publish error: {exc}"
                vk_status_message = "\n⚠️ VK: не удалось опубликовать, подробности в bot.log"
        else:
            vk_status_message = "\nℹ️ VK: пропущено, не заполнены VK_USER_ACCESS_TOKEN/VK_ACCESS_TOKEN и VK_GROUP_ID"

        storage.update_post(
            post_id,
            {
                "status": "published",
                "approved_by": callback.from_user.id,
                "published_at": _now(),
                "telegram_message_id": message_id,
                "error_message": vk_error_message,
            },
        )
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ Telegram: пост опубликован{vk_status_message}")
        await callback.answer("Пост опубликован")

    @dp.callback_query(F.data.startswith("reject:"))
    async def cb_reject(callback: CallbackQuery) -> None:
        if not is_admin(callback):
            await callback.answer("Нет доступа", show_alert=True)
            return
        post_id = callback.data.split(":", 1)[1]
        if not storage.update_post(post_id, {"status": "rejected"}):
            await callback.answer("Пост не найден", show_alert=True)
            return
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("❌ Пост отклонён")
        await callback.answer("Пост отклонён")

    hour, minute = _parse_daily_time(config.DAILY_POST_TIME)
    scheduler.add_job(run_daily_generation, "cron", hour=hour, minute=minute)
    scheduler.start()
    logger.info("Bot started. Admins: %s. Channel: %s", config.admin_ids_list, config.TARGET_CHANNEL)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
