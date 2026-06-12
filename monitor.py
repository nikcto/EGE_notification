import asyncio
import logging
import parser
import database
import notifier
import config

logger = logging.getLogger(__name__)


def _has_scores(data: dict) -> bool:
    return (
        data["status"] != "ожидается"
        or data["primary"] is not None
        or data["test"] is not None
    )


async def _save_and_notify_new_result(bot, chat_id: int, subject: str, current_data: dict):
    database.update_subject(
        chat_id,
        subject,
        current_data["date"],
        current_data["primary"],
        current_data["test"],
        current_data["status"],
        current_data["appeal"],
    )
    await notifier.send_new_result_notification(bot, chat_id, subject)


async def run_check_cycle_for_user(bot, user: dict):
    chat_id = user["chat_id"]
    surname = user["surname"]
    name = user["name"]
    patronymic = user["patronymic"]
    passport = user["passport"]
    region = user["region"]

    logger.info(f"Monitor: Starting check cycle for user {chat_id} ({surname} {name})...")

    current_results = parser.get_parsed_results(surname, name, patronymic, passport, region)
    previous_results = database.load_results(chat_id)
    is_initial_check = len(previous_results) == 0

    for subject, current_data in current_results.items():
        if subject not in previous_results:
            logger.info(f"Monitor [{chat_id}]: Found new subject '{subject}'")

            if not is_initial_check:
                if _has_scores(current_data):
                    await _save_and_notify_new_result(bot, chat_id, subject, current_data)
                else:
                    database.update_subject(
                        chat_id,
                        subject,
                        current_data["date"],
                        current_data["primary"],
                        current_data["test"],
                        current_data["status"],
                        current_data["appeal"],
                    )
                    await notifier.send_message(
                        bot,
                        chat_id,
                        f"📅 Добавлен новый экзамен в расписание:\n"
                        f"Предмет: {subject}\n"
                        f"Дата: {current_data['date']}\n"
                        f"Статус: ожидается",
                    )
            else:
                database.update_subject(
                    chat_id,
                    subject,
                    current_data["date"],
                    current_data["primary"],
                    current_data["test"],
                    current_data["status"],
                    current_data["appeal"],
                )
        else:
            prev_data = previous_results[subject]

            is_previously_unprocessed = (
                prev_data["status"] == "ожидается"
                and prev_data["primary"] is None
                and prev_data["test"] is None
            )
            is_currently_processed = _has_scores(current_data)

            if is_previously_unprocessed and is_currently_processed:
                logger.info(f"Monitor [{chat_id}]: New result published for '{subject}'")
                if not is_initial_check:
                    await _save_and_notify_new_result(bot, chat_id, subject, current_data)
                else:
                    database.update_subject(
                        chat_id,
                        subject,
                        current_data["date"],
                        current_data["primary"],
                        current_data["test"],
                        current_data["status"],
                        current_data["appeal"],
                    )
            else:
                changes = {}
                for field in ["primary", "test", "status", "appeal", "date"]:
                    if prev_data[field] != current_data[field]:
                        changes[field] = {"old": prev_data[field], "new": current_data[field]}

                if changes:
                    logger.info(f"Monitor [{chat_id}]: Changes in '{subject}': {changes}")
                    score_fields = {"primary", "test", "status", "appeal"}
                    has_score_changes = bool(score_fields & changes.keys())

                    database.update_subject(
                        chat_id,
                        subject,
                        current_data["date"],
                        current_data["primary"],
                        current_data["test"],
                        current_data["status"],
                        current_data["appeal"],
                    )

                    if not is_initial_check and has_score_changes:
                        await notifier.send_changed_result_notification(bot, chat_id, subject)

    database.save_results(chat_id, current_results)

    now_str = config.local_now_str()
    database.update_user_last_check(chat_id, now_str)

    if is_initial_check:
        logger.info(f"Monitor [{chat_id}]: Baseline check cycle completed successfully.")
        await notifier.send_message(
            bot,
            chat_id,
            "✅ Регистрация пройдена! Отправь /start для получения списка команд",
        )
    else:
        logger.info(f"Monitor [{chat_id}]: Check cycle completed successfully.")


async def run_check_cycle(bot):
    logger.info("Monitor: Running global check cycle for all users...")
    users = database.get_all_users()
    active_users = [u for u in users if u["is_monitoring"] == 1]

    logger.info(f"Monitor: Found {len(users)} total users ({len(active_users)} active).")

    for user in active_users:
        try:
            await run_check_cycle_for_user(bot, user)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Monitor: Failed to run check for user {user['chat_id']}: {e}")


async def monitoring_loop(bot):
    logger.info("Monitor: Starting global monitoring background loop...")
    while True:
        try:
            await run_check_cycle(bot)
        except Exception as e:
            logger.error(f"Monitor: Error in monitoring loop step: {e}")

        await asyncio.sleep(config.CHECK_INTERVAL)
