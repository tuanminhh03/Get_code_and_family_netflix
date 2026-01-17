# Hướng dẫn triển khai trên Ubuntu (VPS)

## 1) Cài đặt các gói cần thiết
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### (Khuyến nghị) Cài đặt deps cho Playwright/Selenium
Ứng dụng có sử dụng Playwright/Selenium để tự động trình duyệt, vì vậy bạn cần cài browser.
Bạn có 2 lựa chọn:

**Cách A: Cài browser qua Playwright (đề xuất)**
```bash
# chạy trong virtualenv
python -m playwright install --with-deps
```

**Cách B: Dùng Chromium hệ thống**
```bash
sudo apt install -y chromium-browser
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
Tạo file `.env` tại thư mục project (có thể copy từ `.env.example`):
```bash
cp .env.example .env
```

Chỉnh lại các giá trị quan trọng:
- `SECRET_KEY`: khóa bí mật cho Flask.
- `ADMIN_PASSWORD`: mật khẩu admin.
- `DATABASE_URL`: mặc định dùng SQLite.
- `TUKI_HEADLESS`: để `1` trên server.
- `TUKI_FORCE_HEADFUL`: đặt `1` nếu muốn chạy headful trên VPS (cần DISPLAY).
- Các biến `TUKI_CHROME_*`: chỉ cần nếu bạn muốn dùng Chrome profile/debugger.

### Chạy headful trên VPS bằng Xvfb (khắc phục lỗi Netflix khi headless)
> Lưu ý: Chỉ bật nếu bạn đã cài Xvfb và muốn chạy headful.

```bash
sudo apt install -y xvfb
```

Chạy app với DISPLAY ảo:
```bash
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
export TUKI_FORCE_HEADFUL=1
```

Sau đó chạy app như bình thường (gunicorn hoặc python). Nếu muốn chạy nền, hãy đưa các lệnh export vào file `.env` hoặc systemd service.

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
Tạo file `/etc/nginx/sites-available/netflix-app`:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Kích hoạt site và reload:
```bash
sudo ln -s /etc/nginx/sites-available/netflix-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Nếu dùng UFW:
```bash
sudo ufw allow 80
sudo ufw allow 443
```
