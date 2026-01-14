import os
import re
import time
import random 
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options 
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from multiprocessing import Pool

import config

# ----------------- CẤU HÌNH -----------------
INPUT_EMAILS = [
    "douinex+melida@gmail.com",
    # Thêm email khác...
]

# ĐIỀN MÃ 8 SỐ CỦA TV VÀO ĐÂY (Dạng chuỗi ký tự)
TV_CODE_TO_ENTER = "12345678" 

CTV_CODES = [
    "CTV0061", "CTV0070", "CTV0071", "CTV0072", "CTV0082", "CTV0088", 
    "CTV0090", "CTV0103", "CTV0102", "CTV0112", "CTV0122", "CTV0133", 
    "CTV0136", "CTV0148", "CTV0153", "CTV0163", "CTV0171", "CTV0179"
]

MAX_RETRIES = 3             
MAX_CONCURRENT_PROCESSES = 2 
# ------------------------------------------------


def _get_tv_password():
    """Lấy mật khẩu TV riêng (nếu đặt). Không fallback ADMIN để tránh chặn nhầm."""
    return os.getenv("TV_PASSWORD") or getattr(config, "TV_PASSWORD", "") or ""

def _resolve_email(email: str | None):
    if email and email.strip():
        return email.strip()
    for item in INPUT_EMAILS:
        candidate = (item or "").strip()
        if candidate:
            return candidate
    return None

def safe_click(driver, element):
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)

# --- HÀM LẤY VÀ DÁN MÃ TUKITECH ---
def get_and_paste_code(driver, wait, netflix_handle, tukitech_handle):
    driver.switch_to.window(tukitech_handle)
    try:
        BTN_SEARCH_ID = "search-btn"
        search_btn = wait.until(EC.element_to_be_clickable((By.ID, BTN_SEARCH_ID)))
        safe_click(driver, search_btn)
        
        CODE_CONTENT_CSS = "div.bg-light > span.text-dark"
        code_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CODE_CONTENT_CSS)))
        code_text = code_element.get_attribute('innerText').strip()
        
        if not code_text.isdigit() or len(code_text) < 4:
            return False 
        
        driver.switch_to.window(netflix_handle)
        CODE_INPUT_FINAL_CSS = "input[name='challengeOtp']" 
        final_code_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CODE_INPUT_FINAL_CSS)))
        final_code_field.clear() 
        final_code_field.send_keys(code_text)
        
        BTN_LOGIN_FINAL_XPATH = "//button[normalize-space()='Đăng nhập' or @type='submit']"
        login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, BTN_LOGIN_FINAL_XPATH)))
        safe_click(driver, login_btn)
        
        time.sleep(4) 
        
        # Kiểm tra nếu vào được Web thành công
        if "browse" in driver.current_url or "profiles" in driver.current_url:
            return True
        else:
            return False 
            
    except Exception:
        return False

