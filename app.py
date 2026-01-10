from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, or_, text, case
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta, date
from tuki_persistent import TukiPersistent
import config
import os
import re
from logintv import login_tv as run_login_tv

# Flask init
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = config.SECRET_KEY

db = SQLAlchemy(app)

TV_REMOTE_NOTE_MARKER = "[TV-REMOTE]"
TV_LOGIN_FAILURE_MARKER = "[TV-LOGIN-FAILED]"
TV_LOGIN_FAILURE_NOTE = "Không đăng nhập được TV."
TV_SEED_DISABLED_KEY = "tv_login_seed_disabled"


def _customer_table_name():
    try:
        inspector = inspect(db.engine)
        if inspector.has_table(Customer.__tablename__):
            return Customer.__tablename__
        if inspector.has_table("customers"):
            return "customers"
    except Exception:
        pass
    return Customer.__tablename__


def ensure_database():
    db.create_all()
    _ensure_email_nullable()
    _ensure_tv_allowed_column()
    _ensure_tv_login_email_notes_column()


def _ensure_email_nullable():
    table_name = _customer_table_name()
    try:
        result = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    except Exception:
        return

    email_info = next((row for row in result if row[1] == "email"), None)
    if not email_info:
        return

    # In SQLite, the `notnull` flag is stored at index 3
    if email_info[3] == 0:
        return

    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} RENAME TO {table_name}_old"))
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255),
                    phone VARCHAR(50),
                    expiry_date DATE,
                    tv_allowed BOOLEAN DEFAULT 0,
                    notes TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_email ON {table_name} (email)"))
        conn.execute(
            text(
                f"""
                INSERT INTO {table_name} (id, email, phone, expiry_date, tv_allowed, notes, created_at, updated_at)
                SELECT id, email, phone, expiry_date, 0 AS tv_allowed, notes, created_at, updated_at FROM {table_name}_old
                """
            )
        )
        conn.execute(text(f"DROP TABLE {table_name}_old"))


def _ensure_tv_allowed_column():
    table_name = _customer_table_name()
    try:
        result = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    except Exception:
        return

    has_column = any(row[1] == "tv_allowed" for row in result)
    if has_column:
        return

    try:
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN tv_allowed BOOLEAN DEFAULT 0"))
            conn.execute(text(f"UPDATE {table_name} SET tv_allowed = 0 WHERE tv_allowed IS NULL"))
    except Exception:
        print(f"[DB] Không thể thêm cột tv_allowed cho bảng {table_name}", flush=True)


def _ensure_tv_login_email_notes_column():
    try:
        result = db.session.execute(text("PRAGMA table_info(tv_login_email)")).fetchall()
    except Exception:
        return

    has_column = any(row[1] == "notes" for row in result)
    if has_column:
        return

    try:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tv_login_email ADD COLUMN notes TEXT"))
    except Exception:
        print("[DB] Không thể thêm cột notes cho bảng tv_login_email", flush=True)


def _parse_timestamp_candidates(ts_raw: str):
    if not ts_raw:
        return "", ""
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M:%S %Z", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(ts_raw, fmt)
            return ts_raw, dt.isoformat()
        except ValueError:
            continue
    return ts_raw, ""


# === DATABASE MODEL ===
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    phone = db.Column(db.String(50))
    expiry_date = db.Column(db.Date)
    tv_allowed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    @property
    def expiry_display(self):
        if not self.expiry_date:
            return "Không thiết lập"
        return self.expiry_date.strftime("%d/%m/%Y")


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, index=True)
    requester_email = db.Column(db.String(255))
    target_email = db.Column(db.String(255))
    kind = db.Column(db.String(50))
    success = db.Column(db.Boolean, default=False)
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def kind_label(self):
        mapping = {
            "login_code": "Mã đăng nhập",
            "verify_link": "Link hộ gia đình",
            "login_tv": "Đăng nhập TV",
        }
        return mapping.get(self.kind, self.kind or "Khác")


class TvLoginEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def last_used_display(self):
        if not self.last_used_at:
            return "Chưa sử dụng"
        return _format_local_time(self.last_used_at)


class AppSetting(db.Model):
    key = db.Column(db.String(120), primary_key=True)
    value = db.Column(db.Text, nullable=True)


def _get_app_setting(key: str) -> str | None:
    try:
        record = AppSetting.query.filter_by(key=key).first()
    except Exception:
        return None
    return record.value if record else None


def _set_app_setting(key: str, value: str | None) -> None:
    try:
        record = AppSetting.query.filter_by(key=key).first()
        if record:
            record.value = value
        else:
            db.session.add(AppSetting(key=key, value=value))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _evaluate_status(expiry_date: date, today: date | None = None):
    today = today or date.today()
    if not expiry_date:
        return "active"
    delta = (expiry_date - today).days
    if delta < 0:
        return "expired"
    if delta <= 3:
        return "expiring"
    return "active"


def _status_meta(status: str):
    mapping = {
        "active": {"label": "Còn hạn", "badge": "status-pill-active", "row": "status-row-active"},
        "expiring": {"label": "Sắp hết hạn", "badge": "status-pill-expiring", "row": "status-row-expiring"},
        "expired": {"label": "Đã hết hạn", "badge": "status-pill-expired", "row": "status-row-expired"},
    }
    return mapping.get(status, mapping["active"])


def _is_invalid_tv_code_message(message: str | None):
    if not message:
        return False
    lowered = message.lower()
    return "mã bạn nhập sai" in lowered or "mã đó không đúng" in lowered or "mã sai" in lowered


def _is_tv_remote_login_message(message: str | None):
    if not message:
        return False

    lowered = message.lower()
    keywords = [
        "điều khiển tv",
        "sign in using your remote",
        "sign in with your remote",
        "try using your remote",
        "hãy thử đăng nhập bằng điều khiển tv",
    ]
    return any(key in lowered for key in keywords)


def _is_tv_remote_flagged(customer: Customer | None):
    if not customer:
        return False
    notes = (customer.notes or "").lower()
    return TV_REMOTE_NOTE_MARKER.lower() in notes


def _is_tv_login_failed(customer: Customer | None):
    if not customer:
        return False
    notes = (customer.notes or "").lower()
    return TV_LOGIN_FAILURE_MARKER.lower() in notes


