# Hướng dẫn triển khai trên Ubuntu (VPS)

## 1) Cài đặt các gói cần thiết
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

## 2) Clone mã nguồn và tạo môi trường ảo
```bash
git clone <your-repo-url> app
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3) Cấu hình biến môi trường
Tạo file `.env` tại thư mục project:
```bash
SECRET_KEY=change-me
ADMIN_PASSWORD=adminpass
DATABASE_URL=sqlite:///data.db
TUKI_HEADLESS=1
GUNICORN_BIND=0.0.0.0:5000
```

## 4) Chạy bằng Gunicorn (khuyến nghị)
```bash
gunicorn --config gunicorn_conf.py wsgi:application
```

## 5) (Tùy chọn) Tạo systemd service
Tạo file `/etc/systemd/system/netflix-app.service`:
```ini
[Unit]
Description=Netflix Flask App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/app
EnvironmentFile=/home/ubuntu/app/.env
ExecStart=/home/ubuntu/app/.venv/bin/gunicorn --config /home/ubuntu/app/gunicorn_conf.py wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```
Sau đó:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now netflix-app
sudo systemctl status netflix-app
```

## 6) (Tùy chọn) Reverse proxy với Nginx
Cấu hình Nginx để trỏ về `http://127.0.0.1:5000` và mở firewall tương ứng.
