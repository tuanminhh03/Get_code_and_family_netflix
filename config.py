# config.py
import os
from dotenv import load_dotenv

# luôn load .env ở thư mục hiện tại (project root)
load_dotenv(override=True)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'data.db')}")
SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'adminpass')

# ✅ đảm bảo có TUKI_URL; có thể để default đúng trang hiện tại
TUKI_URL = os.getenv('TUKI_URL', 'https://tukitech.com/user_management/customer_login/')


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


# Bật headless khi chạy trên Ubuntu/SSH để Chrome không cần UI.
TUKI_HEADLESS = _as_bool(os.getenv('TUKI_HEADLESS'), default=True)