def _is_tv_login_failed_record(record: TvLoginEmail | None) -> bool:
    if not record:
        return False
    notes = (record.notes or "").lower()
    return TV_LOGIN_FAILURE_MARKER.lower() in notes


def _append_marker_note(existing_notes: str | None, *, marker: str, note: str = "") -> str:
    base = existing_notes or ""
    if marker.lower() in base.lower():
        return base
    appended = f"{base} | {marker}".strip(" |")
    if note:
        appended = f"{appended} - {note}"
    return appended


def _strip_tv_markers(notes: str | None) -> str:
    if not notes:
        return ""

    markers = [TV_REMOTE_NOTE_MARKER.lower(), TV_LOGIN_FAILURE_MARKER.lower()]
    filtered_parts = []
    for raw_part in notes.split("|"):
        part = raw_part.strip()
        if not part:
            continue
        lowered = part.lower()
        if any(marker in lowered for marker in markers):
            continue
        filtered_parts.append(part)

    return " | ".join(filtered_parts)


def _safe_next(target: str | None):
    if not target:
        return url_for("admin")
    if not target.startswith("/"):
        return url_for("admin")
    return target


def _normalize_email(value: str):
    return (value or "").strip().lower()


def _normalize_phone(value: str):
    return re.sub(r"\s+", "", (value or "").strip())


