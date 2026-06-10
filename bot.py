import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import config
import database
import monitor
import parser

# Configure stdout and logging
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

# Define FSM States for registration
class RegistrationStates(StatesGroup):
    waiting_for_surname = State()
    waiting_for_name = State()
    waiting_for_patronymic = State()
    waiting_for_passport = State()

# Initialize Router
router = Router()

@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    """
    Cancels the registration wizard at any stage.
    """
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного процесса регистрации.")
        return
    await state.clear()
    await message.answer("❌ Настройка отменена. Отправь /start, чтобы начать заново.")

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """
    Greets the user and starts the registration FSM wizard if the user is new.
    """
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if user:
        # User already exists, ensure monitoring is active
        database.update_user_monitoring(chat_id, 1)
        await message.answer(
            "👋 Привет! Ты уже зарегистрирован в системе мониторинга результатов ЕГЭ.\n\n"
            "Доступные команды:\n"
            "📊 /status — проверить текущие баллы\n"
            "🔄 /forcecheck — запустить немедленную проверку с сайта\n"
            "🔍 /lastcheck — время последней проверки\n"
            "⏸️ /stop — приостановить уведомления\n"
            "▶️ /resume — возобновить уведомления"
        )
        return
        
    await message.answer(
        "👋 Привет! Я бот для автоматического отслеживания результатов ЕГЭ на сайте РЦОИ Башкортостана.\n\n"
        "Чтобы начать получать уведомления, давай зарегистрируем твои данные для входа.\n"
        "*(В любой момент можно написать /cancel для отмены)*\n\n"
        "Введи, пожалуйста, свою *Фамилию* (с заглавной буквы):")
    await state.set_state(RegistrationStates.waiting_for_surname)

@router.message(RegistrationStates.waiting_for_surname)
async def process_surname(message: Message, state: FSMContext):
    """
    Saves surname input and requests name.
    """
    surname = message.text.strip()
    if not surname.replace('-', '').replace(' ', '').isalpha():
        await message.answer("⚠️ Фамилия должна состоять только из букв. Введи фамилию еще раз:")
        return
    await state.update_data(surname=surname.capitalize())
    await message.answer("Хорошо. Теперь введи свое *Имя* (с заглавной буквы):")
    await state.set_state(RegistrationStates.waiting_for_name)

@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """
    Saves name input and requests patronymic.
    """
    name = message.text.strip()
    if not name.replace('-', '').replace(' ', '').isalpha():
        await message.answer("⚠️ Имя должно состоять только из букв. Введи имя еще раз:")
        return
    await state.update_data(name=name.capitalize())
    await message.answer("Теперь введи свое *Отчество* (с заглавной буквы, если его нет в паспорте, введи символ `-`):")
    await state.set_state(RegistrationStates.waiting_for_patronymic)

@router.message(RegistrationStates.waiting_for_patronymic)
async def process_patronymic(message: Message, state: FSMContext):
    """
    Saves patronymic and requests the 6 passport digits.
    """
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
    """
    Saves passport, performs database entry and fires the initial verification check.
    """
    passport = message.text.strip()
    if not (passport.isdigit() and len(passport) == 6):
        await message.answer("⚠️ Паспорт должен состоять ровно из 6 цифр. Пожалуйста, введи последние 6 цифр паспорта еще раз:")
        return
        
    data = await state.get_data()
    surname = data["surname"]
    name = data["name"]
    patronymic = data["patronymic"]
    
    chat_id = message.chat.id
    
    # Reset FSM state
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
    """
    Displays current results saved in the database for this specific user.
    """
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start, чтобы настроить мониторинг.")
        return
        
    results = database.get_all_results(chat_id)
    if not results:
        await message.answer("📊 В базе данных пока нет информации о твоих экзаменах. Запусти проверку через /forcecheck.")
        return
        
    parts = ["📊 Твои текущие результаты ЕГЭ:\n"]
    for item in results:
        primary = item["primary_score"] if item["primary_score"] is not None else "-"
        test = item["test_score"] if item["test_score"] is not None else "-"
        appeal = item["appeal"] if item["appeal"] else "отсутствует"
        
        parts.append(
            f"<b>Предмет:</b> {item['subject']}\n"
            f"📅 Дата экзамена: {item['exam_date']}\n"
            f"🔢 Первичный балл: {primary}\n"
            f"🎓 Тестовый балл: {test}\n"
            f"⚙️ Статус: {item['status']}\n"
            f"⚖️ Апелляция: {appeal}\n"
            "-----------------------"
        )
    await message.answer("\n".join(parts), parse_mode="HTML")

@router.message(Command("lastcheck"))
async def cmd_lastcheck(message: Message):
    """
    Shows when the user's results were last checked.
    """
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
    """
    Triggers an immediate check for the user.
    """
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
    """
    Pauses monitoring notifications for the user.
    """
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return
        
    database.update_user_monitoring(chat_id, 0)
    await message.answer("⏸️ Мониторинг результатов ЕГЭ приостановлен. Новые уведомления приходить не будут.")

@router.message(Command("resume"))
async def cmd_resume(message: Message):
    """
    Resumes monitoring notifications for the user.
    """
    chat_id = message.chat.id
    user = database.get_user(chat_id)
    if not user:
        await message.answer("⚠️ Ты еще не зарегистрирован. Отправь /start.")
        return
        
    database.update_user_monitoring(chat_id, 1)
    await message.answer("▶️ Мониторинг ЕГЭ возобновлен!")

async def on_startup(bot: Bot):
    """
    Starts the global background monitoring thread.
    """
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
