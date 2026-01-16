import os
import re
import time
import random
from multiprocessing import Pool

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

# ----------------- CẤU HÌNH -----------------
INPUT_EMAILS = [
    # "example@gmail.com",
    # Thêm email khác...
]

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


def _iter_emails(email: str | None):
    seen = set()
    if email and email.strip():
        candidate = email.strip()
        if candidate not in seen:
            seen.add(candidate)
            yield candidate
        return
    for item in INPUT_EMAILS:
        candidate = (item or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate


# ----------------- NETFLIX HELPERS (PLAYWRIGHT) -----------------
def _extract_netflix_message_pw(page) -> str | None:
    selectors = [
        "div.nf-message-contents[data-uia='UIMessage-content']",
        "div[data-uia='UIMessage-content']",
        "p[data-uia='UIMessage-content']",
        "span[data-uia='UIMessage-content']",
        "div.ui-message-container",
        "div[role='alert']",
        "div.alert-error",
        "div[data-uia='error-message']",
        "p[data-uia='error-message']",
        "span[data-uia='error-message']",
    ]
    for css in selectors:
        try:
            loc = page.locator(css).first
            if loc.count() > 0:
                txt = (loc.inner_text(timeout=500) or "").strip()
                if txt:
                    return txt
        except Exception:
            pass
    return None


def netflix_continue_wait_otp(page, email: str, timeout_sec: int = 25):
    """
    ĐÚNG YÊU CẦU CỦA BẠN:
    - Vào trang login
    - Điền email
    - Bấm Tiếp tục
    - ĐỢI ô OTP (challengeOtp) hiện ra
    Không "skip sớm" theo password.
    """
    page.goto("https://www.netflix.com/vn/login", wait_until="domcontentloaded")

    page.locator("input[name='userLoginId']").fill(email)

    btn = page.locator("button[data-uia='continue-button']").first
    btn.click()

    # fallback nếu click bị nuốt
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass

    otp = page.locator("input[name='challengeOtp']").first
    try:
        otp.wait_for(state="visible", timeout=timeout_sec * 1000)
        return True, None, None
    except PWTimeout:
        url = page.url
        msg = _extract_netflix_message_pw(page)

        # chỉ để báo tình trạng cho bạn dễ debug
        pw_visible = False
        try:
            pw = page.locator("input[name='password']").first
            pw_visible = pw.count() > 0 and pw.is_visible()
        except Exception:
            pass

        if msg:
            return False, f"Không thấy ô nhập mã. Netflix báo: {msg} (URL: {url})", "login_failed"
        if pw_visible:
            return False, f"Không thấy ô nhập mã, Netflix đang hiện ô mật khẩu (URL: {url})", "need_password"
        return False, f"Không thấy ô nhập mã sau {timeout_sec}s (URL: {url})", "login_failed"


# ----------------- TUKITECH HELPERS (PLAYWRIGHT) -----------------
def tukitech_prepare_search(tukitech_page, email: str, ctv_code: str):
    tukitech_page.goto("https://tukitech.com/user_management/customer_login/", wait_until="domcontentloaded")

    tukitech_page.locator("input[placeholder='Nhập tên đăng nhập']").fill(ctv_code)
    tukitech_page.locator("xpath=//button[normalize-space()='Tiếp tục']").click()

    tukitech_page.wait_for_url("https://tukitech.com/email_search/", timeout=20000)

    tukitech_page.locator("input[placeholder='example@domain.com']").fill(email)

    # chọn dropdown "Netflix: Mã Đăng Nhập"
    tukitech_page.locator("#condition").select_option(label="Netflix: Mã Đăng Nhập")


def tukitech_fetch_code(tukitech_page) -> str | None:
    """
    Bấm search -> lấy code text
    """
    try:
        tukitech_page.locator("#search-btn").click()
        code_text = tukitech_page.locator("div.bg-light > span.text-dark").first.inner_text(timeout=15000).strip()
        if code_text.isdigit() and len(code_text) >= 4:
            return code_text
    except Exception:
        pass
    return None


# ----------------- MAIN FLOW HELPERS (PLAYWRIGHT) -----------------
def get_and_paste_code_pw(netflix_page, tukitech_page):
    """
    - Tukitech: bấm search -> lấy code
    - Netflix: dán vào input[name='challengeOtp'] -> xác nhận login thành công bằng URL/selector
    """
    try:
        # --- Tukitech search ---
        tukitech_page.locator("#search-btn").click()
        raw = tukitech_page.locator("div.bg-light > span.text-dark").first.inner_text(timeout=15000)
        code_text = (raw or "").strip()

        # Một số nơi copy ra kèm khoảng trắng/newline => gom lại chỉ còn số
        code_digits = re.sub(r"\D+", "", code_text)

        if (not code_digits.isdigit()) or len(code_digits) < 4:
            print(f"[DEBUG] Tukitech code không hợp lệ: raw='{code_text}' digits='{code_digits}'")
            return False

        # --- Netflix paste OTP ---
        otp = netflix_page.locator("input[name='challengeOtp']").first
        otp.wait_for(state="visible", timeout=15000)
        otp.fill(code_digits)

        # Netflix đôi khi cần enter hoặc auto-submit; cứ bấm Enter cho chắc
        try:
            otp.press("Enter", timeout=1000)
        except Exception:
            pass

        # --- ĐỢI ĐÚNG TÍN HIỆU LOGIN THÀNH CÔNG ---
        # 1) Wait URL cụ thể (regex), KHÔNG dùng "**/*"
        try:
            netflix_page.wait_for_url(re.compile(r".*/(browse|profiles|youraccount|account).*", re.I), timeout=25000)
            print(f"[DEBUG] Web login OK by URL: {netflix_page.url}")
            return True
        except Exception:
            pass

        # 2) Fallback bằng selector thường thấy sau login / profile gate
        success_selectors = [
            "a[href*='/browse']",                         # link Browse trong header
            "div[data-uia='profile-gate-container']",     # trang chọn profile
            "div.profile-gate-container",
            "header[data-uia='header']",                  # header sau login
        ]
        for sel in success_selectors:
            try:
                if netflix_page.locator(sel).first.is_visible(timeout=3000):
                    print(f"[DEBUG] Web login OK by selector '{sel}', url={netflix_page.url}")
                    return True
            except Exception:
                pass

        # 3) Nếu vẫn fail -> in debug message để biết thật sự bị lỗi gì
        msg = _extract_netflix_message_pw(netflix_page)
        print(f"[DEBUG] Web login NOT confirmed. url={netflix_page.url} msg={msg!r}")
        return False

    except Exception as e:
        print(f"[DEBUG] get_and_paste_code_pw exception: {e}")
        return False

def enter_tv_code_pw(netflix_page, tv_code: str):
    try:
        print(" -> Đang truy cập trang nhập mã TV8...")
        netflix_page.goto("https://www.netflix.com/tv8", wait_until="domcontentloaded")

        code_str = str(tv_code).strip()
        if len(code_str) != 8 or not code_str.isdigit():
            print(f"LỖI: Mã TV phải có đúng 8 số. Mã hiện tại: {code_str}")
            return False, "Mã TV phải có đúng 8 số.", "invalid_input"

        # Đợi ô đầu tiên hiện rõ
        first = netflix_page.locator("input[data-uia='pin-number-0']").first
        first.wait_for(state="visible", timeout=20000)

        # Hàm nhập chắc chắn 1 digit vào 1 ô
        def put_digit(i: int, d: str):
            sel = f"input[data-uia='pin-number-{i}']"
            box = netflix_page.locator(sel).first
            box.wait_for(state="visible", timeout=10000)

            # Click để chắc chắn focus đúng ô
            box.click(timeout=2000)

            # Clear nhẹ nhàng rồi type có delay
            try:
                box.fill("")  # clear
            except Exception:
                pass

            box.type(d, delay=80)  # delay ms, tăng/giảm tuỳ máy

            # Verify đã có giá trị đúng
            val = ""
            try:
                val = (box.input_value(timeout=1000) or "").strip()
            except Exception:
                pass
            return val == d

        # Nhập đủ 8 số, thiếu thì retry từng ô
        for i, digit in enumerate(code_str):
            ok = put_digit(i, digit)
            if not ok:
                # retry 2 lần nếu focus nhảy
                for _ in range(2):
                    ok = put_digit(i, digit)
                    if ok:
                        break
            if not ok:
                return False, f"Không nhập được số ở ô {i+1}.", "tv_code_input_failed"

        # Verify toàn bộ 8 ô
        values = []
        for i in range(8):
            sel = f"input[data-uia='pin-number-{i}']"
            v = (netflix_page.locator(sel).first.input_value(timeout=1000) or "").strip()
            values.append(v)

        joined = "".join(values)
        if joined != code_str:
            print(f" -> [DEBUG] nhập thiếu: expected={code_str} got={joined} values={values}")
            # attempt cuối: click ô 0 và type lại cả chuỗi (fallback)
            first.click()
            first.type(code_str, delay=80)
            # check lại
            values2 = []
            for i in range(8):
                sel = f"input[data-uia='pin-number-{i}']"
                v = (netflix_page.locator(sel).first.input_value(timeout=1000) or "").strip()
                values2.append(v)
            joined2 = "".join(values2)
            if joined2 != code_str:
                return False, "Không điền đủ 8 số (Netflix focus nhảy).", "tv_code_input_failed"

        print(f" -> ✅ Đã điền đủ mã {code_str}. Đang bấm Continue...")
        netflix_page.locator("button[data-uia='witcher-code-submit']").click()

        # ---- phần chờ success / bắt lỗi giữ nguyên như bạn ----
        stop_texts = {
            "that code wasn't right. try again.",
            "that code isn't right. try again.",
            "that code isnt right. try again.",
            "mã đó không đúng. hãy thử lại nào.",
        }
        skip_texts = {
            "đã xảy ra lỗi. hãy thử đăng nhập bằng điều khiển tv.",
        }

        def is_skip_text(text: str) -> bool:
            lowered_text = (text or "").strip().lower()
            if not lowered_text:
                return False
            return any(s in lowered_text for s in skip_texts)

        start_time = time.time()
        max_wait_seconds = 60
        last_message = None

        while time.time() - start_time < max_wait_seconds:
            if "/tv/out/success" in (netflix_page.url or ""):
                print(" -> ✅ KẾT QUẢ: ĐĂNG NHẬP TV THÀNH CÔNG (Url success)")
                return True, "Đăng nhập TV thành công.", None

            msg_loc = netflix_page.locator("div.nf-message-contents[data-uia='UIMessage-content']").first
            if msg_loc.count() > 0:
                raw = (msg_loc.inner_text(timeout=500) or "").strip()
                if raw and raw != last_message:
                    print(f" -> Thông báo lỗi trên trang TV: {raw}")
                    last_message = raw
                if raw:
                    lowered = raw.lower()
                    if lowered in stop_texts:
                        print(" -> ❌ Sai mã TV, dừng lại.")
                        return False, "Mã bạn nhập sai vui lòng nhập lại", "invalid_tv_code"
                    if is_skip_text(raw):
                        print(" -> ⚠️ Bỏ qua lỗi điều khiển TV, thử tài khoản khác.")
                        return False, raw, "tv_login_skip"

            title_loc = netflix_page.locator("h1.tvsignup-title[data-uia='witcher-code-title']").first
            if title_loc.count() > 0:
                raw_title = (title_loc.inner_text(timeout=500) or "").strip()
                if raw_title and raw_title != last_message:
                    print(f" -> Thông báo trạng thái TV: {raw_title}")
                    last_message = raw_title
                if is_skip_text(raw_title):
                    print(" -> ⚠️ Bỏ qua lỗi điều khiển TV, thử tài khoản khác.")
                    return False, raw_title, "tv_login_skip"

            time.sleep(1)

        print(" -> ❌ KẾT QUẢ: KHÔNG THẤY TRANG SUCCESS")
        return False, "Không thể đăng nhập TV.", "tv_login_failed"

    except Exception as e:
        print(f" -> Lỗi khi nhập mã TV: {e}")
        return False, "Không thể đăng nhập TV.", "tv_login_error"

def _login_once_pw(email: str, tv_code: str, progress: list[str] | None = None):
    def push_step(msg: str):
        if progress is not None:
            progress.append(msg)

    selected_ctv = random.choice(CTV_CODES)

    # Netflix thường ổn hơn khi headless=False, nhưng server không có X nên cần headless=True.
    headless = bool(getattr(config, "TUKI_HEADLESS", True))
    if not os.getenv("DISPLAY"):
        headless = True

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--start-maximized"],
            )

            context = browser.new_context(
                viewport=None,
                locale="vi-VN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                ),
            )

            netflix_page = context.new_page()

            # --- BƯỚC 1: NETFLIX (BẤM TIẾP TỤC -> ĐỢI OTP) ---
            push_step("Đang mở trang đăng nhập Netflix.")
            ok, message, reason = netflix_continue_wait_otp(netflix_page, email, timeout_sec=25)
            if not ok:
                push_step(f"Không thể yêu cầu mã đăng nhập: {message}")
                push_step("Không gửi được mã Netflix, sẽ chuyển sang tài khoản khác.")
                browser.close()
                return {
                    "success": False,
                    "message": message,
                    "reason": reason,
                    "email": email,
                    "steps": progress or [],
                }

            push_step("Đã hiện ô nhập mã Netflix (OTP).")

            # --- BƯỚC 2: TUKITECH ---
            push_step("Đang lấy mã đăng nhập từ Tukitech.")
            tukitech_page = context.new_page()
            tukitech_prepare_search(tukitech_page, email=email, ctv_code=selected_ctv)

            # --- BƯỚC 3: RETRY LOOP DÁN OTP ---
            print(f"[{email}] Bắt đầu quy trình...")
            push_step("Đang xác thực tài khoản trên Netflix.")
            login_web_success = False

            for attempt in range(1, MAX_RETRIES + 1):
                login_web_success = get_and_paste_code_pw(netflix_page, tukitech_page)
                if login_web_success:
                    print(f"[{email}] -> Đăng nhập Web OK.")
                    push_step("Đăng nhập web thành công.")
                    break

                if attempt < MAX_RETRIES:
                    print(f"[{email}] -> Web Login thất bại (Lần {attempt}). Thử lại sau 15s...")
                    push_step(f"Đăng nhập web thất bại, thử lại lần {attempt + 1}.")
                    time.sleep(15)

            # --- BƯỚC 4: NẾU WEB OK -> NHẬP MÃ TV ---
            if login_web_success:
                push_step("Đang nhập mã TV.")
                tv_success, tv_message, tv_reason = enter_tv_code_pw(netflix_page, tv_code)

                if tv_success:
                    push_step("Đăng nhập TV thành công.")
                else:
                    push_step(f"Đăng nhập TV thất bại: {tv_message}")

                result = {
                    "success": tv_success,
                    "message": tv_message,
                    "reason": tv_reason,
                    "email": email,
                    "steps": progress or [],
                }
                if tv_reason == "tv_login_skip":
                    push_step("Gặp lỗi đăng nhập bằng điều khiển TV, sẽ đổi sang tài khoản khác.")

                browser.close()
                return result

            push_step("Không đăng nhập web thành công, chuyển sang tài khoản khác.")
            browser.close()
            return {
                "success": False,
                "message": "Không qua được bước đăng nhập Web.",
                "reason": "web_login_failed",
                "email": email,
                "steps": progress or [],
            }

    except Exception as e:
        push_step(f"Lỗi trong quá trình xử lý: {e}")
        return {"success": False, "message": f"Lỗi với {email}: {e}", "email": email, "steps": progress or []}


def worker_process(email):
    return _login_once_pw(email=email, tv_code=TV_CODE_TO_ENTER)


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
        result = _login_once_pw(email=target_email, tv_code=code, progress=progress)
        if isinstance(result, dict):
            last_result = result
            if result.get("success"):
                return result
            if result.get("reason") == "invalid_tv_code":
                return result
            if result.get("reason") in ("tv_login_skip", "need_password", "login_failed", "web_login_failed"):
                # đổi account khác
                continue

    return {
        "success": False,
        "message": (last_result.get("message") if last_result else None) or "Không thể đăng nhập TV.",
        "email": last_result.get("email") if last_result else None,
        "steps": last_result.get("steps") if last_result else [],
    }


if __name__ == "__main__":
    tasks = [e.strip() for e in INPUT_EMAILS if e.strip()]
    with Pool(processes=MAX_CONCURRENT_PROCESSES) as pool:
        pool.map(worker_process, tasks)
