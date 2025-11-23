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
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta, date
from tuki_persistent import TukiPersistent
import config
import re

# Flask init
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = config.SECRET_KEY

db = SQLAlchemy(app)


def ensure_database():
    db.create_all()
    _ensure_email_nullable()


def _ensure_email_nullable():
    try:
        result = db.session.execute(text("PRAGMA table_info(customers)")).fetchall()
    except Exception:
        return

    email_info = next((row for row in result if row[1] == "email"), None)
    if not email_info:
        return

    # In SQLite, the `notnull` flag is stored at index 3
    if email_info[3] == 0:
        return

    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE customers RENAME TO customers_old"))
        conn.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255),
                    phone VARCHAR(50),
                    expiry_date DATE,
                    notes TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_email ON customers (email)"))
        conn.execute(
            text(
                """
                INSERT INTO customers (id, email, phone, expiry_date, notes, created_at, updated_at)
                SELECT id, email, phone, expiry_date, notes, created_at, updated_at FROM customers_old
                """
            )
        )
        conn.execute(text("DROP TABLE customers_old"))


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
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def expiry_display(self):
        if not self.expiry_date:
            return "Không thiết lập"
        return self.expiry_date.strftime("%d/%m/%Y")


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
                    "notes": customer.notes or "",
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
                "notes": customer.notes or "",
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

    recent_threshold = datetime.utcnow() - timedelta(days=30)
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

    next_url = request.full_path.rstrip('?')

    return render_template(
        'admin.html',
        customers=customers_view,
        emails=emails_view,
        stats=stats,
        search=search,
        status_filter=status_filter,
        next_url=next_url,
    )


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

        customer = Customer(email=email or None, phone=phone, expiry_date=expiry, notes=notes)
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
            return jsonify({"success": False, "message": PHONE_NOT_ALLOWED_MSG}), 403

        phone_status = _evaluate_status(phone_holder.expiry_date)
        if phone_status == 'expired':
            return jsonify({"success": False, "message": PHONE_NOT_ALLOWED_MSG}), 403

        # Validate requester
        requester = Customer.query.filter(func.lower(Customer.email) == email).first()
        if not requester:
            return jsonify({"success": False, "message": "Email không hợp lệ hoặc chưa được cấp quyền, vui lòng liên hệ admin."}), 403

        status = _evaluate_status(requester.expiry_date)
        if status == 'expired':
            return jsonify({"success": False, "message": "Gói Netflix của bạn đã hết hạn, vui lòng liên hệ admin để được gia hạn."}), 403

        # Validate target (can be the same as requester)
        target = Customer.query.filter(func.lower(Customer.email) == target_email).first()
        if not target:
            return jsonify({"success": False, "message": "Email đích không tồn tại trong hệ thống."}), 404

        target_status = _evaluate_status(target.expiry_date)
        if target_status == 'expired':
            return jsonify({"success": False, "message": "Email đích đã hết hạn, vui lòng liên hệ admin."}), 403

        worker = ensure_worker()
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
        ensure_worker()  # ✅ Chỉ warm-up khi chạy server thật
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
