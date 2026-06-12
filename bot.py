import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import config
import database
import monitor
import notifier
import parser

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger("bot")

REGISTERED_USER_COMMANDS = (
    "📊 /status — проверить текущие баллы\n"
    "🔄 /forcecheck — запустить немедленную проверку с сайта\n"
    "🔍 /lastcheck — время последней проверки\n"
    "⏸️ /stop — приостановить уведомления\n"
    "▶️ /resume — возобновить уведомления\n\n"
    "/logout — выйти и зарегистрировать другого человека"
)


class RegistrationStates(StatesGroup):
    waiting_for_surname = State()
    waiting_for_name = State()
    waiting_for_patronymic = State()
    waiting_for_passport = State()


class BroadcastStates(StatesGroup):
    waiting_for_message = State()

router = Router()


def _format_status_message(results: dict) -> str:
    parts = ["📊 Твои текущие результаты ЕГЭ:\n"]
    for subject, data in results.items():
        parts.append(
            notifier.format_subject_result_text(
                subject,
                date=data["date"],
                primary=data["primary"],
                test=data["test"],
                status=data["status"],
                appeal=data["appeal"],
            )
        )
        parts.append("-----------------------")
    return "\n".join(parts)


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного процесса.")
        return
    await state.clear()
    if current_state.startswith(BroadcastStates.__name__):
        await message.answer("❌ Рассылка отменена.")
    else:
        await message.answer("❌ Настройка отменена. Отправь /start, чтобы начать заново.")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if user:
        database.update_user_monitoring(chat_id, 1)
        await message.answer(
            "👋 Привет! Ты уже зарегистрирован в системе мониторинга результатов ЕГЭ.\n\n"
            "Доступные команды:\n"
            f"{REGISTERED_USER_COMMANDS}"
        )
        return

    await message.answer(
        "👋 Привет! Я бот для автоматического отслеживания результатов ЕГЭ на сайте РЦОИ Башкортостана.\n\n"
        "Чтобы начать получать уведомления, давай зарегистрируем твои данные для входа.\n"
        "*(В любой момент можно написать /cancel для отмены)*\n\n"
        "Введи, пожалуйста, свою *Фамилию* (с заглавной буквы):"
    )
    await state.set_state(RegistrationStates.waiting_for_surname)


@router.message(RegistrationStates.waiting_for_surname)
async def process_surname(message: Message, state: FSMContext):
    surname = message.text.strip()
    if not surname.replace('-', '').replace(' ', '').isalpha():
        await message.answer("⚠️ Фамилия должна состоять только из букв. Введи фамилию еще раз:")
        return
    await state.update_data(surname=surname.capitalize())
    await message.answer("Хорошо. Теперь введи свое *Имя* (с заглавной буквы):")
    await state.set_state(RegistrationStates.waiting_for_name)


@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name.replace('-', '').replace(' ', '').isalpha():
        await message.answer("⚠️ Имя должно состоять только из букв. Введи имя еще раз:")
        return
    await state.update_data(name=name.capitalize())
    await message.answer("Теперь введи свое *Отчество* (с заглавной буквы, если его нет в паспорте, введи символ `-`):")
    await state.set_state(RegistrationStates.waiting_for_patronymic)


@router.message(RegistrationStates.waiting_for_patronymic)
async def process_patronymic(message: Message, state: FSMContext):
    patronymic = message.text.strip()
    if patronymic != '-' and not patronymic.replace('-', '').replace(' ', '').isalpha():
        await message.answer("⚠️ Отчество должно состоять только из букв. Введи отчество еще раз:")
        return

    patronymic_val = "" if patronymic == '-' else patronymic.capitalize()
    await state.update_data(patronymic=patronymic_val)
    await message.answer("Отлично. Теперь введи *последние 6 цифр паспорта* (например, 123456):")
    await state.set_state(RegistrationStates.waiting_for_passport)


@router.message(RegistrationStates.waiting_for_passport)
async def process_passport(message: Message, state: FSMContext):
    passport = message.text.strip()
    if not (passport.isdigit() and len(passport) == 6):
        await message.answer("⚠️ Паспорт должен состоять ровно из 6 цифр. Пожалуйста, введи последние 6 цифр паспорта еще раз:")
        return

    data = await state.get_data()
    surname = data["surname"]
    name = data["name"]
    patronymic = data["patronymic"]
    chat_id = message.chat.id

    await state.clear()

    await message.answer(
        "⏳ Проверяю данные и выполняю первую попытку входа на сайт РЦОИ...\n"
        "Пожалуйста, подожди."
    )

    region = "Республика Башкортостан"

    try:
        parser.verify_student_credentials(
            surname=surname,
            name=name,
            patronymic=patronymic,
            passport=passport,
            region=region,
        )
    except parser.StudentVerificationError as e:
        logger.warning(f"Registration rejected for chat {chat_id}: {e}")
        await message.answer(
            "❌ Не удалось подтвердить данные на сайте РЦОИ Башкортостана.\n"
            "Убедись, что ФИО и последние 6 цифр паспорта введены без ошибок "
            "и на сайте есть расписание или результаты экзаменов.\n\n"
            "Начни настройку заново с помощью команды /start."
        )
        return
    except Exception as e:
        logger.error(f"Registration verification failed for chat {chat_id}: {e}")
        await message.answer(
            "❌ Не удалось проверить данные на сайте РЦОИ. Попробуй позже "
            "или начни заново с помощью команды /start."
        )
        return

    try:
        database.save_user(
            chat_id=chat_id,
            surname=surname,
            name=name,
            patronymic=patronymic,
            passport=passport,
            region=region,
        )

        user_data = database.get_user(chat_id)
        await monitor.run_check_cycle_for_user(bot, user_data)

    except Exception as e:
        logger.error(f"Registration failed for chat {chat_id}: {e}")
        database.delete_user(chat_id)
        await message.answer(
            "❌ Данные подтверждены, но не удалось завершить регистрацию.\n"
            "Попробуй ещё раз с помощью команды /start."
        )


