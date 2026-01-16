# tuki_persistent.py
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

import config

TUKI_URL = getattr(config, "TUKI_URL", "https://tukitech.com/user_management/customer_login/")
USERNAME_TUKI = getattr(config, "USERNAME_TUKI", "CTV0047")

class TukiPersistent:
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        self.ready = False
        self._start_driver()          # khởi tạo ngay khi tạo instance
        self._go_search_page()        # mở sẵn trang, điền sẵn “Netflix: Mã đăng nhập”
        self.ready = True
        print("🟢 Tukitech sẵn sàng")

    def _start_driver(self):
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1280,900")
        config.apply_chrome_profile(opts)
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
        config.apply_stealth_settings(self.driver)
        self.driver.set_page_load_timeout(90)

    def _go_search_page(self):
        d = self.driver
        d.get(TUKI_URL)
        wait = WebDriverWait(d, 25)
        # login bước 1 nếu có
        try:
            user = wait.until(EC.presence_of_element_located((By.ID, "username")))
            user.clear(); user.send_keys(USERNAME_TUKI)
            d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        except Exception:
            pass  # có thể đã login
        # chờ form tìm kiếm
        wait.until(EC.presence_of_element_located((By.ID, "email")))
        # chọn điều kiện mặc định
        try:
            Select(d.find_element(By.ID, "condition")).select_by_value("netflix_code")
        except Exception:
            pass

    def _ensure_ready(self):
        if not self.driver:
            self._start_driver(); self._go_search_page(); self.ready = True
            return
        try:
            _ = self.driver.current_url
        except Exception:
            self._start_driver(); self._go_search_page(); self.ready = True

    # public API
    def fetch(self, email, kind="login_code"):
        self._ensure_ready()
        d = self.driver; wait = WebDriverWait(d, 20)

        # đổi điều kiện nếu cần
        if kind == "verify_link":
            try: Select(d.find_element(By.ID, "condition")).select_by_value("netflix_verify")
            except Exception: pass
        else:
            try: Select(d.find_element(By.ID, "condition")).select_by_value("netflix_code")
            except Exception: pass

        # điền email và bấm Tìm kiếm
        box = wait.until(EC.presence_of_element_located((By.ID, "email")))
        box.clear(); box.send_keys(email)
        for sel in [
            (By.XPATH, "//button[contains(., 'Tìm kiếm')]"),
            (By.CSS_SELECTOR, "button[type='submit']")
        ]:
            try:
                wait.until(EC.element_to_be_clickable(sel)).click(); break
            except Exception: pass

        # lấy kết quả (mã 4 số hoặc link)
        try:
            # khối kết quả phổ biến – bạn có thể chỉnh selector phù hợp site của bạn
            code_el = WebDriverWait(d, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#search-results, .card-body"))
            )
            txt = code_el.text.strip()
            # heuristics: nếu có http thì trả link, nếu 4 số thì trả code
            if "http" in txt:
                link = next((p for p in txt.split() if p.startswith("http")), "")
                return {"success": True, "verify_link": link}
            # tìm mã 4 số
            import re
            m = re.search(r"\b(\d{4,6})\b", txt)
            if m:
                return {"success": True, "code": m.group(1)}
            return {"success": False, "message": "Không tìm thấy dữ liệu."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi khi đọc kết quả: {e}"}