def _log_activity(customer_id: int | None, *, requester_email: str, target_email: str, kind: str, success: bool, message: str):
    try:
        entry = ActivityLog(
            customer_id=customer_id,
            requester_email=requester_email or "",
            target_email=target_email or "",
            kind=kind or "",
            success=bool(success),
            message=message or "",
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        print("[ActivityLog] Không thể lưu nhật ký", flush=True)


def _find_customers_by_emails(emails: list[str]):
    normalized_emails = {_normalize_email(email) for email in emails if _normalize_email(email)}
    if not normalized_emails:
        return {}
    rows = Customer.query.filter(func.lower(Customer.email).in_(normalized_emails)).all()
    return {(_normalize_email(row.email)): row for row in rows}


def _load_seed_emails():
    seed_path = os.path.join(os.getcwd(), "account.txt")
    if not os.path.exists(seed_path):
        return []
    try:
        with open(seed_path, encoding="utf-8") as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    except Exception:  # pragma: no cover - best-effort seed
        return []


def _ensure_seed_tv_account():
    """Đảm bảo luôn có ít nhất một email TV trong DB.

    - Ưu tiên các email đã tồn tại, chỉ bật tv_allowed nếu cần.
    - Nếu DB chưa có email, seed từ account.txt (dòng đầu tiên hợp lệ).
    """
    ensure_database()

    existing = (
        Customer.query.filter(
            Customer.email.isnot(None),
            Customer.email != "",
        )
        .order_by(Customer.id.asc())
        .first()
    )

    if existing and existing.tv_allowed:
        return existing

    if existing and not existing.tv_allowed:
        existing.tv_allowed = True
        db.session.commit()
        return existing

    # Seed mới từ account.txt
    seed_emails = _load_seed_emails()
    for raw in seed_emails:
        email = _normalize_email(raw)
        if not email:
            continue

        existing_email = Customer.query.filter(func.lower(Customer.email) == email).first()
        if existing_email:
            if not existing_email.tv_allowed:
                existing_email.tv_allowed = True
                db.session.commit()
            return existing_email

        customer = Customer(email=email, tv_allowed=True)
        db.session.add(customer)
        db.session.commit()
        return customer

    return None


def _pick_tv_customer(today: date | None = None):
    today = today or date.today()

    # Ưu tiên account được bật tv_allowed + còn hạn
    chosen = (
        Customer.query.filter(
            Customer.tv_allowed.is_(True),
            Customer.email.isnot(None),
            Customer.email != "",
            or_(Customer.expiry_date.is_(None), Customer.expiry_date >= today),
        )
        .order_by(func.random())
        .first()
    )
    if chosen:
        return chosen

    # Fallback: chọn bất kỳ email hợp lệ còn hạn (dù tv_allowed=False)
    return (
        Customer.query.filter(
            Customer.email.isnot(None),
            Customer.email != "",
            or_(Customer.expiry_date.is_(None), Customer.expiry_date >= today),
        )
        .order_by(func.random())
        .first()
    )


def _get_tv_candidates(limit: int = 3, today: date | None = None):
    """Trả về danh sách email có thể dùng để đăng nhập TV (ưu tiên tv_allowed)."""

    today = today or date.today()
    limit = max(1, limit or 1)
    seen = set()
    candidates: list[Customer] = []

    def _append_unique(rows):
        nonlocal candidates
        for customer in rows:
            email = _normalize_email(customer.email)
            if not email or email in seen:
                continue
            if _is_tv_remote_flagged(customer) or _is_tv_login_failed(customer):
                continue
            seen.add(email)
            candidates.append(customer)
            if len(candidates) >= limit:
                return True
        return False

    prioritized = (
        Customer.query.filter(
            Customer.tv_allowed.is_(True),
            Customer.email.isnot(None),
            Customer.email != "",
            or_(Customer.expiry_date.is_(None), Customer.expiry_date >= today),
        )
        .order_by(func.random())
        .limit(limit * 2)
        .all()
    )
    if _append_unique(prioritized):
        return candidates

    fallback = (
        Customer.query.filter(
            Customer.email.isnot(None),
            Customer.email != "",
            or_(Customer.expiry_date.is_(None), Customer.expiry_date >= today),
        )
        .order_by(func.random())
        .limit(limit * 3)
        .all()
    )
    _append_unique(fallback)
    return candidates


def _seed_tv_login_emails():
    """Đưa danh sách email trong account.txt vào bảng quay vòng nếu bảng đang trống."""
    if _get_app_setting(TV_SEED_DISABLED_KEY):
        return
    try:
        existing = TvLoginEmail.query.count()
    except Exception:
        return

    if existing:
        return

    seed_emails = _load_seed_emails()
    if not seed_emails:
        return

    added = 0
    for raw in seed_emails:
        email = _normalize_email(raw)
        if not email:
            continue
        duplicate = TvLoginEmail.query.filter(func.lower(TvLoginEmail.email) == email).first()
        if duplicate:
            continue
        db.session.add(TvLoginEmail(email=email))
        added += 1

    if added:
        db.session.commit()
    else:
        db.session.rollback()


def _pick_next_tv_login_email(explicit_email: str | None = None):
    """Chọn email tiếp theo để đăng nhập TV, quay vòng đều và tránh trùng khi chưa hết lượt."""

    ensure_database()
    _seed_tv_login_emails()

    if explicit_email:
        normalized = _normalize_email(explicit_email)
        if not normalized:
            return None
        record = TvLoginEmail.query.filter(func.lower(TvLoginEmail.email) == normalized).first()
        if not record:
            record = TvLoginEmail(email=normalized)
            db.session.add(record)
        record.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return record

    candidate = (
        TvLoginEmail.query.filter(TvLoginEmail.email.isnot(None), TvLoginEmail.email != "")
        .order_by(
            case((TvLoginEmail.last_used_at.is_(None), 0), else_=1),
            TvLoginEmail.last_used_at.asc(),
            TvLoginEmail.id.asc(),
        )
        .limit(50)
        .all()
    )

    if not candidate:
        return None

    customer_map = _find_customers_by_emails([row.email for row in candidate])
    for row in candidate:
        customer = customer_map.get(_normalize_email(row.email))
        if _is_tv_remote_flagged(customer) or _is_tv_login_failed(customer) or _is_tv_login_failed_record(row):
            continue
        row.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return row

    return None


def _list_tv_login_emails():
    ensure_database()
    _seed_tv_login_emails()
    try:
        rows = (
            TvLoginEmail.query.filter(TvLoginEmail.email.isnot(None), TvLoginEmail.email != "")
            .order_by(
                case((TvLoginEmail.last_used_at.is_(None), 0), else_=1),
                TvLoginEmail.last_used_at.asc(),
                TvLoginEmail.created_at.asc(),
            )
            .all()
        )
    except Exception:
        return []

    customer_map = _find_customers_by_emails([row.email for row in rows])

    def _tv_email_status(row: TvLoginEmail):
        customer = customer_map.get(_normalize_email(row.email))
        statuses = []
        if customer and _is_tv_remote_flagged(customer):
            statuses.append("Yêu cầu đăng nhập bằng điều khiển TV")
        if customer and _is_tv_login_failed(customer):
            statuses.append(TV_LOGIN_FAILURE_NOTE)
        if _is_tv_login_failed_record(row) and TV_LOGIN_FAILURE_NOTE not in statuses:
            statuses.append(TV_LOGIN_FAILURE_NOTE)
        return " | ".join(statuses)

    return [
        {
            "id": row.id,
            "email": row.email,
            "last_used": row.last_used_display,
            "created_at": _format_local_time(row.created_at),
            "status": _tv_email_status(row),
        }
        for row in rows
    ]


def _get_tv_login_records(limit: int | None = None, *, exclude_flagged: bool = False):
    ensure_database()
    _seed_tv_login_emails()

    try:
        query = (
            TvLoginEmail.query.filter(TvLoginEmail.email.isnot(None), TvLoginEmail.email != "")
            .order_by(
                case((TvLoginEmail.last_used_at.is_(None), 0), else_=1),
                TvLoginEmail.last_used_at.asc(),
                TvLoginEmail.created_at.asc(),
            )
        )
        if limit:
            query = query.limit(limit)
        records = query.all()
        if not exclude_flagged:
            return records
        customer_map = _find_customers_by_emails([row.email for row in records])
        filtered = []
        for row in records:
            customer = customer_map.get(_normalize_email(row.email))
            if _is_tv_remote_flagged(customer) or _is_tv_login_failed(customer) or _is_tv_login_failed_record(row):
                continue
            filtered.append(row)
        return filtered
    except Exception:
        return []


def _mark_tv_login_email_used(record: TvLoginEmail | None):
    if not record:
        return
    try:
        record.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _flag_tv_login_issue(
    email: str | None,
    *,
    marker: str,
    note: str = "",
    disable_tv_allowed: bool = True,
    remove_from_rotation: bool = True,
):
    normalized = _normalize_email(email or "")
    if not normalized:
        return

    try:
        customer = Customer.query.filter(func.lower(Customer.email) == normalized).first()
        rotation_record = TvLoginEmail.query.filter(func.lower(TvLoginEmail.email) == normalized).first()

        if customer:
            customer.notes = _append_marker_note(customer.notes, marker=marker, note=note)
            if disable_tv_allowed:
                customer.tv_allowed = False

        if rotation_record:
            rotation_record.notes = _append_marker_note(rotation_record.notes, marker=marker, note=note)
            if remove_from_rotation:
                db.session.delete(rotation_record)

        if customer or rotation_record:
            db.session.commit()
    except Exception:
        db.session.rollback()


def _flag_tv_login_failure(email: str | None):
    _flag_tv_login_issue(
        email,
        marker=TV_LOGIN_FAILURE_MARKER,
        note=TV_LOGIN_FAILURE_NOTE,
        disable_tv_allowed=True,
        remove_from_rotation=False,
    )


def _format_local_time(value: datetime, tz_offset_hours: int = 7) -> str:
    if not value:
        return ""
    try:
        if value.tzinfo:
            utc_dt = value.astimezone(timezone.utc)
        else:
            utc_dt = value.replace(tzinfo=timezone.utc)
        local_dt = utc_dt.astimezone(timezone(timedelta(hours=tz_offset_hours)))
        return local_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return value.strftime("%d/%m/%Y %H:%M")


def _login_tv(password: str, code: str, email: str | None = None):
    """Ủy quyền sang module logintv để dùng chung fallback/validation."""

    expected_password = str(getattr(config, "TV_PASSWORD", "") or os.getenv("TV_PASSWORD") or "").strip()
    if expected_password and password != expected_password:
        return {"success": False, "message": "Sai mật khẩu đăng nhập TV."}

    if not re.fullmatch(r"\d{8}", code or ""):
        return {"success": False, "message": "Mã TV phải đủ 8 số."}

    chosen_email = email
    if not chosen_email:
        record = _pick_next_tv_login_email()
        if not record:
            return {"success": False, "message": "Chưa có email nào trong danh sách đăng nhập TV."}
        chosen_email = record.email

    result = run_login_tv(password=password, code=code, email=chosen_email)

    # Đảm bảo luôn trả về dict chuẩn hóa cho luồng gọi hiện có
    if isinstance(result, dict):
        success = bool(result.get("success"))
        message = result.get("message") or ("Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.")
        remote_required = bool(result.get("remote_login_required")) or _is_tv_remote_login_message(message)
        if remote_required:
            _flag_tv_login_issue(
                chosen_email,
                marker=TV_REMOTE_NOTE_MARKER,
                note="Yêu cầu đăng nhập bằng điều khiển TV.",
                disable_tv_allowed=True,
                remove_from_rotation=True,
            )
        normalized = {
            "success": success,
            "message": message,
            "raw": result.get("raw"),
            "email": chosen_email,
            "remote_login_required": remote_required,
        }
        # Giữ lại bất kỳ thông tin phụ khác từ backend
        for key, value in result.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    if isinstance(result, (tuple, list)) and result:
        success = bool(result[0])
        message = str(result[1]) if len(result) > 1 else ("Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.")
        remote_required = _is_tv_remote_login_message(message)
        if remote_required:
            _flag_tv_login_issue(
                chosen_email,
                marker=TV_REMOTE_NOTE_MARKER,
                note="Yêu cầu đăng nhập bằng điều khiển TV.",
                disable_tv_allowed=True,
                remove_from_rotation=True,
            )
        return {
            "success": success,
            "message": message,
            "raw": result,
            "email": chosen_email,
            "remote_login_required": remote_required,
        }

    success = bool(result)
    message = "Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại."
    remote_required = _is_tv_remote_login_message(message)
    if remote_required:
        _flag_tv_login_issue(
            chosen_email,
            marker=TV_REMOTE_NOTE_MARKER,
            note="Yêu cầu đăng nhập bằng điều khiển TV.",
            disable_tv_allowed=True,
            remove_from_rotation=True,
        )
    return {
        "success": success,
        "message": message,
        "raw": result,
        "email": chosen_email,
        "remote_login_required": remote_required,
    }


# === WORKER (KEEP CHROME ALIVE) ===
_worker = None

def ensure_worker():
    global _worker
    if _worker is None:
        headless = getattr(config, "TUKI_HEADLESS", True)
        print(f"⚙️  Khởi tạo phiên Tukitech ... (headless={headless})")
        _worker = TukiPersistent(headless=headless)
    return _worker


# === ROUTES ===
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/tv')
def tv_page():
    ensure_database()
    _ensure_seed_tv_account()
    return render_template('tv.html')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    error = None
    if not session.get('is_admin'):
        if request.method == 'POST':
            password = request.form.get('password', '')
            if password == config.ADMIN_PASSWORD:
                session['is_admin'] = True
                return redirect(url_for('admin'))
            error = "Sai mật khẩu, vui lòng thử lại."
        return render_template('admin.html', error=error)

    ensure_database()

    today = date.today()

    search = (request.args.get('q') or '').strip()
    status_filter = request.args.get('status', 'all')

    # Pre-compute how many emails are associated with each phone number so that the
    # UI can highlight potential abuse cases (many emails mapped to one phone).
    phone_email_counts: dict[str, int] = {}
    email_usage_rows = (
        db.session.query(Customer.phone, func.count(Customer.id))
        .filter(Customer.email.isnot(None), Customer.email != "")
        .group_by(Customer.phone)
        .all()
    )
    for phone_value, count in email_usage_rows:
        normalized_phone = _normalize_phone(phone_value)
        if not normalized_phone:
            continue
        phone_email_counts[normalized_phone] = count

    query = Customer.query
    if search:
        like_term = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(Customer.email).like(like_term),
                func.lower(Customer.phone).like(like_term),
                func.lower(Customer.notes).like(like_term),
            )
        )

    customers = query.order_by(Customer.expiry_date.is_(None), Customer.expiry_date, Customer.email).all()

    total_customers = 0
    counts = {"active": 0, "expiring": 0, "expired": 0}
    customers_view = []
    emails_view = []

    for customer in customers:
        status = _evaluate_status(customer.expiry_date, today)
        counts[status] += 1
        total_customers += 1

        meta = _status_meta(status)
        stripped_notes = _strip_tv_markers(customer.notes)
        days_remaining = None
        if customer.expiry_date:
            days_remaining = (customer.expiry_date - today).days

        normalized_phone = _normalize_phone(customer.phone)
        email_usage_count = phone_email_counts.get(normalized_phone, 0)

        if status_filter != 'all' and status != status_filter:
            continue

        if customer.email:
            emails_view.append(
                {
                    "id": customer.id,
                    "email": customer.email,
                    "phone": customer.phone or "",
                    "expiry_display": customer.expiry_display,
                    "status_label": meta["label"],
                    "status_badge": meta["badge"],
                    "tv_allowed": bool(customer.tv_allowed),
                    "notes": stripped_notes,
                    "created_at": customer.created_at.strftime("%d/%m/%Y %H:%M"),
                    "updated_at": customer.updated_at.strftime("%d/%m/%Y %H:%M") if customer.updated_at else "",
                }
            )

        if not normalized_phone:
            continue

        customers_view.append(
            {
                "id": customer.id,
                "email": customer.email or "",
                "phone": customer.phone or "",
                "expiry_display": customer.expiry_display,
                "expiry_value": customer.expiry_date.strftime("%Y-%m-%d") if customer.expiry_date else "",
                "status": status,
                "status_label": meta["label"],
                "status_badge": meta["badge"],
                "row_class": meta["row"],
                "tv_allowed": bool(customer.tv_allowed),
                "notes": stripped_notes,
                "created_at": customer.created_at.strftime("%d/%m/%Y %H:%M"),
                "updated_at": customer.updated_at.strftime("%d/%m/%Y %H:%M") if customer.updated_at else "",
                "days_remaining": days_remaining,
                "phone_email_count": email_usage_count,
                "has_multiple_emails": email_usage_count > 1,
            }
        )

    active_customers = counts['active']
    expiring_customers = counts['expiring']
    expired_customers = counts['expired']

    recent_threshold = datetime.now(timezone.utc) - timedelta(days=30)
    recent_updates = Customer.query.filter(Customer.updated_at >= recent_threshold).count()
    renewal_rate = 0
    if total_customers:
        renewal_rate = round((recent_updates / total_customers) * 100, 1)

    stats = {
        "total": total_customers,
        "active": active_customers,
        "expiring": expiring_customers,
        "expired": expired_customers,
        "renewal_rate": renewal_rate,
    }

    # Lấy nhật ký hoạt động gần đây (tối đa 100 bản ghi)
    recent_logs = (
        ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()
    )
    log_customer_ids = [log.customer_id for log in recent_logs if log.customer_id]
    phone_map = {}
    if log_customer_ids:
        related_customers = Customer.query.filter(Customer.id.in_(log_customer_ids)).all()
        phone_map = {c.id: c.phone for c in related_customers}

    recent_activities = [
        {
            "id": log.id,
            "phone": phone_map.get(log.customer_id, "—"),
            "requester": log.requester_email or "—",
            "target": log.target_email or "—",
            "kind": log.kind_label,
            "success": log.success,
            "message": log.message or ("Thành công" if log.success else "Thất bại"),
            "created_at": _format_local_time(log.created_at),

        }
        for log in recent_logs
    ]

    next_url = request.full_path.rstrip('?')
    tv_login_emails = _list_tv_login_emails()

    return render_template(
        'admin.html',
        customers=customers_view,
        emails=emails_view,
        stats=stats,
        search=search,
        status_filter=status_filter,
        recent_activities=recent_activities,
        next_url=next_url,
        tv_emails=tv_login_emails,
    )