# --- HÀM NHẬP MÃ TV (Logic mới) ---
def enter_tv_code(driver, wait, tv_code):
    try:
        print(" -> Đang truy cập trang nhập mã TV8...")
        driver.get("https://www.netflix.com/tv8")

        # Đảm bảo mã là chuỗi và đủ 8 ký tự
        code_str = str(tv_code).strip()
        if len(code_str) != 8 or not code_str.isdigit():
            print(f"LỖI: Mã TV phải có đúng 8 số. Mã hiện tại: {code_str}")
            return False, "Mã TV phải có đúng 8 số.", "invalid_input"

        # Vòng lặp điền từng số vào 8 ô input riêng biệt
        for i in range(8):
            digit = code_str[i]
            input_selector = f"input[data-uia='pin-number-{i}']"
            input_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, input_selector)))
            input_field.clear()
            input_field.send_keys(digit)
            time.sleep(0.1)

        print(f" -> Đã điền mã {code_str}. Đang bấm Continue...")

        submit_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-uia='witcher-code-submit']"))
        )
        safe_click(driver, submit_btn)

        # Các thông báo "sai mã" cần dừng ngay
        stop_texts = {
            "that code isn't right. try again.",
            "that code isnt right. try again.",
            "mã đó không đúng. hãy thử lại nào.",
        }
        skip_texts = {
            "đã xảy ra lỗi. hãy thử đăng nhập bằng điều khiển tv.",
        }

        # Chờ đến khi thành công hoặc nhận thông báo sai mã cụ thể
        start_time = time.time()
        max_wait_seconds = 60
        last_message = None

        while time.time() - start_time < max_wait_seconds:
            if "/tv/out/success" in (driver.current_url or ""):
                print(" -> ✅ KẾT QUẢ: ĐĂNG NHẬP TV THÀNH CÔNG (Url success)")
                return True, "Đăng nhập TV thành công.", None

            error_elements = driver.find_elements(
                By.CSS_SELECTOR,
                "div.nf-message-contents[data-uia='UIMessage-content']",
            )
            if error_elements:
                raw_text = (error_elements[0].text or "").strip()
                if raw_text:
                    lowered = raw_text.lower()

                    # Chỉ print khi message thay đổi để tránh spam log
                    if raw_text != last_message:
                        print(f" -> Thông báo lỗi trên trang TV: {raw_text}")
                        last_message = raw_text

                    # Nếu đúng message "mã sai" thì trả về luôn
                    if lowered in stop_texts:
                        print(" -> ❌ Sai mã TV, dừng lại.")
                        return False, "Mã bạn nhập sai vui lòng nhập lại", "invalid_tv_code"

            title_elements = driver.find_elements(
                By.CSS_SELECTOR,
                "h1.tvsignup-title[data-uia='witcher-code-title']",
            )
            if title_elements:
                raw_title = (title_elements[0].text or "").strip()
                lowered_title = raw_title.lower()
                if raw_title and raw_title != last_message:
                    print(f" -> Thông báo trạng thái TV: {raw_title}")
                    last_message = raw_title
                if lowered_title in skip_texts:
                    print(" -> ⚠️ Bỏ qua lỗi điều khiển TV, thử tài khoản khác.")
                    return False, raw_title, "tv_login_skip"

            time.sleep(1)

        print(" -> ❌ KẾT QUẢ: KHÔNG THẤY TRANG SUCCESS (Có thể sai mã hoặc lỗi hệ thống)")
        return False, "Không thể đăng nhập TV.", "tv_login_failed"

    except Exception as e:
        print(f" -> Lỗi khi nhập mã TV: {e}")
        return False, "Không thể đăng nhập TV.", "tv_login_error"


def worker_process(email):
    return _login_once(email=email, tv_code=TV_CODE_TO_ENTER)


