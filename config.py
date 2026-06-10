import os
from pathlib import Path
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Base project directory
BASE_DIR = Path(__file__).resolve().parent

# Ensure target directories exist automatically
(BASE_DIR / "logs").mkdir(exist_ok=True)
(BASE_DIR / "data").mkdir(exist_ok=True)

# Bot Settings
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# Student Credentials
SURNAME = os.getenv("SURNAME", "Иванов")
NAME = os.getenv("NAME", "Макар")
PATRONYMIC = os.getenv("PATRONYMIC", "Владимирович")
PASSPORT = os.getenv("PASSPORT", "422184")
REGION = os.getenv("REGION", "Республика Башкортостан")

# Interval between checks in seconds (default 60 seconds)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

# Telegram Proxy (optional, e.g. http://127.0.0.1:1080)
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "")

# Paths for data storage and logging
DB_PATH = str(BASE_DIR / "data" / "results.db")
LOG_FILE = str(BASE_DIR / "logs" / "app.log")
