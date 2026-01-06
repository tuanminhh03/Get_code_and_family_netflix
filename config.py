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


def _headless_default() -> bool:
    """
    Headless mặc định:
    - Windows / có DISPLAY/WAYLAND: ưu tiên hiển thị (default False)
    - Không có UI (server/CI, không DISPLAY): bật headless để tránh treo Chrome
    """
    if os.name == "nt":
        return False
    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        return False
    return True


# Nếu muốn xem trình duyệt, đặt TUKI_HEADLESS=0 hoặc "false".
# Nếu muốn headless trên máy có UI, đặt TUKI_HEADLESS=1.
TUKI_HEADLESS = _as_bool(os.getenv('TUKI_HEADLESS'), default=_headless_default())
