import base64
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

SHOW_RESULT_PREFIX = "show:"


def encode_subject_callback(subject: str) -> str:
    encoded = base64.urlsafe_b64encode(subject.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{SHOW_RESULT_PREFIX}{encoded}"


def decode_subject_callback(data: str) -> str | None:
    if not data.startswith(SHOW_RESULT_PREFIX):
        return None
    encoded = data[len(SHOW_RESULT_PREFIX):]
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")


def format_subject_result_text(
    subject: str,
    date: str,
    primary,
    test,
    status: str,
    appeal: str,
) -> str:
    primary_str = primary if primary is not None else "-"
    test_str = test if test is not None else "-"
    appeal_str = appeal if appeal else "отсутствует"

    return (
        f"📊 <b>{subject}</b>\n\n"
        f"📅 Дата экзамена: {date}\n"
        f"🔢 Первичный балл: {primary_str}\n"
        f"🎓 Тестовый балл: {test_str}\n"
        f"⚙️ Статус: {status}\n"
        f"⚖️ Апелляция: {appeal_str}"
    )


def _show_result_keyboard(subject: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Показать результаты",
                    callback_data=encode_subject_callback(subject),
                )
            ]
        ]
    )


async def send_message(bot: Bot, chat_id: int | str, text: str, reply_markup=None, parse_mode: str | None = None):
    try:
        c_id = int(chat_id) if str(chat_id).strip().replace("-", "").isdigit() else chat_id
        await bot.send_message(
            chat_id=c_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        logger.info(f"Notifier: Message sent successfully to {c_id}")
    except Exception as e:
        logger.error(f"Notifier: Error sending Telegram message to {chat_id}: {e}")


async def send_new_result_notification(bot: Bot, chat_id: int | str, subject: str):
    text = (
        f"🎉 Пришли баллы по предмету: <b>{subject}</b>!\n\n"
        "Нажми кнопку ниже, когда будешь готов посмотреть."
    )
    await send_message(
        bot,
        chat_id,
        text,
        reply_markup=_show_result_keyboard(subject),
        parse_mode="HTML",
    )


async def send_changed_result_notification(bot: Bot, chat_id: int | str, subject: str):
    text = (
        f"📈 Обновились данные по предмету: <b>{subject}</b>.\n\n"
        "Нажми кнопку ниже, когда будешь готов посмотреть."
    )
    await send_message(
        bot,
        chat_id,
        text,
        reply_markup=_show_result_keyboard(subject),
        parse_mode="HTML",
    )
