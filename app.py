from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from tuki_persistent import TukiPersistent
import config
import re

# Flask init
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = config.SECRET_KEY

db = SQLAlchemy(app)


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
class Phone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    expiry = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# === WORKER (KEEP CHROME ALIVE) ===
_worker = None
def ensure_worker():
    global _worker
    if _worker is None:
        print("⚙️  Khởi tạo phiên Tukitech ...")
        _worker = TukiPersistent(headless=False)
    return _worker


# === ROUTES ===
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        phone = request.form.get('phone')
        email = request.form.get('email')
        expiry = request.form.get('expiry')
        if phone and email:
            db.session.add(Phone(phone=phone, email=email, expiry=expiry))
            db.session.commit()
        return redirect(url_for('admin'))

    phones = Phone.query.order_by(Phone.id.desc()).all()
    return render_template('admin_dashboard.html', phones=phones)


# === API ===
@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    try:
        data = request.form if request.form else request.json
        email = (data or {}).get('email', '').strip()
        kind  = (data or {}).get('kind', 'login_code')

        if not email:
            return jsonify({"success": False, "message": "Thiếu email"}), 400
        if kind not in ("login_code", "verify_link"):
            return jsonify({"success": False, "message": f"kind không hợp lệ: {kind}"}), 400

        worker = ensure_worker()
        print(f"[API] yêu cầu: kind={kind} email={email}")
        result = worker.fetch(email=email, kind=kind)
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