@router.message(Command("status"))
async def cmd_status(message: Message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start, чтобы настроить мониторинг.")
        return

    results = database.load_results(chat_id)
    if not results:
        await message.answer("📊 В базе данных пока нет информации о твоих экзаменах. Запусти проверку через /forcecheck.")
        return

    await message.answer(_format_status_message(results), parse_mode="HTML")


@router.callback_query(F.data.startswith(notifier.SHOW_RESULT_PREFIX))
async def on_show_result(callback: CallbackQuery):
    subject = notifier.decode_subject_callback(callback.data)
    if not subject:
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await callback.answer("Ты не зарегистрирован.", show_alert=True)
        return

    results = database.load_results(chat_id)
    if subject not in results:
        await callback.answer("Результат не найден в базе.", show_alert=True)
        return

    data = results[subject]
    text = notifier.format_subject_result_text(
        subject,
        date=data["date"],
        primary=data["primary"],
        test=data["test"],
        status=data["status"],
        appeal=data["appeal"],
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return

    database.delete_user(chat_id)
    await state.clear()
    await message.answer(
        "🚪 Ты вышел из аккаунта. Все сохранённые данные удалены.\n\n"
        "Отправь /start, чтобы зарегистрировать другого человека."
    )


@router.message(Command("lastcheck"))
async def cmd_lastcheck(message: Message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return

    if user["last_check_at"]:
        await message.answer(f"🔍 Последняя проверка для тебя была выполнена: {user['last_check_at']}")
    else:
        await message.answer("🔍 Проверок еще не выполнялось.")


@router.message(Command("forcecheck"))
async def cmd_forcecheck(message: Message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return

    await message.answer("🔄 Выполняю немедленную проверку твоих результатов на сайте RCOI...")
    try:
        await monitor.run_check_cycle_for_user(bot, user)
        await message.answer("✅ Проверка успешно завершена! Проверь результаты командой /status.")
    except Exception as e:
        logger.error(f"Force check error for user {chat_id}: {e}")
        await message.answer(f"❌ Ошибка при проверке результатов: {e}")


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return

    database.update_user_monitoring(chat_id, 0)
    await message.answer("⏸️ Мониторинг результатов ЕГЭ приостановлен. Новые уведомления приходить не будут.")


@router.message(Command("resume"))
async def cmd_resume(message: Message):
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return

    database.update_user_monitoring(chat_id, 1)
    await message.answer("▶️ Мониторинг ЕГЭ возобновлен!")


@router.message(Command("tell"))
async def cmd_tell(message: Message, state: FSMContext):
    if not config.is_admin(message.chat.id):
        await message.answer("⚠️ Эта команда доступна только администратору.")
        return

    users = database.get_all_users()
    await state.set_state(BroadcastStates.waiting_for_message)
    await message.answer(
        f"📢 Готов принять сообщение для рассылки.\n"
        f"Зарегистрировано пользователей: {len(users)}\n\n"
        "Отправь текст, который нужно разослать всем.\n"
        "Для отмены напиши /cancel."
    )


@router.message(BroadcastStates.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    if not config.is_admin(message.chat.id):
        await state.clear()
        return

    if not message.text:
        await message.answer("⚠️ Отправь текстовое сообщение для рассылки или /cancel для отмены.")
        return

    await state.clear()

    users = database.get_all_users()
    if not users:
        await message.answer("📭 Нет зарегистрированных пользователей для рассылки.")
        return

    broadcast_text = message.text.strip()
    sent = 0
    failed = 0

    await message.answer(f"⏳ Рассылаю сообщение {len(users)} пользователям...")

    for user in users:
        try:
            await bot.send_message(chat_id=user["chat_id"], text=broadcast_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast failed for chat {user['chat_id']}: {e}")

    await message.answer(
        f"✅ Рассылка завершена.\n"
        f"Доставлено: {sent}\n"
        f"Ошибок: {failed}"
    )


async def on_startup(bot: Bot):
    logger.info("Bot starting up...")
    asyncio.create_task(monitor.monitoring_loop(bot))
    logger.info("Global background monitoring task created.")


async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.critical("BOT_TOKEN is not configured in .env file.")
        sys.exit("Critical Error: BOT_TOKEN is not set.")

    global bot
    if config.TELEGRAM_PROXY:
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(proxy=config.TELEGRAM_PROXY)
        bot = Bot(token=config.BOT_TOKEN, session=session)
        logger.info(f"Bot initialized using proxy: {config.TELEGRAM_PROXY}")
    else:
        bot = Bot(token=config.BOT_TOKEN)

    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    logger.info("Starting long polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
