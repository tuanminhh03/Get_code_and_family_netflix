import os
import re
import time
import random
from multiprocessing import Pool

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

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


def _resolve_email(email: str | None):
    if email and email.strip():
        return email.strip()
    for item in INPUT_EMAILS:
        candidate = (item or "").strip()
        if candidate:
            return candidate
    return None


def _normalize_debugger_address(address: str) -> str:
    if not address:
        return ""
    normalized = address.strip()
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    return f"http://{normalized}"


def _add_stealth_script(context) -> None:
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        "window.chrome = window.chrome || { runtime: {} };"
        "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});"
        "Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US']});"
    )


def _launch_context(playwright):
    headless = getattr(config, "TUKI_HEADLESS", False)
    user_data_dir = (getattr(config, "TUKI_CHROME_USER_DATA_DIR", "") or "").strip()
    profile_dir = (getattr(config, "TUKI_CHROME_PROFILE_DIR", "") or "").strip()
    debugger_address = _normalize_debugger_address(config.chrome_debugger_address())

    args = [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-blink-features=AutomationControlled",
        "--log-level=3",
        "--window-size=1280,900",
    ]
    if profile_dir:
        args.append(f"--profile-directory={profile_dir}")

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    viewport = {"width": 1280, "height": 900}

    if debugger_address:
        browser = playwright.chromium.connect_over_cdp(debugger_address)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context(user_agent=user_agent, viewport=viewport)
        _add_stealth_script(context)
        return context, browser

    if user_data_dir:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            args=args,
            user_agent=user_agent,
            viewport=viewport,
        )
        _add_stealth_script(context)
        return context, None

    browser = playwright.chromium.launch(headless=headless, args=args)
    context = browser.new_context(user_agent=user_agent, viewport=viewport)
    _add_stealth_script(context)
    return context, browser


def safe_click(locator) -> None:
    try:
        locator.click()
    except PlaywrightError:
        locator.evaluate("el => el.click()")


