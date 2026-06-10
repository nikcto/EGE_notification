import logging
from aiogram import Bot

logger = logging.getLogger(__name__)

async def send_message(bot: Bot, chat_id: int or str, text: str):
    """
    Sends a general text message to a specific Telegram chat_id.
    """
    try:
        # Convert target chat_id to integer if numeric
        c_id = int(chat_id) if str(chat_id).strip().replace('-', '').isdigit() else chat_id
        await bot.send_message(chat_id=c_id, text=text)
        logger.info(f"Notifier: Message sent successfully to {c_id}")
    except Exception as e:
        logger.error(f"Notifier: Error sending Telegram message to {chat_id}: {e}")

async def send_new_result_notification(bot: Bot, chat_id: int or str, subject: str, date: str, primary, test, status: str):
    """
    Formats and sends a message when a new exam result is available.
    """
    primary_str = primary if primary is not None else "-"
    test_str = test if test is not None else "-"
    
    text = (
        "🎉 Появился новый результат!\n\n"
        f"Предмет: {subject}\n"
        f"Первичный балл: {primary_str}\n"
        f"Тестовый балл: {test_str}\n"
        f"Статус: {status}"
    )
    await send_message(bot, chat_id, text)

async def send_changed_result_notification(bot: Bot, chat_id: int or str, subject: str, changes: dict):
    """
    Formats and sends a message when some details of a result change.
    """
    field_labels = {
        "primary": "Первичный балл",
        "test": "Тестовый балл",
        "status": "Статус",
        "appeal": "Апелляция",
        "date": "Дата"
    }
    
    parts = [
        "📈 Изменение результата!",
        f"Предмет: {subject}\n"
    ]
    
    for key, change in changes.items():
        label = field_labels.get(key, key)
        old_val = change["old"] if change["old"] is not None else "-"
        new_val = change["new"] if change["new"] is not None else "-"
        
        parts.append(
            f"{label}:\n"
            f"Было: {old_val}\n"
            f"Стало: {new_val}\n"
        )
        
    text = "\n".join(parts).strip()
    await send_message(bot, chat_id, text)
