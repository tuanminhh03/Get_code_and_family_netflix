# config.py
import os
from dotenv import load_dotenv

# luôn load .env ở thư mục hiện tại (project root)
load_dotenv(override=True)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'data.db')}")
SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'adminpass')
USERNAME_TUKI = os.getenv('USERNAME_TUKI', 'CTV0047')

# ✅ đảm bảo có TUKI_URL; có thể để default đúng trang hiện tại
TUKI_URL = os.getenv('TUKI_URL', 'https://tukitech.com/user_management/customer_login/')


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


# Bật headless mặc định để tránh lỗi khi môi trường không có UI/Chrome.
# Nếu muốn xem trình duyệt, đặt TUKI_HEADLESS=0 hoặc "false".
TUKI_HEADLESS = _as_bool(os.getenv('TUKI_HEADLESS'), default=True)

# Bỏ qua check DISPLAY và ép chạy headful (phù hợp khi dùng Xvfb/VNC).
# Đặt TUKI_FORCE_HEADFUL=1 để bật.
TUKI_FORCE_HEADFUL = _as_bool(os.getenv("TUKI_FORCE_HEADFUL"), default=False)

# Dùng Chrome profile hiện tại hoặc gắn vào Chrome đang mở.
# - TUKI_CHROME_USER_DATA_DIR: đường dẫn đến user data dir của Chrome.
# - TUKI_CHROME_PROFILE_DIR: tên profile (vd: "Default", "Profile 1").
# - TUKI_CHROME_DEBUGGER_ADDRESS: địa chỉ debugger, vd "127.0.0.1:9222".
TUKI_CHROME_USER_DATA_DIR = os.getenv("TUKI_CHROME_USER_DATA_DIR", "")
TUKI_CHROME_PROFILE_DIR = os.getenv("TUKI_CHROME_PROFILE_DIR", "")
TUKI_CHROME_DEBUGGER_ADDRESS = os.getenv("TUKI_CHROME_DEBUGGER_ADDRESS", "")


def chrome_debugger_address() -> str:
    return (TUKI_CHROME_DEBUGGER_ADDRESS or "").strip()


def is_debugger_enabled() -> bool:
    return bool(chrome_debugger_address())


def apply_chrome_profile(options) -> bool:
    """Áp cấu hình profile/debugger vào ChromeOptions."""
    debugger_address = chrome_debugger_address()
    if debugger_address:
        options.add_experimental_option("debuggerAddress", debugger_address)
        return True

    user_data_dir = (TUKI_CHROME_USER_DATA_DIR or "").strip()
    profile_dir = (TUKI_CHROME_PROFILE_DIR or "").strip()

    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if profile_dir:
        options.add_argument(f"--profile-directory={profile_dir}")
    return False


def apply_stealth_settings(driver) -> None:
    """Giảm dấu hiệu automation cho Chrome sau khi tạo driver."""
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                    "window.chrome = window.chrome || { runtime: {} };"
                    "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});"
                    "Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US']});"
                )
            },
        )
    except Exception:
        # Không chặn luồng chính nếu CDP không khả dụng.
        pass
