"""Lightweight wrapper để đăng nhập TV.

Module này cố gắng sử dụng backend (nếu có) từ tệp `LOGINTV.py` để
thực hiện thao tác đăng nhập TV thực sự. Nếu không tìm thấy backend, nó
trả về kết quả giả lập để UI có thể hiển thị luồng trạng thái.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable

LoginTVResult = dict[str, Any]


def _resolve_backend() -> Callable[[str, str], Any] | None:
    """Tìm kiếm hàm backend trong LOGINTV.py (nếu được cung cấp)."""

    try:
        backend = importlib.import_module("LOGINTV")
    except Exception:
        return None

    for name in ("login_tv", "loginTV", "run", "execute"):
        func = getattr(backend, name, None)
        if callable(func):
            return func
    return None


def login_tv(password: str, code: str) -> LoginTVResult:
    """Thực hiện (hoặc giả lập) đăng nhập TV.

    Returns a dictionary with at least:
        success (bool): trạng thái đăng nhập.
        message (str): thông báo cho người dùng.
    """

    password = (password or "").strip()
    code = (code or "").strip()

    if not password:
        return {"success": False, "message": "Mật khẩu không được để trống."}

    if not re.fullmatch(r"\d{8}", code):
        return {"success": False, "message": "Mã TV phải đủ 8 số."}

    backend_func = _resolve_backend()

    if backend_func:
        try:
            response = backend_func(password=password, code=code)
            if isinstance(response, dict):
                success = bool(response.get("success"))
                message = response.get("message") or (
                    "Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại."
                )
                return {"success": success, "message": message, "raw": response}

            # Hỗ trợ backend trả về tuple/list (success, message)
            if isinstance(response, (tuple, list)) and response:
                success = bool(response[0])
                message = (
                    str(response[1])
                    if len(response) > 1
                    else ("Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.")
                )
                return {"success": success, "message": message, "raw": response}

            success = bool(response)
            return {
                "success": success,
                "message": "Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.",
                "raw": response,
            }
        except Exception as exc:  # pragma: no cover - bảo vệ backend người dùng
            return {"success": False, "message": f"Lỗi khi đăng nhập TV: {exc}"}

    # Fallback giả lập để UI có thể hoạt động ngay cả khi backend chưa sẵn sàng
    return {
        "success": True,
        "message": "Đăng nhập TV giả lập thành công (chưa kết nối backend LOGINTV).",
        "raw": None,
    }