@app.route('/api/login-tv', methods=['POST'])
def api_login_tv():
    if not session.get('is_admin'):
        return jsonify({"success": False, "message": "Chưa đăng nhập admin."}), 403

    payload = request.get_json(silent=True) or {}
    password = (payload.get('password') or '').strip()
    code = (payload.get('code') or '').strip()

    if not re.fullmatch(r"\d{8}", code or ""):
        return jsonify({"success": False, "message": "Mã TV phải đủ 8 số."}), 400

    login_records = _get_tv_login_records(exclude_flagged=True)
    if not login_records:
        return jsonify({"success": False, "message": "Chưa có email nào trong danh sách đăng nhập TV."}), 503

    attempts = []
    final_success = False
    final_message = "Không thể đăng nhập TV."
    final_email = None
    final_raw = None
    status_code = 400
    invalid_code_seen = False

    for record in login_records:
        result = _login_tv(password=password, code=code, email=record.email)
        final_raw = result
        if isinstance(result, dict):
            success = bool(result.get("success"))
            message = result.get("message") or ("Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.")
        else:
            success = bool(result)
            message = "Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại."

        password_error = "mật khẩu" in message.lower()
        invalid_code = _is_invalid_tv_code_message(message)
        remote_required = bool(result.get("remote_login_required")) or _is_tv_remote_login_message(message)

        if remote_required:
            final_message = "Email yêu cầu đăng nhập bằng điều khiển TV, đã ghi chú và bỏ qua email này."
            attempts.append({"email": record.email, "success": False, "message": final_message})
            continue

        if not success and not invalid_code and not password_error:
            attempts.append({"email": record.email, "success": False, "message": "Mail không log được TV"})
            _flag_tv_login_failure(record.email)
            continue

        attempts.append({"email": record.email, "success": success, "message": message})

        if success:
            final_success = True
            final_email = record.email
            final_message = f"Đăng nhập thành công bằng email {record.email}."
            status_code = 200
            _mark_tv_login_email_used(record)
            break

        if password_error:
            final_email = record.email
            final_message = message
            status_code = 403
            break

        if invalid_code:
            invalid_code_seen = True
            final_email = record.email
            final_message = "Mã bạn nhập sai vui lòng nhập lại."
            status_code = 400
            break

        _mark_tv_login_email_used(record)

    if not final_email and attempts:
        final_email = attempts[-1]["email"]

    if not final_success and status_code == 400 and not invalid_code_seen:
        final_message = final_message or "Không thể đăng nhập TV với các email hiện tại."


    response_payload = {
        "success": final_success,
        "message": final_message,
        "email": final_email,
        "raw": final_raw,
        "attempts": attempts,
        "pool": _list_tv_login_emails(),
    }

    return jsonify(response_payload), status_code



