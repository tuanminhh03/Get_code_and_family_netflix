from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from tuki_persistent import TukiPersistent
import config

# Flask init
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = config.SECRET_KEY

db = SQLAlchemy(app)

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

        # 🧩 Chỉ giữ lại mã và thời gian, bỏ hết text dư
        if isinstance(result, dict):
            code = result.get("code") or result.get("result") or ""
            timestamp = result.get("timestamp") or ""
        elif isinstance(result, str):
            # nếu worker trả về chuỗi thô, tự tách số và thời gian
            import re
            code_match = re.search(r"(\d{3,6})", result)
            time_match = re.search(r"\w{3},\s\d{1,2}\s\w{3}\s\d{4}\s[\d:]+", result)
            code = code_match.group(1) if code_match else ""
            timestamp = time_match.group(0) if time_match else ""
        else:
            code, timestamp = "", ""

        return jsonify({
            "success": True,
            "code": code,
            "timestamp": timestamp or datetime.now().strftime("%a, %d %b %Y %H:%M:%S")
        })

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
