import asyncio
import datetime
import logging
import parser
import database
import notifier
import config

logger = logging.getLogger(__name__)

async def run_check_cycle_for_user(bot, user: dict):
    """
    Runs a check cycle for a single user, comparing grades, 
    updating database records, and sending notifications.
    """
    chat_id = user["chat_id"]
    surname = user["surname"]
    name = user["name"]
    patronymic = user["patronymic"]
    passport = user["passport"]
    region = user["region"]
    
    logger.info(f"Monitor: Starting check cycle for user {chat_id} ({surname} {name})...")
    
    # 1. Fetch current results from the website
    current_results = parser.get_parsed_results(surname, name, patronymic, passport, region)
    
    # 2. Load previous results from SQLite
    previous_results = database.load_results(chat_id)
    
    # Detect if this is the first execution for this user (baseline loading)
    is_initial_check = len(previous_results) == 0
    
    # 3. Compare current results with database results
    for subject, current_data in current_results.items():
        if subject not in previous_results:
            # New subject
            logger.info(f"Monitor [{chat_id}]: Found new subject '{subject}'")
            
            is_processed = (
                current_data["status"] != "ожидается" 
                or current_data["primary"] is not None 
                or current_data["test"] is not None
            )
            
            # Send notifications only if it is not the baseline check
            if not is_initial_check:
                if is_processed:
                    await notifier.send_new_result_notification(
                        bot, chat_id, subject, current_data["date"],
                        current_data["primary"], current_data["test"],
                        current_data["status"]
                    )
                else:
                    await notifier.send_message(
                        bot, chat_id,
                        f"📅 Добавлен новый экзамен в расписание:\n"
                        f"Предмет: {subject}\n"
                        f"Дата: {current_data['date']}\n"
                        f"Статус: ожидается"
                    )
            
            # Save to database
            database.update_subject(
                chat_id, subject, current_data["date"],
                current_data["primary"], current_data["test"],
                current_data["status"], current_data["appeal"]
            )
        else:
            # Subject already exists
            prev_data = previous_results[subject]
            
            is_previously_unprocessed = (
                prev_data["status"] == "ожидается" 
                and prev_data["primary"] is None 
                and prev_data["test"] is None
            )
            
            is_currently_processed = (
                current_data["status"] != "ожидается" 
                or current_data["primary"] is not None 
                or current_data["test"] is not None
            )
            
            if is_previously_unprocessed and is_currently_processed:
                logger.info(f"Monitor [{chat_id}]: New result published for '{subject}'")
                if not is_initial_check:
                    await notifier.send_new_result_notification(
                        bot, chat_id, subject, current_data["date"],
                        current_data["primary"], current_data["test"],
                        current_data["status"]
                    )
                database.update_subject(
                    chat_id, subject, current_data["date"],
                    current_data["primary"], current_data["test"],
                    current_data["status"], current_data["appeal"]
                )
            else:
                # Check for updates
                changes = {}
                for field in ["primary", "test", "status", "appeal", "date"]:
                    if prev_data[field] != current_data[field]:
                        changes[field] = {"old": prev_data[field], "new": current_data[field]}
                
                if changes:
                    logger.info(f"Monitor [{chat_id}]: Changes in '{subject}': {changes}")
                    if not is_initial_check:
                        await notifier.send_changed_result_notification(bot, chat_id, subject, changes)
                    database.update_subject(
                        chat_id, subject, current_data["date"],
                        current_data["primary"], current_data["test"],
                        current_data["status"], current_data["appeal"]
                    )
                    
    # Sync and update records
    database.save_results(chat_id, current_results)
    
    # Save last check timestamp
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    database.update_user_last_check(chat_id, now_str)
    
    if is_initial_check:
        logger.info(f"Monitor [{chat_id}]: Baseline check cycle completed successfully.")
        await notifier.send_message(
            bot, chat_id,
            "✅Регистрация пройдена! Отправь /start для получения списка команд"
        )
    else:
        logger.info(f"Monitor [{chat_id}]: Check cycle completed successfully.")

async def run_check_cycle(bot):
    """
    Scans all users in the database and runs checks for active ones.
    """
    logger.info("Monitor: Running global check cycle for all users...")
    users = database.get_all_users()
    active_users = [u for u in users if u["is_monitoring"] == 1]
    
    logger.info(f"Monitor: Found {len(users)} total users ({len(active_users)} active).")
    
    for user in active_users:
        try:
            await run_check_cycle_for_user(bot, user)
            # Avoid hammering the server too quickly
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Monitor: Failed to run check for user {user['chat_id']}: {e}")

async def monitoring_loop(bot):
    """
    Background loop that wakes up every CHECK_INTERVAL to monitor results for all users.
    """
    logger.info("Monitor: Starting global monitoring background loop...")
    while True:
        try:
            await run_check_cycle(bot)
        except Exception as e:
            logger.error(f"Monitor: Error in monitoring loop step: {e}")
            
        await asyncio.sleep(config.CHECK_INTERVAL)
