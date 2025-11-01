# tuki_persistent.py — persistent Selenium session for Tukitech
import time, threading, traceback, re
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Yêu cầu trong config.py có:
# TUKI_URL = 'https://tukitech.com/user_management/customer_login/'
# USERNAME_TUKI = 'CTV0047'
import config

RESULT_WAIT_MAX = 15
IDLE_REFRESH_SECONDS = 300   # refresh nếu rảnh > 5 phút
WAIT_SHORT, WAIT_MED, WAIT_LONG = 4, 10, 20


def _parse_code_time_text(raw_text: str):
    """Bóc 'Nội dung:' (mã) và 'Thời gian nhận:' từ block kết quả."""
    if not raw_text:
        return "", "", ""
    t = raw_text.replace("\r", "")
    code, t_raw = "", ""
    m1 = re.search(r"(?i)Nội dung:\s*([^\n\r]+)", t)
    if m1: code = m1.group(1).strip()
    m2 = re.search(r"(?i)Thời gian nhận:\s*([^\n\r]+)", t)
    if m2: t_raw = m2.group(1).strip()

    t_iso = ""
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            t_iso = datetime.strptime(t_raw, fmt).isoformat(); break
        except Exception:
            continue
    return code, t_raw, t_iso


class TukiPersistent:
    """
    Giữ 1 phiên Chrome Selenium luôn mở tại trang tìm kiếm Tukitech.
    fetch(email, kind) chỉ: điền email → chọn condition → bấm "Tìm kiếm" → đọc #results-content.
    kind: 'login_code' | 'verify_link'
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        self.wait = None
        self.lock = threading.Lock()
        self.last_active = 0
        self._start_driver()

    # ---------- driver ----------
    def _start_driver(self):
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--log-level=3")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(2)

        self.wait = WebDriverWait(self.driver, WAIT_LONG)
        self._go_search_page()
        self.last_active = time.time()

    def _restart(self):
        try:
            if self.driver: self.driver.quit()
        except: pass
        self.driver = None
        self.wait = None
        self._start_driver()

    def _ensure_driver(self):
        if self.driver is None:
            self._start_driver()
            return
        try:
            _ = self.driver.current_url
        except Exception:
            self._restart()

    # ---------- điều hướng tới form tìm kiếm (qua bước username nếu có) ----------
    def _go_search_page(self):
        base = (getattr(config, "TUKI_URL", "") or "").strip()
        if not base:
            raise RuntimeError("Thiếu TUKI_URL trong config/.env")
        self.driver.get(base)

        # Chờ hoặc form username, hoặc input email
        try:
            self.wait.until(lambda d: d.find_elements(By.ID, "username") or d.find_elements(By.ID, "email"))
        except Exception:
            self.driver.refresh()
            self.wait.until(lambda d: d.find_elements(By.ID, "username") or d.find_elements(By.ID, "email"))

        # Nếu có bước username (CTV0047) → đi qua
        if self._exists(By.ID, "username"):
            try:
                u = self.wait.until(EC.presence_of_element_located((By.ID, "username")))
                try: u.clear()
                except: pass
                u.send_keys(getattr(config, "USERNAME_TUKI", "") or "CTV0047")

                # Click nút tiếp tục / submit
                self._try_click_any([
                    (By.CSS_SELECTOR, "button.btn.btn-success.w-100"),
                    (By.XPATH, "//button[contains(., 'Tiếp tục')]"),
                    (By.XPATH, "//button[@type='submit']"),
                ], timeout=WAIT_SHORT)
            except Exception:
                pass  # bỏ qua nếu trang không yêu cầu

        # Chờ ô email xuất hiện
        self.wait.until(EC.presence_of_element_located((By.ID, "email")))

    # ---------- utils ----------
    def _exists(self, by, sel):
        try:
            return bool(self.driver.find_elements(by, sel))
        except:
            return False

    def _try_click_any(self, candidates, timeout=WAIT_MED):
        for by, sel in candidates:
            try:
                WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, sel))).click()
                return True
            except Exception:
                continue
        return False

    def _select_condition(self, kind: str):
        """Chọn option đúng trong <select id="condition"> theo kind."""
        try:
            sel = self.driver.find_element(By.ID, "condition")
        except:
            return
        S = Select(sel)
        if kind == "login_code":
            # Mã đăng nhập / mã tạm thời
            for v in ("netflix_code", "netflix_temp_code", "code", "login_code"):
                try: S.select_by_value(v); return
                except: pass
            for t in ("Netflix: Mã Đăng Nhập", "Netflix: Mã Tạm Thời", "Mã đăng nhập", "Login code"):
                try: S.select_by_visible_text(t); return
                except: pass
        elif kind == "verify_link":
            # Link xác minh hộ gia đình
            for v in ("netflix_verify", "verify_link", "household_verify", "netflix_household"):
                try: S.select_by_value(v); return
                except: pass
            for t in ("Netflix: Link Xác Minh Gia Đình", "Link xác minh", "Xác minh hộ gia đình", "Household verify"):
                try: S.select_by_visible_text(t); return
                except: pass

    # ---------- hành động chính ----------
    def fetch(self, email: str, kind: str = "login_code"):
        """API chính backend gọi: điền email, chọn condition, ấn tìm kiếm và đọc kết quả."""
        with self.lock:
            try:
                self._ensure_driver()

                # refresh nhẹ nếu để lâu
                if time.time() - self.last_active > IDLE_REFRESH_SECONDS:
                    try:
                        self.driver.refresh()
                        self.wait.until(EC.presence_of_element_located((By.ID, "email")))
                    except:
                        self._restart()

                # đảm bảo ở form
                if not self._exists(By.ID, "email"):
                    self._go_search_page()

                el = self.wait.until(EC.presence_of_element_located((By.ID, "email")))
                try: el.clear()
                except: pass
                el.send_keys(email)

                self._select_condition(kind)

                # bấm Tìm kiếm
                if not self._try_click_any([
                    (By.XPATH, "//button[contains(., 'Tìm kiếm')]"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.XPATH, "//input[@type='submit' and (contains(@value,'Tìm') or contains(@value,'Search'))]")
                ], timeout=WAIT_SHORT):
                    raise RuntimeError("Không click được nút Tìm kiếm")

                # đọc kết quả
                root = WebDriverWait(self.driver, RESULT_WAIT_MAX).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#results-content"))
                )

                # cảnh báo không tìm thấy
                try:
                    warn = root.find_element(By.CSS_SELECTOR, ".alert.alert-warning")
                    msg = (warn.text or "").strip()
                    self.last_active = time.time()
                    return {"success": False, "message": msg, "kind": kind}
                except: pass

                raw = (root.text or "").strip()
                code, t_raw, t_iso = _parse_code_time_text(raw)

                self.last_active = time.time()
                return {
                    "success": True, "message": "OK", "kind": kind,
                    "content": raw, "code": code,
                    "received_at_raw": t_raw, "received_at": t_iso
                }

            except Exception as e:
                traceback.print_exc()
                self._restart()
                return {"success": False, "message": f"Lỗi: {e}", "kind": kind}