@app.route('/api/tv-login', methods=['POST'])
def api_tv_login():
    ensure_database()
    _ensure_seed_tv_account()


    payload = request.get_json(silent=True) or {}
    password = (payload.get('password') or '').strip()
    code = (payload.get('code') or '').strip()

    if not password:
        return jsonify({"success": False, "message": "Vui lòng nhập mật khẩu đăng nhập TV."}), 400
    if not re.fullmatch(r"\d{8}", code):
        return jsonify({"success": False, "message": "Mã TV phải đủ 8 số."}), 400

    candidates = _get_tv_candidates(limit=3)
    if not candidates:
        return jsonify({"success": False, "message": "Hiện chưa có email nào được cấp quyền đăng nhập TV."}), 503

    attempts = []
    final_email = None
    final_message = "Mã sai, vui lòng nhập lại."
    final_raw = None
    status_code = 400
    remote_error_seen = False

    for idx, customer in enumerate(candidates, start=1):
        status = _evaluate_status(customer.expiry_date)
        if status == 'expired':
            attempts.append(
                {"email": customer.email, "success": False, "message": "Gói đã hết hạn, vui lòng liên hệ admin để gia hạn."}
            )
            _log_activity(
                customer.id,
                requester_email="auto",
                target_email=customer.email,
                kind="login_tv",
                success=False,
                message=f"[Lần {idx}] Gói đã hết hạn, bỏ qua.",
            )
            continue

        result = _login_tv(password=password, code=code, email=customer.email)
        if isinstance(result, dict):
            success = bool(result.get("success"))
            message = result.get("message") or ("Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại.")
        else:
            success = bool(result)
            message = "Đăng nhập thành công." if success else "Mã sai, vui lòng nhập lại."

        invalid_code = _is_invalid_tv_code_message(message)
        remote_required = bool(result.get("remote_login_required")) or _is_tv_remote_login_message(message)
        attempt_message = (
            "Email yêu cầu đăng nhập bằng điều khiển TV, đã ghi chú và bỏ qua email này." if remote_required else message
        )
        attempts.append({"email": customer.email, "success": success, "message": attempt_message})
        final_raw = result

        if not success and not invalid_code and not remote_required and "mật khẩu" not in message.lower():
            _flag_tv_login_failure(customer.email)

        _log_activity(
            customer.id,
            requester_email="auto",
            target_email=customer.email,
            kind="login_tv",
            success=success,
            message=f"[Lần {idx}] {attempt_message}",
        )

        if remote_required:
            status_code = 400
            final_message = attempt_message
            remote_error_seen = True
            continue

        if success:
            final_email = customer.email
            final_message = f"Đăng nhập thành công bằng email {customer.email}."
            status_code = 200
            break

        if "mật khẩu" in message.lower():
            status_code = 403
            final_message = message
            break

        if invalid_code:
            status_code = 400
            final_email = customer.email
            final_message = "Mã bạn nhập sai vui lòng nhập lại."
            break

    if status_code != 200:
        attempts_text = "; ".join(
            f"{item['email']} -> {'Thành công' if item['success'] else item['message']}" for item in attempts
        )
        final_message = (
            final_message
            if "mật khẩu" in final_message.lower() or _is_invalid_tv_code_message(final_message) or remote_error_seen
            else f"Không thể đăng nhập TV. Đã thử: {attempts_text}"
        )

    if not final_email and attempts:
        final_email = attempts[-1]["email"]

    return (
        jsonify(
            {
                "success": status_code == 200,
                "message": final_message,
                "email": final_email,
                "attempted_emails": [item["email"] for item in attempts],
                "raw": final_raw,
            }
        ),
        status_code,
    )


