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
from services.image_constructor import ConstructorPlan, build_constructor_image, list_constructor_icons
from services.image_generator import ImageGenerationError, ImageGenerator
from services.telethon_publisher import (
    publish_photo_post,
    publish_text_post,
    render_plain_caption,
    render_preview_caption,
)
from services.text_generator import TextGenerator
from services.vk_publisher import VKPublishError, publish_vk_photo_post, publish_vk_text_post, vk_is_configured
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

BASE_DIR = Path(__file__).resolve().parent
IMAGE_DIR = BASE_DIR / "data" / "images"


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
    pending_edits: dict[int, str] = {}
    pending_image_edits: dict[int, str] = {}

    def admin_ids() -> list[int]:
        return config.admin_ids_list

    def is_admin(message_or_callback) -> bool:
        user = message_or_callback.from_user
        return bool(user and user.id in admin_ids())

    def today_rubric_id() -> str:
        schedule = text_generator.rubric_schedule
        weekday = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%A").lower()
        return schedule.get(weekday, "guide")

    async def notify_admins(text: str, exclude_user_id: int | None = None) -> None:
        for admin_id in admin_ids():
            if exclude_user_id and admin_id == exclude_user_id:
                continue
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                logger.exception("Failed to notify admin %s", admin_id)

    async def send_preview(admin_chat_id: int, post: Post) -> None:
        has_image = bool(post.image_path and Path(post.image_path).exists())
        preview_caption = render_preview_caption(post.caption)
        if has_image:
            try:
                await bot.send_photo(
                    chat_id=admin_chat_id,
                    photo=FSInputFile(post.image_path),
                    caption=preview_caption,
                    reply_markup=get_approval_keyboard(post.id, has_image=True),
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Failed to send formatted preview for post %s", post.id)
                await bot.send_photo(
                    chat_id=admin_chat_id,
                    photo=FSInputFile(post.image_path),
                    caption=render_plain_caption(post.caption),
                    reply_markup=get_approval_keyboard(post.id, has_image=True),
                    parse_mode=None,
                )
            return

        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=preview_caption,
                reply_markup=get_approval_keyboard(post.id, has_image=False),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send formatted preview for post %s", post.id)
            await bot.send_message(
                chat_id=admin_chat_id,
                text=render_plain_caption(post.caption),
                reply_markup=get_approval_keyboard(post.id, has_image=False),
                parse_mode=None,
            )

    async def send_preview_to_admins(post: Post) -> None:
        for admin_id in admin_ids():
            try:
                await send_preview(admin_id, post)
            except Exception:
                logger.exception("Failed to send preview to admin %s", admin_id)

    async def generate_post_for_review(
        rubric_id: str,
        requested_by_chat_id: int,
        custom_topic: str = "",
        announce_to_all: bool = True,
    ) -> Post | None:
        rubric = rubrics.get(rubric_id)
        if not rubric:
            await bot.send_message(requested_by_chat_id, f"Неизвестная рубрика: {rubric_id}")
            return None

        post_id = _post_id()
        now = _now()
        recent_posts = [p.__dict__ for p in storage.list_recent_posts(limit=20)]

        try:
            generated = await text_generator.generate_post_text(rubric_id, recent_posts, custom_topic=custom_topic)
        except Exception as exc:
            logger.exception("Text generation failed")
            storage.add_post(
                Post(
                    id=post_id,
                    created_at=now,
                    updated_at=now,
                    rubric_id=rubric_id,
                    topic=custom_topic or "",
                    caption="",
                    image_prompt="",
                    status="generation_failed",
                    error_message=str(exc),
                )
            )
            await bot.send_message(requested_by_chat_id, f"⚠️ Не удалось сгенерировать пост: {exc}")
            return None

        try:
            image = await image_generator.generate_image(generated["image_prompt"], post_id)
        except ImageGenerationError as exc:
            logger.exception("Image generation failed")
            post = Post(
                id=post_id,
                created_at=now,
                updated_at=now,
                rubric_id=rubric_id,
                topic=generated["topic"],
                caption=generated["caption"],
                image_prompt=generated["image_prompt"],
                image_path="",
                image_provider="",
                status="review",
                error_message=f"Image generation failed: {exc}",
            )
            storage.add_post(post)
            await bot.send_message(
                requested_by_chat_id,
                "⚠️ Картинку не удалось сгенерировать.\n"
                "Текст готов: можно опубликовать без фотографии или нажать «Добавить картинку» в preview.",
            )
            if announce_to_all:
                await send_preview_to_admins(post)
            else:
                await send_preview(requested_by_chat_id, post)
            return post

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

        if announce_to_all:
            await send_preview_to_admins(post)
        else:
            await send_preview(requested_by_chat_id, post)
        return post

    async def revise_post_for_review(post_id: str, admin_chat_id: int, revision_request: str) -> None:
        post = storage.get_post(post_id)
        if not post:
            await bot.send_message(admin_chat_id, "Пост не найден.")
            return
        if post.status == "published":
            await bot.send_message(admin_chat_id, "Этот пост уже опубликован, его нельзя изменить.")
            return
        if post.status == "rejected":
            await bot.send_message(admin_chat_id, "Этот пост уже отклонен, его нельзя изменить.")
            return

        await bot.send_message(admin_chat_id, "Дорабатываю пост по твоему запросу...")
        old_post = post.__dict__

        try:
            generated = await text_generator.revise_post_text(post.rubric_id, old_post, revision_request)
        except Exception as exc:
            logger.exception("Text revision failed")
            storage.update_post(post_id, {"error_message": str(exc)})
            await bot.send_message(admin_chat_id, f"⚠️ Не удалось доработать текст: {exc}")
            return

        try:
            image = await image_generator.generate_image(generated["image_prompt"], post_id)
        except ImageGenerationError as exc:
            logger.exception("Revision image generation failed")
            storage.update_post(
                post_id,
                {
                    "topic": generated["topic"],
                    "caption": generated["caption"],
                    "image_prompt": generated["image_prompt"],
                    "image_path": "",
                    "image_provider": "",
                    "status": "review",
                    "error_message": f"Revision image generation failed: {exc}",
                },
            )
            await bot.send_message(
                admin_chat_id,
                "⚠️ Текст доработал, но новую картинку сгенерировать не удалось. Отправляю preview без фотографии.",
            )
            updated_post = storage.get_post(post_id)
            if updated_post:
                await notify_admins(f"✏️ Пост {post_id} доработан без картинки. Новый preview ниже.")
                await send_preview_to_admins(updated_post)
            return

        storage.update_post(
            post_id,
            {
                "topic": generated["topic"],
                "caption": generated["caption"],
                "image_prompt": generated["image_prompt"],
                "image_path": image.path,
                "image_provider": image.provider,
                "status": "review",
                "error_message": "",
            },
        )
        updated_post = storage.get_post(post_id)
        if updated_post:
            await notify_admins(f"✏️ Пост {post_id} доработан. Новый preview ниже.")
            await send_preview_to_admins(updated_post)

    async def generate_image_for_existing_post(post_id: str, admin_chat_id: int, image_request: str) -> None:
        post = storage.get_post(post_id)
        if not post:
            await bot.send_message(admin_chat_id, "Пост не найден.")
            return
        if post.status == "published":
            await bot.send_message(admin_chat_id, "Этот пост уже опубликован, картинку менять нельзя.")
            return
        if post.status == "rejected":
            await bot.send_message(admin_chat_id, "Этот пост уже отклонен, картинку менять нельзя.")
            return

        request = image_request.strip()
        if request.lower() in {"оставь", "оставить", "как есть", "-"}:
            image_prompt = post.image_prompt
        else:
            image_prompt = text_generator._build_image_prompt(request)

        await bot.send_message(admin_chat_id, "Генерирую картинку для поста...")
        try:
            image = await image_generator.generate_image(image_prompt, post_id)
        except ImageGenerationError as exc:
            logger.exception("Manual image generation failed")
            storage.update_post(post_id, {"error_message": f"Manual image generation failed: {exc}"})
            await bot.send_message(
                admin_chat_id,
                "⚠️ Картинку снова не удалось сгенерировать. Пост можно опубликовать без фотографии.",
            )
            return

        storage.update_post(
            post_id,
            {
                "image_prompt": image_prompt,
                "image_path": image.path,
                "image_provider": image.provider,
                "status": "review",
                "error_message": "",
            },
        )
        updated_post = storage.get_post(post_id)
        if updated_post:
            await notify_admins(f"🖼 Картинка для поста {post_id} обновлена. Новый preview ниже.")
            await send_preview_to_admins(updated_post)

    async def save_uploaded_image_for_post(post_id: str, message: Message) -> None:
        post = storage.get_post(post_id)
        if not post:
            await message.answer("Пост не найден.")
            return
        if post.status == "published":
            await message.answer("Этот пост уже опубликован, картинку менять нельзя.")
            return
        if post.status == "rejected":
            await message.answer("Этот пост уже отклонен, картинку менять нельзя.")
            return

        file_id = ""
        extension = ".jpg"
        if message.photo:
            file_id = message.photo[-1].file_id
            extension = ".jpg"
        elif message.document and (message.document.mime_type or "").startswith("image/"):
            file_id = message.document.file_id
            suffix = Path(message.document.file_name or "").suffix.lower()
            extension = suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        else:
            await message.answer("Пришли картинку как фото или как файл-изображение.")
            pending_image_edits[message.from_user.id] = post_id
            return

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        image_path = IMAGE_DIR / f"{post_id}{extension}"
        await bot.download(file_id, destination=image_path)

        storage.update_post(
            post_id,
            {
                "image_path": str(image_path),
                "image_provider": "admin_upload",
                "status": "review",
                "error_message": "",
            },
        )
        updated_post = storage.get_post(post_id)
        if updated_post:
            await notify_admins(f"🖼 Админ загрузил картинку для поста {post_id}. Новый preview ниже.")
            await send_preview_to_admins(updated_post)

    async def construct_image_for_post(post_id: str, admin_chat_id: int, request: str = "") -> None:
        post = storage.get_post(post_id)
        if not post:
            await bot.send_message(admin_chat_id, "Пост не найден.")
            return
        if post.status == "published":
            await bot.send_message(admin_chat_id, "Этот пост уже опубликован, картинку менять нельзя.")
            return
        if post.status == "rejected":
            await bot.send_message(admin_chat_id, "Этот пост уже отклонен, картинку менять нельзя.")
            return

        icons = list_constructor_icons()
        if not icons:
            await bot.send_message(admin_chat_id, "В data/icons нет PNG-иконок для конструктора.")
            return

        await bot.send_message(
            admin_chat_id,
            "Собираю картинку-конструктор: выбираю иконку, заголовок и подзаголовок...",
        )
        plan_data = await text_generator.plan_constructor_cover(post.__dict__, icons, request=request)
        plan = ConstructorPlan(
            icon=plan_data["icon"],
            title=plan_data["title"],
            subtitle=plan_data.get("subtitle", ""),
        )
        image_path = build_constructor_image(post_id, plan)

        storage.update_post(
            post_id,
            {
                "image_path": image_path,
                "image_provider": f"constructor:{plan.icon}",
                "status": "review",
                "error_message": "",
            },
        )
        updated_post = storage.get_post(post_id)
        if updated_post:
            await notify_admins(
                f"🧩 Собрана картинка-конструктор для поста {post_id}: {plan.icon}. Новый preview ниже."
            )
            await send_preview_to_admins(updated_post)

    async def run_daily_generation() -> None:
        if not admin_ids():
            logger.warning("Daily generation skipped: ADMIN_IDS is empty")
            return
        rubric_id = today_rubric_id()
        rubric_name = rubrics.get(rubric_id, {}).get("name", rubric_id)
        await notify_admins(f"Генерирую ежедневный пост в 10:00 по рубрике дня: {rubric_name}...")
        await generate_post_for_review(rubric_id, admin_ids()[0], announce_to_all=True)

    def parse_post_args(args: str) -> tuple[str, str]:
        args = (args or "").strip()
        if not args:
            return today_rubric_id(), ""

        first, *rest = args.split(maxsplit=1)
        if first in rubrics:
            return first, rest[0].strip() if rest else ""
        return today_rubric_id(), args

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Бот запущен.\n"
            "/post <rubric> - сгенерировать пост по рубрике\n"
            "/post <тема> - сгенерировать пост по теме в рубрике дня\n"
            "/post guide <тема> - сгенерировать пост по теме в конкретной рубрике\n"
            "/today - сгенерировать пост по рубрике дня\n"
            "/rubrics - список рубрик\n"
            "/download - скачать Excel\n"
            "\nМожно просто написать тему сообщением, и я соберу пост с картинкой."
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not is_admin(message):
            return
        await message.answer(
            "Механика:\n"
            "1. Напиши /post guide или просто тему поста.\n"
            "2. Все админы получат общий preview.\n"
            "3. Любой админ может нажать ✅ Опубликовать, ✏️ Изменить или ❌ Отклонить.\n"
            "4. После ✏️ Изменить напиши, что поправить: тон, структуру, CTA, картинку, тему."
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
        rubric_id, custom_topic = parse_post_args(command.args or "")
        rubric = rubrics.get(rubric_id, {})
        label = custom_topic or rubric.get("name", rubric_id)
        await message.answer(f"Генерирую пост: {label}...")
        await generate_post_for_review(rubric_id, message.chat.id, custom_topic=custom_topic)

    @dp.message(Command("today"))
    async def cmd_today(message: Message) -> None:
        if not is_admin(message):
            return
        rubric_id = today_rubric_id()
        rubric = rubrics.get(rubric_id, {})
        await message.answer(f"Генерирую пост по рубрике дня: {rubric.get('name', rubric_id)}...")
        await generate_post_for_review(rubric_id, message.chat.id)

    @dp.callback_query(F.data.startswith("edit:"))
    async def cb_edit(callback: CallbackQuery) -> None:
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

        pending_edits[callback.from_user.id] = post_id
        await callback.answer("Жду правки")
        if callback.message:
            await callback.message.answer(
                f"✏️ Напиши одним сообщением, что изменить в посте {post_id}.\n"
                "Например: сделай короче, добавь больше экспертности, замени картинку на метафору CRM."
            )

    @dp.callback_query(F.data.startswith("image:"))
    async def cb_image(callback: CallbackQuery) -> None:
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

        pending_image_edits[callback.from_user.id] = post_id
        pending_edits.pop(callback.from_user.id, None)
        await callback.answer("Жду описание картинки")
        if callback.message:
            current = "изменить" if post.image_path else "добавить"
            await callback.message.answer(
                f"🖼 Напиши, какую картинку {current} для поста {post_id}.\n"
                "Например: 3D-воронка продаж с чат-ботом и CRM.\n"
                "Или пришли свою картинку с устройства как фото/файл.\n"
                "Можно написать «оставь», чтобы попробовать текущий image_prompt еще раз."
            )

    @dp.callback_query(F.data.startswith("construct:"))
    async def cb_construct(callback: CallbackQuery) -> None:
        if not is_admin(callback):
            await callback.answer("Нет доступа", show_alert=True)
            return
        post_id = callback.data.split(":", 1)[1]
        await callback.answer("Собираю")
        if callback.message:
            await callback.message.answer("🧩 Собираю картинку-конструктор по тексту поста...")
        await construct_image_for_post(post_id, callback.message.chat.id if callback.message else callback.from_user.id)

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
        if post.status == "rejected":
            await callback.answer("Пост уже отклонен", show_alert=True)
            return
        if not config.TARGET_CHANNEL:
            await callback.answer("TARGET_CHANNEL не задан", show_alert=True)
            return

        has_image = bool(post.image_path and Path(post.image_path).exists())
        try:
            if has_image:
                message_id = await publish_photo_post(
                    channel=config.TARGET_CHANNEL,
                    image_path=post.image_path,
                    caption=post.caption,
                )
            else:
                message_id = await publish_text_post(channel=config.TARGET_CHANNEL, text=post.caption)
        except Exception as exc:
            logger.exception("Telegram publishing failed for post %s", post_id)
            storage.update_post(post_id, {"error_message": str(exc)})
            await callback.answer("Не удалось опубликовать", show_alert=True)
            return

        vk_status_message = ""
        vk_error_message = ""
        if vk_is_configured():
            try:
                if has_image:
                    vk_post_id = await publish_vk_photo_post(
                        image_path=post.image_path,
                        caption=render_plain_caption(post.caption),
                    )
                else:
                    vk_post_id = await publish_vk_text_post(caption=render_plain_caption(post.caption))
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
        pending_edits.clear()
        pending_image_edits.clear()
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ Telegram: пост опубликован{vk_status_message}")

        approver = callback.from_user.full_name or str(callback.from_user.id)
        await notify_admins(
            f"✅ Пост {post_id} опубликован админом {approver}.{vk_status_message}",
            exclude_user_id=callback.from_user.id,
        )
        await callback.answer("Пост опубликован")

    @dp.callback_query(F.data.startswith("reject:"))
    async def cb_reject(callback: CallbackQuery) -> None:
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
        if not storage.update_post(post_id, {"status": "rejected"}):
            await callback.answer("Пост не найден", show_alert=True)
            return
        pending_edits.clear()
        pending_image_edits.clear()
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("❌ Пост отклонен")
        await notify_admins(f"❌ Пост {post_id} отклонен.", exclude_user_id=callback.from_user.id)
        await callback.answer("Пост отклонен")

    @dp.message(F.photo | F.document)
    async def msg_image(message: Message) -> None:
        if not is_admin(message):
            return
        post_id = pending_image_edits.pop(message.from_user.id, "")
        if not post_id:
            await message.answer("Сначала нажми «Добавить картинку» или «Изменить картинку» у нужного поста.")
            return
        await save_uploaded_image_for_post(post_id, message)

    @dp.message(F.text)
    async def msg_text(message: Message) -> None:
        if not is_admin(message):
            return
        text = (message.text or "").strip()
        if not text:
            return

        post_id = pending_image_edits.pop(message.from_user.id, "")
        if post_id:
            await generate_image_for_existing_post(post_id, message.chat.id, text)
            return

        post_id = pending_edits.pop(message.from_user.id, "")
        if post_id:
            await revise_post_for_review(post_id, message.chat.id, text)
            return

        rubric_id = today_rubric_id()
        await message.answer(f"Генерирую пост по теме: {text}...")
        await generate_post_for_review(rubric_id, message.chat.id, custom_topic=text)

    hour, minute = _parse_daily_time(config.DAILY_POST_TIME)
    scheduler.add_job(run_daily_generation, "cron", hour=hour, minute=minute, id="daily_post", replace_existing=True)
    scheduler.start()
    logger.info("Bot started. Admins: %s. Channel: %s", admin_ids(), config.TARGET_CHANNEL)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
