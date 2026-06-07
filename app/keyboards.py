from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_approval_keyboard(post_id: str, has_image: bool = True) -> InlineKeyboardMarkup:
    image_button_text = "🧩 Изменить картинку" if has_image else "🧩 Добавить картинку"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{post_id}"),
            ],
            [
                InlineKeyboardButton(text=image_button_text, callback_data=f"image:{post_id}"),
                InlineKeyboardButton(text="🧩 Собрать картинку", callback_data=f"construct:{post_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{post_id}"),
            ],
        ]
    )
