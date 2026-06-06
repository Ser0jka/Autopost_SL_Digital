from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_approval_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{post_id}"),
            ]
        ]
    )
