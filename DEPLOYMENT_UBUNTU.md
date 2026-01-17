# Hướng dẫn triển khai trên Ubuntu (VPS)

> Mục tiêu: chạy app bằng Gunicorn + systemd, tùy chọn Nginx reverse proxy.

## 0) Chuẩn bị nhanh (tài khoản, thư mục, firewall)
1) SSH vào VPS:
```bash
ssh <user>@<vps-ip>
```

2) (Khuyến nghị) Tạo user riêng cho app:
```bash
sudo adduser deployer
sudo usermod -aG sudo deployer
su - deployer
```

3) (Tùy chọn) Mở firewall nếu dùng UFW:
```bash
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

## 1) Cài đặt các gói cần thiết
```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

## 2) Cài trình duyệt cho automation (Playwright/Selenium)
Ứng dụng có sử dụng Playwright/Selenium để tự động trình duyệt, vì vậy bạn cần cài browser.

### Cách A: Cài browser qua Playwright (đề xuất)
```bash
python -m playwright install --with-deps
```

### Cách B: Dùng Chromium hệ thống
```bash
sudo apt install -y chromium-browser
```

## 3) Clone mã nguồn và tạo môi trường ảo
```bash
git clone <your-repo-url> app
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4) Cấu hình biến môi trường (.env)
Tạo file `.env`:
```bash
cp .env.example .env
```

Sửa file:
```bash
nano .env
```

Các biến quan trọng:
- `SECRET_KEY`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `TUKI_HEADLESS=1`
- `TUKI_FORCE_HEADFUL=1` (chỉ bật khi cần)
- `TUKI_CHROME_*` (tuỳ chọn)

### (Tùy chọn) Chạy headful bằng Xvfb
```bash
sudo apt install -y xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
export TUKI_FORCE_HEADFUL=1
```

Nếu dùng `xvfb-run` mà báo lỗi `awk: not found` hoặc `getopt: not found`, cài thêm:
```bash
sudo apt install -y gawk util-linux
```

## 5) Chạy thử nhanh bằng Gunicorn
```bash
gunicorn --config gunicorn_conf.py wsgi:application
```
Nếu bind `127.0.0.1:5000` → cần Nginx / SSH tunnel.

Nếu bind `0.0.0.0:5000` → test trực tiếp `http://<vps-ip>:5000` (không khuyến nghị lâu dài).

## 6) Chạy nền bằng systemd (khuyến nghị)
Cách A: Dùng file mẫu trong repo:
```bash
sudo cp deploy/systemd/netflix-app.service /etc/systemd/system/netflix-app.service
sudo nano /etc/systemd/system/netflix-app.service
```

Ví dụ nội dung:
```ini
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
```

Khởi động:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now netflix-app
sudo systemctl status netflix-app
```

## 7) (Tùy chọn) Reverse proxy với Nginx
```bash
sudo apt install -y nginx
sudo cp deploy/nginx/netflix-app.conf /etc/nginx/sites-available/netflix-app
sudo nano /etc/nginx/sites-available/netflix-app
```

Kích hoạt:
```bash
sudo ln -s /etc/nginx/sites-available/netflix-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 8) Kiểm tra & logs
```bash
sudo systemctl status netflix-app
sudo journalctl -u netflix-app -f
```

## 9) Gỡ lỗi nhanh
- App không lên → xem `journalctl`.
- Nginx 502 → kiểm tra port Gunicorn + `proxy_pass`.
- Playwright lỗi → chạy lại:
```bash
python -m playwright install --with-deps
```

## 10) Troubleshooting Chrome/Chromium không tìm thấy
Nếu `which google-chrome-stable` không ra gì, nghĩa là Chrome chưa cài.

### Cài Google Chrome (deb) đúng cách
```bash
wget -qO- https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-linux-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable
```

Kiểm tra đường dẫn:
```bash
which google-chrome-stable
```

Nếu ra `/usr/bin/google-chrome-stable`, thêm vào `.env`:
```env
CHROME_BINARY=/usr/bin/google-chrome-stable
HEADLESS=1
```

### Lưu ý khi dán lệnh
Khi `tee` hỏi `Overwrite? (y/N)`, **chỉ gõ `y` rồi Enter**.
Đừng dán thêm lệnh khác vào prompt đó, nếu không shell sẽ hiểu đó là tên file.
