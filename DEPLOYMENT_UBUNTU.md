# Hướng dẫn triển khai trên Ubuntu (VPS)

> Mục tiêu: chạy app bằng Gunicorn + systemd, tùy chọn Nginx reverse proxy.

## 0) Chuẩn bị nhanh (tài khoản, thư mục, firewall)
1. SSH vào VPS:
   ```bash
   ssh <user>@<vps-ip>
(Khuyến nghị) Tạo user riêng cho app:

sudo adduser deployer
sudo usermod -aG sudo deployer
su - deployer
(Tùy chọn) Mở firewall nếu dùng UFW:

sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
1) Cài đặt các gói cần thiết
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
(Khuyến nghị) Cài deps cho Playwright/Selenium
Ứng dụng có sử dụng Playwright/Selenium để tự động trình duyệt, vì vậy bạn cần cài browser.

Cách A: Cài browser qua Playwright (đề xuất)

python -m playwright install --with-deps
Cách B: Dùng Chromium hệ thống

sudo apt install -y chromium-browser
2) Clone mã nguồn và tạo môi trường ảo
git clone <your-repo-url> app
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
3) Cấu hình biến môi trường (.env)
Tạo file .env:

cp .env.example .env
Sửa file:

nano .env
Các biến quan trọng:

SECRET_KEY

ADMIN_PASSWORD

DATABASE_URL

TUKI_HEADLESS=1

TUKI_FORCE_HEADFUL=1 (chỉ bật khi cần)

TUKI_CHROME_* (tuỳ chọn)

(Tùy chọn) Chạy headful bằng Xvfb
sudo apt install -y xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
export TUKI_FORCE_HEADFUL=1
Nếu dùng `xvfb-run` mà báo lỗi `awk: not found` hoặc `getopt: not found`, cài thêm:
```
sudo apt install -y gawk util-linux
```
4) Chạy thử nhanh bằng Gunicorn
gunicorn --config gunicorn_conf.py wsgi:application
Nếu bind 127.0.0.1:5000 → cần Nginx / SSH tunnel

Nếu bind 0.0.0.0:5000 → test trực tiếp http://<vps-ip>:5000 (không khuyến nghị lâu dài)

5) Chạy nền bằng systemd (khuyến nghị)
Cách A: Dùng file mẫu trong repo
sudo cp deploy/systemd/netflix-app.service /etc/systemd/system/netflix-app.service
sudo nano /etc/systemd/system/netflix-app.service
Ví dụ nội dung:

[Unit]
Description=Netflix Flask App
After=network.target

[Service]
Type=simple
User=deployer
Group=deployer
WorkingDirectory=/home/deployer/app
EnvironmentFile=/home/deployer/app/.env
ExecStart=/home/deployer/app/.venv/bin/gunicorn --config /home/deployer/app/gunicorn_conf.py wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
Khởi động:

sudo systemctl daemon-reload
sudo systemctl enable --now netflix-app
sudo systemctl status netflix-app
6) (Tùy chọn) Reverse proxy với Nginx
sudo apt install -y nginx
sudo cp deploy/nginx/netflix-app.conf /etc/nginx/sites-available/netflix-app
sudo nano /etc/nginx/sites-available/netflix-app
Kích hoạt:

sudo ln -s /etc/nginx/sites-available/netflix-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
7) Kiểm tra & logs
sudo systemctl status netflix-app
sudo journalctl -u netflix-app -f
8) Gỡ lỗi nhanh
App không lên → xem journalctl

Nginx 502 → check port gunicorn + proxy_pass

Playwright lỗi → chạy lại:

python -m playwright install --with-deps

---

## Sau khi dán xong → chạy lệnh này
```bash
git add <tên_file_md>
git commit -m "Resolve merge conflict: Ubuntu VPS deployment guide"