# --- HÀM LẤY VÀ DÁN MÃ TUKITECH ---
def get_and_paste_code(netflix_page, tukitech_page):
    try:
        search_btn = tukitech_page.locator("#search-btn")
        search_btn.wait_for(state="visible")
        safe_click(search_btn)

        code_element = tukitech_page.locator("div.bg-light > span.text-dark").first
        code_text = (code_element.inner_text() or "").strip()

        if not code_text.isdigit() or len(code_text) < 4:
            return False

        code_input = netflix_page.locator("input[name='challengeOtp']")
        code_input.wait_for(state="visible")
        code_input.fill(code_text)

        try:
            netflix_page.wait_for_function(
                "() => location.href.toLowerCase().includes('browse') || "
                "location.href.toLowerCase().includes('profiles')",
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            return False

        cur = (netflix_page.url or "").lower()
        return ("browse" in cur) or ("profiles" in cur)

    except PlaywrightError:
        return False


# --- HÀM NHẬP MÃ TV (Logic mới) ---
def enter_tv_code(page, tv_code):
    try:
        print(" -> Đang truy cập trang nhập mã TV8...")
        page.goto("https://www.netflix.com/tv8")

        code_str = str(tv_code).strip()
        if len(code_str) != 8 or not code_str.isdigit():
            print(f"LỖI: Mã TV phải có đúng 8 số. Mã hiện tại: {code_str}")
            return False, "Mã TV phải có đúng 8 số.", "invalid_input"

        for i, digit in enumerate(code_str):
            input_selector = f"input[data-uia='pin-number-{i}']"
            input_field = page.locator(input_selector)
            input_field.wait_for(state="visible")
            input_field.fill(digit)
            time.sleep(0.1)

        print(f" -> Đã điền mã {code_str}. Đang bấm Continue...")

        submit_btn = page.locator("button[data-uia='witcher-code-submit']")
        submit_btn.wait_for(state="visible")
        safe_click(submit_btn)

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
            return any(skip_text in lowered_text for skip_text in skip_texts)

        start_time = time.time()
        max_wait_seconds = 60
        last_message = None

        while time.time() - start_time < max_wait_seconds:
            if "/tv/out/success" in (page.url or ""):
                print(" -> ✅ KẾT QUẢ: ĐĂNG NHẬP TV THÀNH CÔNG (Url success)")
                return True, "Đăng nhập TV thành công.", None

            error_text = _extract_netflix_message(page)
            if error_text:
                lowered = error_text.lower()
                if error_text != last_message:
                    print(f" -> Thông báo lỗi trên trang TV: {error_text}")
                    last_message = error_text

                if lowered in stop_texts:
                    print(" -> ❌ Sai mã TV, dừng lại.")
                    return False, "Mã bạn nhập sai vui lòng nhập lại", "invalid_tv_code"
                if is_skip_text(error_text):
                    print(" -> ⚠️ Bỏ qua lỗi điều khiển TV, thử tài khoản khác.")
                    return False, error_text, "tv_login_skip"

            title_locator = page.locator("h1.tvsignup-title[data-uia='witcher-code-title']")
            if title_locator.count() > 0 and title_locator.first.is_visible():
                raw_title = (title_locator.first.inner_text() or "").strip()
                lowered_title = raw_title.lower()
                if raw_title and raw_title != last_message:
                    print(f" -> Thông báo trạng thái TV: {raw_title}")
                    last_message = raw_title
                if is_skip_text(raw_title):
                    print(" -> ⚠️ Bỏ qua lỗi điều khiển TV, thử tài khoản khác.")
                    return False, raw_title, "tv_login_skip"

            time.sleep(1)

        print(" -> ❌ KẾT QUẢ: KHÔNG THẤY TRANG SUCCESS (Có thể sai mã hoặc lỗi hệ thống)")
        return False, "Không thể đăng nhập TV.", "tv_login_failed"

    except PlaywrightError as e:
        print(f" -> Lỗi khi nhập mã TV: {e}")
        return False, "Không thể đăng nhập TV.", "tv_login_error"


def worker_process(email):
    return _login_once(email=email, tv_code=TV_CODE_TO_ENTER)


def _extract_netflix_message(page):
    selectors = [
        "div.nf-message-contents[data-uia='UIMessage-content']",
        "div[data-uia='UIMessage-content']",
        "p[data-uia='UIMessage-content']",
        "span[data-uia='UIMessage-content']",
        "div[data-uia*='UIMessage']",
        "p[data-uia*='UIMessage']",
        "span[data-uia*='UIMessage']",
        "div.textWithTags",
        "div.ui-message-contents",
        "p.ui-message-contents",
        "span.ui-message-contents",
        "div.ui-message-container",
        "div[role='alert']",
        "div.alert",
        "div.alert-error",
        "div[data-uia='error-message']",
        "p[data-uia='error-message']",
        "span[data-uia='error-message']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            target = locator.first
            try:
                if target.is_visible():
                    text = (target.inner_text() or "").strip()
                    if text:
                        return text
            except PlaywrightError:
                continue
    return None


def _netflix_request_login_code_new_flow(page, email: str):
    """
    FLOW MỚI (tối ưu phát hiện nhanh):
    - Sau khi bấm Continue:
      + Chờ nhanh 8s để thấy OTP hoặc thấy password hoặc thấy message lỗi.
      + Nếu không thấy gì -> SKIP sớm, đổi tài khoản khác.
      + Nếu thấy message "vui lòng thử lại..." -> SKIP.
      + Nếu thấy password -> SKIP.
      + Nếu thấy OTP -> OK.
    """
    page.goto("https://www.netflix.com/vn/login")

    email_input = page.locator("input[name='userLoginId']")
    email_input.wait_for(state="visible")
    email_input.fill(email)

    continue_btn = page.locator("button[data-uia='continue-button']")
    continue_btn.wait_for(state="visible")
    safe_click(continue_btn)

    otp_selector = "input[name='challengeOtp']"

    skip_texts = {
        "đã xảy ra lỗi. vui lòng thử lại trong vài phút.",
        "đã xảy ra lỗi vui lòng thử lại trong vài phút",
    }

    def is_skip_text(text: str) -> bool:
        lowered_text = (text or "").strip().lower()
        if not lowered_text:
            return False
        if any(skip_text in lowered_text for skip_text in skip_texts):
            return True
        return "đã xảy ra lỗi" in lowered_text and "vui lòng thử lại" in lowered_text

    def any_visible(css: str) -> bool:
        locator = page.locator(css)
        count = locator.count()
        for i in range(min(count, 5)):
            if locator.nth(i).is_visible():
                return True
        return False

    def any_password_visible() -> bool:
        locator = page.locator("input[name='password']")
        count = locator.count()
        for i in range(min(count, 5)):
            if locator.nth(i).is_visible():
                return True
        return False

    fast_deadline = time.time() + 8

    while time.time() < fast_deadline:
        if any_visible(otp_selector):
            return True, None, None

        if any_password_visible():
            return False, "Tài khoản yêu cầu mật khẩu, không dùng được mã đăng nhập.", "login_skip"

        msg = _extract_netflix_message(page)
        if msg:
            if is_skip_text(msg):
                return False, msg, "login_skip"
            lowered = msg.lower()
            if "không tìm thấy" in lowered or "can't find" in lowered:
                return False, msg, "account_not_found"

        time.sleep(0.15)

    slow_deadline = time.time() + 6
    while time.time() < slow_deadline:
        msg = _extract_netflix_message(page)
        if msg:
            if is_skip_text(msg):
                return False, msg, "login_skip"
            lowered = msg.lower()
            if "không tìm thấy" in lowered or "can't find" in lowered:
                return False, msg, "account_not_found"
            return False, msg, "login_skip"
        time.sleep(0.25)

    return False, "Không thấy ô nhập mã sau khi bấm Tiếp tục (phát hiện nhanh), đổi tài khoản khác.", "login_skip"


def _login_once(email: str, tv_code: str, progress: list[str] | None = None):
    def push_step(message: str) -> None:
        if progress is not None:
            progress.append(message)

    with sync_playwright() as playwright:
        context = None
        browser = None
        try:
            context, browser = _launch_context(playwright)
            page = context.new_page()
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(30000)

            push_step("Đang mở trang đăng nhập Netflix.")
            login_flow_ok, login_flow_message, login_flow_reason = _netflix_request_login_code_new_flow(page, email)
            if not login_flow_ok:
                message = login_flow_message or "Không thể yêu cầu mã đăng nhập."
                push_step(f"Không thể yêu cầu mã đăng nhập: {message}")
                push_step("Không gửi được mã Netflix, sẽ chuyển sang tài khoản khác.")
                return {
                    "success": False,
                    "message": message,
                    "reason": login_flow_reason,
                    "email": email,
                    "steps": progress or [],
                }

            push_step("Đã gửi yêu cầu mã đăng nhập.")
            time.sleep(2)

            push_step("Đang lấy mã đăng nhập từ Tukitech.")
            tukitech_page = context.new_page()
            tukitech_page.set_default_timeout(15000)
            tukitech_page.set_default_navigation_timeout(30000)

            tukitech_page.goto("https://tukitech.com/user_management/customer_login/")
            tukitech_page.locator("input[placeholder='Nhập tên đăng nhập']").fill(random.choice(CTV_CODES))
            safe_click(tukitech_page.locator("//button[normalize-space()='Tiếp tục']"))

            tukitech_page.wait_for_url("https://tukitech.com/email_search/")
            tukitech_page.locator("input[placeholder='example@domain.com']").fill(email)
            tukitech_page.select_option("#condition", label="Netflix: Mã Đăng Nhập")

            print(f"[{email}] Bắt đầu quy trình...")
            push_step("Đang xác thực tài khoản trên Netflix.")
            login_web_success = False

            for attempt in range(1, MAX_RETRIES + 1):
                login_web_success = get_and_paste_code(page, tukitech_page)

                if login_web_success:
                    print(f"[{email}] -> Đăng nhập Web OK.")
                    push_step("Đăng nhập web thành công.")
                    break

                if attempt < MAX_RETRIES:
                    print(f"[{email}] -> Web Login thất bại (Lần {attempt}). Thử lại sau 15s...")
                    push_step(f"Đăng nhập web thất bại, thử lại lần {attempt + 1}.")
                    time.sleep(15)

            if login_web_success:
                push_step("Đang nhập mã TV.")
                tv_success, tv_message, tv_reason = enter_tv_code(page, tv_code)

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
                return result

            push_step("Không gửi được mã Netflix hoặc không đăng nhập web thành công, chuyển sang tài khoản khác.")
            return {
                "success": False,
                "message": "Không qua được bước đăng nhập Web.",
                "reason": "web_login_failed",
                "email": email,
                "steps": progress or [],
            }

        except PlaywrightError as e:
            push_step(f"Lỗi trong quá trình xử lý: {e}")
            return {"success": False, "message": f"Lỗi với {email}: {e}", "email": email, "steps": progress or []}

        finally:
            if context is not None:
                try:
                    context.close()
                except PlaywrightError:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except PlaywrightError:
                    pass


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
            if result.get("reason") == "tv_login_skip":
                continue
            if result.get("reason") == "login_skip":
                continue
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
