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
        if len(code_str) != 8:
            print(f"LỖI: Mã TV phải có đúng 8 số. Mã hiện tại: {code_str}")
            return False

        # Vòng lặp điền từng số vào 8 ô input riêng biệt
        for i in range(8):
            digit = code_str[i]
            # Selector theo data-uia="pin-number-0" đến "pin-number-7"
            input_selector = f"input[data-uia='pin-number-{i}']"
            input_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, input_selector)))
            input_field.clear()
            input_field.send_keys(digit)
            time.sleep(0.1) # Delay nhẹ để giống người nhập

        print(f" -> Đã điền mã {code_str}. Đang bấm Continue...")
        
        # Bấm nút CONTINUE (data-uia="witcher-code-submit")
        # Nút này ban đầu disabled, cần đợi nó enable hoặc click được
        submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-uia='witcher-code-submit']")))
        safe_click(driver, submit_btn)
        
        # Chờ kiểm tra URL Success
        try:
            wait.until(EC.url_contains("/tv/out/success"))
            print(" -> ✅ KẾT QUẢ: ĐĂNG NHẬP TV THÀNH CÔNG (Url success)")
            return True
        except TimeoutException:
            print(" -> ❌ KẾT QUẢ: KHÔNG THẤY TRANG SUCCESS (Có thể sai mã hoặc lỗi hệ thống)")
            return False

    except Exception as e:
        print(f" -> Lỗi khi nhập mã TV: {e}")
        return False

def worker_process(email):
    chrome_options = Options()
    chrome_options.add_experimental_option("detach", True) 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    selected_ctv = random.choice(CTV_CODES)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 15)
    
    try:
        # --- BƯỚC 1: NETFLIX WEB LOGIN ---
        driver.get("https://www.netflix.com/vn/login")
        netflix_handle = driver.current_window_handle
        
        btn_use_code = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Sử dụng mã đăng nhập']")))
        safe_click(driver, btn_use_code)
        
        wait.until(EC.presence_of_element_located((By.NAME, "userLoginId"))).send_keys(email)
        
        btn_send = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Gửi mã đăng nhập']")))
        safe_click(driver, btn_send)
        
        time.sleep(2) 

        # --- BƯỚC 2: TUKITECH ---
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
        login_web_success = False

        for attempt in range(1, MAX_RETRIES + 1):
            login_web_success = get_and_paste_code(driver, wait, netflix_handle, tukitech_handle)
            
            if login_web_success:
                print(f"[{email}] -> Đăng nhập Web OK.")
                break 
            
            elif attempt < MAX_RETRIES:
                print(f"[{email}] -> Web Login thất bại (Lần {attempt}). Thử lại sau 15s...")
                driver.switch_to.window(tukitech_handle)
                time.sleep(15)

        # --- BƯỚC 4: NẾU WEB OK -> CHUYỂN QUA NHẬP MÃ TV ---
        if login_web_success:
            # Chuyển về tab Netflix
            driver.switch_to.window(netflix_handle)
            # Gọi hàm xử lý TV8
            enter_tv_code(driver, wait, TV_CODE_TO_ENTER)
        else:
            print(f"[{email}] -> Không qua được bước đăng nhập Web. Dừng.")

    except Exception as e:
        print(f"Lỗi với {email}: {e}")

if __name__ == "__main__":
    tasks = [e.strip() for e in INPUT_EMAILS if e.strip()]
    with Pool(processes=MAX_CONCURRENT_PROCESSES) as pool:
        pool.map(worker_process, tasks)