@app.route('/admin/activity/<int:customer_id>')
def admin_activity(customer_id: int):
    if not session.get('is_admin'):
        return jsonify({"success": False, "message": "Chưa đăng nhập."}), 403

    ensure_database()

    logs = (
        ActivityLog.query.filter(ActivityLog.customer_id == customer_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(100)
        .all()
    )
    payload = [
        {
            "id": log.id,
            "requester_email": log.requester_email,
            "target_email": log.target_email,
            "kind": log.kind_label,
            "raw_kind": log.kind,
            "success": log.success,
            "message": log.message,
            "created_at": _format_local_time(log.created_at),
        }
        for log in logs
    ]

    return jsonify({"success": True, "logs": payload})


@app.route('/admin/manage', methods=['POST'])
def admin_manage():
    if not session.get('is_admin'):
        flash('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('admin'))

    ensure_database()

    action = request.form.get('action')
    next_url = _safe_next(request.form.get('next'))

    if action == 'create':
        email_raw = request.form.get('email')
        email = _normalize_email(email_raw)
        phone = (request.form.get('phone') or '').strip()
        expiry = _parse_date(request.form.get('expiry'))
        tv_allowed = bool(request.form.get('tv_allowed'))
        notes = (request.form.get('notes') or '').strip()

        if not phone:
            flash('Số điện thoại không được để trống.', 'danger')
            return redirect(next_url)

        email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if email:
            if not re.match(email_pattern, email):
                flash('Email không hợp lệ.', 'danger')
                return redirect(next_url)

            exists = Customer.query.filter(func.lower(Customer.email) == email).first()
            if exists:
                flash('Email đã tồn tại trong hệ thống.', 'danger')
                return redirect(next_url)

        customer = Customer(
            email=email or None,
            phone=phone,
            expiry_date=expiry,
            tv_allowed=tv_allowed,
            notes=notes,
        )
        db.session.add(customer)
        db.session.commit()
        flash('Thêm khách hàng thành công.', 'success')
        return redirect(next_url)

    if action == 'update':
        try:
            customer_id = int(request.form.get('customer_id'))
        except (TypeError, ValueError):
            flash('Không tìm thấy khách hàng cần cập nhật.', 'danger')
            return redirect(next_url)

        customer = Customer.query.get(customer_id)
        if not customer:
            flash('Khách hàng không tồn tại.', 'danger')
            return redirect(next_url)

        email_raw = request.form.get('email')
        email = _normalize_email(email_raw)
        phone = (request.form.get('phone') or '').strip()
        expiry = _parse_date(request.form.get('expiry'))
        tv_allowed = bool(request.form.get('tv_allowed'))
        notes = (request.form.get('notes') or '').strip()

        email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if email:
            if not re.match(email_pattern, email):
                flash('Email không hợp lệ.', 'danger')
                return redirect(next_url)

            duplicate = (
                Customer.query.filter(func.lower(Customer.email) == email, Customer.id != customer.id)
                .first()
            )
            if duplicate:
                flash('Email đã được sử dụng cho khách hàng khác.', 'danger')
                return redirect(next_url)

        customer.email = email or None
        customer.phone = phone
        customer.expiry_date = expiry
        customer.tv_allowed = tv_allowed
        customer.notes = notes
        try:
            db.session.commit()
            flash('Cập nhật khách hàng thành công.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Không thể cập nhật khách hàng, vui lòng thử lại.', 'danger')
        return redirect(next_url)

    if action == 'delete':
        try:
            customer_id = int(request.form.get('customer_id'))
        except (TypeError, ValueError):
            flash('Không xác định được khách hàng cần xóa.', 'danger')
            return redirect(next_url)

        customer = Customer.query.get(customer_id)
        if not customer:
            flash('Khách hàng không tồn tại.', 'danger')
            return redirect(next_url)

        db.session.delete(customer)
        db.session.commit()
        flash('Đã xóa khách hàng.', 'success')
        return redirect(next_url)

    if action == 'bulk_delete':
        raw_ids = request.form.getlist('customer_ids')
        try:
            ids = [int(val) for val in raw_ids]
        except (TypeError, ValueError):
            ids = []

        if not ids:
            flash('Vui lòng chọn ít nhất một email để xóa.', 'warning')
            return redirect(next_url)

        customers_to_delete = Customer.query.filter(Customer.id.in_(ids)).all()
        if not customers_to_delete:
            flash('Không tìm thấy email cần xóa.', 'warning')
            return redirect(next_url)

        for customer in customers_to_delete:
            db.session.delete(customer)

        db.session.commit()
        flash(f'Đã xóa {len(customers_to_delete)} email.', 'success')
        return redirect(next_url)

    flash('Hành động không hợp lệ.', 'danger')
    return redirect(next_url)


@app.route('/admin/tv-emails', methods=['POST'])
def admin_tv_emails():
    if not session.get('is_admin'):
        flash('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('admin'))

    ensure_database()
    action = request.form.get('action')
    next_url = _safe_next(request.form.get('next'))

    if action == 'add':
        raw_email = request.form.get('email')
        email = _normalize_email(raw_email)
        if not email:
            flash('Vui lòng nhập email để đăng nhập TV.', 'danger')
            return redirect(next_url)

        email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(email_pattern, email):
            flash('Email không hợp lệ.', 'danger')
            return redirect(next_url)

        exists = TvLoginEmail.query.filter(func.lower(TvLoginEmail.email) == email).first()
        if exists:
            flash('Email đã tồn tại trong danh sách quay vòng.', 'warning')
            return redirect(next_url)

        db.session.add(TvLoginEmail(email=email))
        db.session.commit()
        flash('Đã thêm email vào danh sách đăng nhập TV.', 'success')
        return redirect(next_url)

    if action == 'delete':
        try:
            email_id = int(request.form.get('email_id'))
        except (TypeError, ValueError):
            flash('Không xác định được email cần xóa.', 'danger')
            return redirect(next_url)

        record = TvLoginEmail.query.get(email_id)
        if not record:
            flash('Email không tồn tại.', 'warning')
            return redirect(next_url)

        db.session.delete(record)
        db.session.commit()
        flash('Đã xóa email khỏi danh sách đăng nhập TV.', 'success')
        return redirect(next_url)

    if action == 'bulk_delete':
        raw_ids = request.form.getlist('email_ids')
        try:
            ids = [int(val) for val in raw_ids]
        except (TypeError, ValueError):
            ids = []

        if not ids:
            flash('Vui lòng chọn ít nhất một email để xóa.', 'warning')
            return redirect(next_url)

        records = TvLoginEmail.query.filter(TvLoginEmail.id.in_(ids)).all()
        if not records:
            flash('Không tìm thấy email cần xóa.', 'warning')
            return redirect(next_url)

        for record in records:
            db.session.delete(record)

        db.session.commit()
        flash(f'Đã xóa {len(records)} email đăng nhập TV.', 'success')
        return redirect(next_url)

    if action == 'delete_all':
        total = TvLoginEmail.query.count()
        if total == 0:
            flash('Danh sách email đăng nhập TV đang trống.', 'warning')
            return redirect(next_url)

        TvLoginEmail.query.delete(synchronize_session=False)
        db.session.commit()

        # Nếu xoá toàn bộ thì tắt seed từ account.txt để danh sách không tự add lại
        _set_app_setting(TV_SEED_DISABLED_KEY, "1")

        flash(f'Đã xóa toàn bộ {total} email đăng nhập TV.', 'success')
        return redirect(next_url)


    if action == 'import':
        file = request.files.get('email_file')
        if not file or not file.filename:
            flash('Vui lòng chọn tệp .txt để import.', 'danger')
            return redirect(next_url)

        try:
            content = file.read().decode('utf-8')
        except UnicodeDecodeError:
            flash('Tệp phải sử dụng mã hóa UTF-8.', 'danger')
            return redirect(next_url)

        email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        added = 0
        skipped = 0
        invalid = 0
        seen = set()

        for line in content.splitlines():
            candidate = _normalize_email(line)
            if not candidate or candidate in seen:
                if candidate:
                    skipped += 1
                continue

            seen.add(candidate)

            if not email_pattern.match(candidate):
                invalid += 1
                continue

            exists = TvLoginEmail.query.filter(func.lower(TvLoginEmail.email) == candidate).first()
            if exists:
                skipped += 1
                continue

            db.session.add(TvLoginEmail(email=candidate))
            added += 1

        if added:
            db.session.commit()
        else:
            db.session.rollback()

        message_parts = []
        if added:
            message_parts.append(f'thêm {added} email mới')
        if skipped:
            message_parts.append(f'bỏ qua {skipped} email trùng')
        if invalid:
            message_parts.append(f'{invalid} dòng không hợp lệ')

        summary = '; '.join(message_parts) if message_parts else 'Không có email hợp lệ để import.'
        flash(f'Import email đăng nhập TV hoàn tất: {summary}.', 'info' if added else 'warning')
        return redirect(next_url)

    flash('Hành động không hợp lệ.', 'danger')
    return redirect(next_url)


@app.route('/admin/import', methods=['POST'])
def admin_import():
    if not session.get('is_admin'):
        flash('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('admin'))

    ensure_database()

    next_url = _safe_next(request.form.get('next'))
    file = request.files.get('email_file')

    if not file or not file.filename:
        flash('Vui lòng chọn tệp .txt để import.', 'danger')
        return redirect(next_url)

    try:
        content = file.read().decode('utf-8')
    except UnicodeDecodeError:
        flash('Tệp phải sử dụng mã hóa UTF-8.', 'danger')
        return redirect(next_url)

    email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    added = 0
    skipped = 0
    invalid = 0
    seen = set()

    for line in content.splitlines():
        candidate = _normalize_email(line)
        if not candidate or candidate in seen:
            if candidate:
                skipped += 1
            continue

        seen.add(candidate)

        if not email_pattern.match(candidate):
            invalid += 1
            continue

        exists = Customer.query.filter(func.lower(Customer.email) == candidate).first()
        if exists:
            skipped += 1
            continue

        customer = Customer(email=candidate)
        db.session.add(customer)
        added += 1

    if added:
        db.session.commit()
    else:
        db.session.rollback()

    message_parts = []
    if added:
        message_parts.append(f'thêm {added} email mới')
    if skipped:
        message_parts.append(f'bỏ qua {skipped} email trùng')
    if invalid:
        message_parts.append(f'{invalid} dòng không hợp lệ')

    summary = '; '.join(message_parts) if message_parts else 'Không có email hợp lệ để import.'
    flash(f'Import hoàn tất: {summary}.', 'info' if added else 'warning')

    return redirect(next_url)


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    flash('Đã đăng xuất khỏi phiên quản trị.', 'info')
    return redirect(url_for('admin'))


# === API ===
@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    try:
        data = request.form if request.form else request.json

        # Support optional target_email; default to the same as requester
        email_raw = (data or {}).get('email', '')
        target_email_raw = (data or {}).get('target_email', '')
        kind = (data or {}).get('kind', 'login_code')
        phone_raw = (data or {}).get('password', '')

        email = _normalize_email(email_raw)
        target_email = _normalize_email(target_email_raw) or email
        phone = _normalize_phone(phone_raw)

        def log_attempt(*, customer_id: int | None, success: bool, message: str):
            _log_activity(
                customer_id,
                requester_email=email,
                target_email=target_email,
                kind=kind,
                success=success,
                message=message,
            )

        # The email actually used by the worker to fetch. If target provided, use it; else requester
        fetch_email = (target_email_raw or email_raw or '').strip()

        if not email:
            return jsonify({"success": False, "message": "Thiếu email"}), 400
        if kind not in ("login_code", "verify_link"):
            return jsonify({"success": False, "message": f"kind không hợp lệ: {kind}"}), 400

        PHONE_NOT_ALLOWED_MSG = (
            "Số điện thoại hết hạn hoặc chưa được đăng kí, vui lòng liên hệ với seller để được gia hạn"
        )

        if not phone:
            return jsonify({"success": False, "message": PHONE_NOT_ALLOWED_MSG}), 403

        ensure_database()

        phone_holder = Customer.query.filter(func.lower(Customer.phone) == phone.lower()).first()
        if not phone_holder:
            log_attempt(customer_id=None, success=False, message="Số điện thoại không hợp lệ")
            return jsonify({"success": False, "message": PHONE_NOT_ALLOWED_MSG}), 403

        phone_status = _evaluate_status(phone_holder.expiry_date)
        if phone_status == 'expired':
            log_attempt(customer_id=phone_holder.id, success=False, message="Số điện thoại hết hạn")
            return jsonify({"success": False, "message": PHONE_NOT_ALLOWED_MSG}), 403

        # Validate requester
        requester = Customer.query.filter(func.lower(Customer.email) == email).first()
        if not requester:
            log_attempt(customer_id=phone_holder.id, success=False, message="Email requester không hợp lệ")
            return jsonify({"success": False, "message": "Email không hợp lệ hoặc chưa được cấp quyền, vui lòng liên hệ admin."}), 403

        status = _evaluate_status(requester.expiry_date)
        if status == 'expired':
            log_attempt(customer_id=phone_holder.id, success=False, message="Gói requester hết hạn")
            return jsonify({"success": False, "message": "Gói Netflix của bạn đã hết hạn, vui lòng liên hệ admin để được gia hạn."}), 403

        # Validate target (can be the same as requester)
        target = Customer.query.filter(func.lower(Customer.email) == target_email).first()
        if not target:
            log_attempt(customer_id=phone_holder.id, success=False, message="Email đích không tồn tại")
            return jsonify({"success": False, "message": "Email đích không tồn tại trong hệ thống."}), 404

        target_status = _evaluate_status(target.expiry_date)
        if target_status == 'expired':
            log_attempt(customer_id=phone_holder.id, success=False, message="Email đích hết hạn")
            return jsonify({"success": False, "message": "Email đích đã hết hạn, vui lòng liên hệ admin."}), 403

        try:
            worker = ensure_worker()
        except Exception as exc:
            log_attempt(customer_id=phone_holder.id, success=False, message=f"Không khởi tạo được worker: {exc}")
            return jsonify({"success": False, "message": "Hệ thống đang bận, vui lòng thử lại sau ít phút."}), 503
        print(f"[API] yêu cầu: kind={kind} email={fetch_email}")
        result = worker.fetch(email=fetch_email, kind=kind)
        print(f"[API] trả về: {result}")

        # chuẩn bị thời gian dự phòng từ server (giờ địa phương của server)
        server_now = datetime.now(timezone.utc).astimezone()
        fallback_raw = server_now.strftime("%a, %d %b %Y %H:%M:%S %Z")
        fallback_iso = server_now.isoformat()

        code = ""
        content = ""
        timestamp_raw = ""
        timestamp_iso = ""
        verify_link = ""

        if isinstance(result, dict):
            if result.get("success") is False:
                message = result.get("message") or "Phản hồi không thành công từ worker"
                log_attempt(customer_id=phone_holder.id, success=False, message=message)
                return jsonify({"success": False, "message": message}), 502

            code = (result.get("code") or result.get("result") or "").strip()
            content = result.get("content") or ""
            timestamp_raw = result.get("received_at_raw") or result.get("timestamp") or ""
            timestamp_iso = result.get("received_at") or result.get("timestamp_iso") or ""
            verify_link = result.get("verify_link") or result.get("link") or ""

        elif isinstance(result, str):
            code_match = re.search(r"(\d{3,6})", result)
            time_match = re.search(r"\w{3},\s\d{1,2}\s\w{3}\s\d{4}\s[\d:]+(?:\s\w+)?", result)
            code = code_match.group(1) if code_match else ""
            timestamp_raw = time_match.group(0) if time_match else ""
            content = result

        timestamp_raw, parsed_iso = _parse_timestamp_candidates(timestamp_raw)
        if parsed_iso and not timestamp_iso:
            timestamp_iso = parsed_iso

        if not timestamp_raw and timestamp_iso:
            timestamp_raw = timestamp_iso

        if not timestamp_raw and not timestamp_iso:
            timestamp_raw = fallback_raw
            timestamp_iso = fallback_iso

        response_payload = {
            "success": True,
            "code": code,
            "content": content,
            "verify_link": verify_link,
            "received_at_raw": timestamp_raw,
            "received_at": timestamp_iso,
            "timestamp_raw": timestamp_raw,
            "timestamp_iso": timestamp_iso,
            "timestamp": timestamp_raw,
            "server_time_raw": fallback_raw,
            "server_time_iso": fallback_iso,
            "requester_email": requester.email,
            "target_email": target.email,
        }

        log_attempt(customer_id=phone_holder.id, success=True, message="Thành công")

        return jsonify(response_payload)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Lỗi server: {e}"}), 500


# === INIT DB ===
@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("✅ Database khởi tạo thành công")


import sys

if __name__ == '__main__':
    if '--init-db' in sys.argv:
        with app.app_context():
            db.create_all()
            print('✅ DB created/ready')
        # ❌ KHÔNG gọi ensure_worker() ở đây
    else:
        warmup = str(os.getenv("TUKI_WARMUP", "0")).strip().lower() in {"1", "true", "yes", "y", "on"}
        if warmup:
            try:
                ensure_worker()  # ✅ Chỉ warm-up khi chạy server thật (khi bật TUKI_WARMUP)
            except Exception as exc:
                print(f"⚠️ Không thể khởi tạo worker tự động: {exc}. Worker sẽ khởi tạo khi có request.", flush=True)
        else:
            print("ℹ️ Bỏ qua warm-up TukiPersistent (TUKI_WARMUP=0). Worker sẽ khởi tạo khi có request đầu tiên.", flush=True)

        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