def _login_once(email: str, tv_code: str, progress: list[str] | None = None):
    def push_step(message: str) -> None:
        if progress is not None:
            progress.append(message)

    chrome_options = Options()
    chrome_options.add_experimental_option("detach", True) 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    selected_ctv = random.choice(CTV_CODES)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 15)
    
    try:
        # --- BƯỚC 1: NETFLIX WEB LOGIN ---
        push_step("Đang mở trang đăng nhập Netflix.")
        driver.get("https://www.netflix.com/vn/login")
        netflix_handle = driver.current_window_handle
        
        btn_use_code = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Sử dụng mã đăng nhập']")))
        safe_click(driver, btn_use_code)
        
        wait.until(EC.presence_of_element_located((By.NAME, "userLoginId"))).send_keys(email)
        
        btn_send = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Gửi mã đăng nhập']")))
        safe_click(driver, btn_send)
        push_step("Đã gửi yêu cầu mã đăng nhập.")
        
        time.sleep(2) 

        # --- BƯỚC 2: TUKITECH ---
        push_step("Đang lấy mã đăng nhập từ Tukitech.")
        driver.execute_script("window.open('');")
        tukitech_handle = [h for h in driver.window_handles if h != netflix_handle][0]
        driver.switch_to.window(tukitech_handle)
        
        driver.get("https://tukitech.com/user_management/customer_login/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Nhập tên đăng nhập']"))).send_keys(selected_ctv)
        safe_click(driver, wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Tiếp tục']"))))
        
        wait.until(EC.url_to_be("https://tukitech.com/email_search/"))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='example@domain.com']"))).send_keys(email)
        
        dropdown = wait.until(EC.presence_of_element_located((By.ID, "condition")))
        Select(dropdown).select_by_visible_text("Netflix: Mã Đăng Nhập")
        
        # --- BƯỚC 3: RETRY LOOP & XỬ LÝ TV ---
        print(f"[{email}] Bắt đầu quy trình...")
        push_step("Đang xác thực tài khoản trên Netflix.")
        login_web_success = False

        for attempt in range(1, MAX_RETRIES + 1):
            login_web_success = get_and_paste_code(driver, wait, netflix_handle, tukitech_handle)
            
            if login_web_success:
                print(f"[{email}] -> Đăng nhập Web OK.")
                push_step("Đăng nhập web thành công.")
                break 
            
            elif attempt < MAX_RETRIES:
                print(f"[{email}] -> Web Login thất bại (Lần {attempt}). Thử lại sau 15s...")
                push_step(f"Đăng nhập web thất bại, thử lại lần {attempt + 1}.")
                driver.switch_to.window(tukitech_handle)
                time.sleep(15)

        # --- BƯỚC 4: NẾU WEB OK -> CHUYỂN QUA NHẬP MÃ TV ---
        if login_web_success:
            driver.switch_to.window(netflix_handle)
            push_step("Đang nhập mã TV.")
            tv_success, tv_message, tv_reason = enter_tv_code(driver, wait, tv_code)
            if tv_success:
                push_step("Đăng nhập TV thành công.")
            else:
                push_step(f"Đăng nhập TV thất bại: {tv_message}")
            return {
                "success": tv_success,
                "message": tv_message,
                "reason": tv_reason,
                "email": email,
                "steps": progress or [],
            }

        return {
            "success": False,
            "message": "Không qua được bước đăng nhập Web.",
            "email": email,
            "steps": progress or [],
        }

    except Exception as e:
        push_step(f"Lỗi trong quá trình xử lý: {e}")
        return {"success": False, "message": f"Lỗi với {email}: {e}", "email": email, "steps": progress or []}

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _iter_emails(email: str | None):
    seen = set()
    candidates = []
    if email and email.strip():
        candidates.append(email.strip())
    candidates.extend(INPUT_EMAILS)
    for item in candidates:
        candidate = (item or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate


def login_tv(password: str, code: str, email: str | None = None, expected_password: str | None = None):
    expected_password = (expected_password if expected_password is not None else _get_tv_password()) or ""
    expected_password = expected_password.strip()
    if not expected_password:
        return {
            "success": False,
            "message": "Chưa cấu hình mật khẩu đăng nhập TV.",
            "steps": ["Chưa cấu hình mật khẩu đăng nhập TV."],
        }
    if password != expected_password:
        return {"success": False, "message": "Sai mật khẩu đăng nhập TV.", "steps": ["Sai mật khẩu đăng nhập TV."]}

    if not re.fullmatch(r"\d{8}", code or ""):
        return {"success": False, "message": "Mã TV phải đủ 8 số.", "steps": ["Mã TV phải đủ 8 số."]}

    emails = list(_iter_emails(email))
    if not emails:
        return {"success": False, "message": "Không có email nào để đăng nhập TV.", "steps": ["Không có email nào để đăng nhập TV."]}

    last_result = None
    for target_email in emails:
        progress: list[str] = []
        result = _login_once(email=target_email, tv_code=code, progress=progress)
        if isinstance(result, dict):
            last_result = result
            if result.get("success"):
                return result
            if result.get("reason") == "invalid_tv_code":
                return result
            continue

    return {
        "success": False,
        "message": "Không thể đăng nhập TV.",
        "email": last_result.get("email") if last_result else None,
        "steps": last_result.get("steps") if last_result else [],
    }

if __name__ == "__main__":
    tasks = [e.strip() for e in INPUT_EMAILS if e.strip()]
    with Pool(processes=MAX_CONCURRENT_PROCESSES) as pool:
        pool.map(worker_process, tasks)
