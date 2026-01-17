# Hướng dẫn triển khai trên Ubuntu (VPS)

> Mục tiêu: chạy app bằng Gunicorn + systemd, tùy chọn Nginx reverse proxy.

## 0) Chuẩn bị nhanh (tài khoản, thư mục, firewall)
1. SSH vào VPS:
   ```bash
   ssh <user>@<vps-ip>
   ```
2. (Khuyến nghị) Tạo user riêng cho app:
   ```bash
   sudo adduser deployer
   sudo usermod -aG sudo deployer
   su - deployer
   ```
3. (Tùy chọn) Mở firewall nếu dùng UFW:
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

### (Khuyến nghị) Cài deps cho Playwright/Selenium
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

## 3) Cấu hình biến môi trường (.env)
1. Tạo file `.env` tại thư mục project:
   ```bash
   cp .env.example .env
   ```
2. Mở file và sửa các giá trị quan trọng:
   ```bash
   nano .env
   ```
   - `SECRET_KEY`: khóa bí mật cho Flask.
   - `ADMIN_PASSWORD`: mật khẩu admin.
   - `DATABASE_URL`: mặc định dùng SQLite.
   - `TUKI_HEADLESS`: để `1` trên server.
   - `TUKI_FORCE_HEADFUL`: đặt `1` nếu muốn chạy headful trên VPS (cần DISPLAY).
   - Các biến `TUKI_CHROME_*`: chỉ cần nếu bạn muốn dùng Chrome profile/debugger.

### (Tùy chọn) Chạy headful trên VPS bằng Xvfb (khắc phục lỗi Netflix khi headless)
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

## 4) Chạy thử nhanh bằng Gunicorn
```bash
gunicorn --config gunicorn_conf.py wsgi:application
```
Mở trình duyệt truy cập `http://<vps-ip>:5000` để kiểm tra.

## 5) Chạy nền bằng systemd (khuyến nghị)
Bạn có thể dùng mẫu có sẵn trong repo: `deploy/systemd/netflix-app.service`.

1. Copy file mẫu sang systemd:
   ```bash
   sudo cp deploy/systemd/netflix-app.service /etc/systemd/system/netflix-app.service
   ```
2. Sửa các field cho đúng:
   ```bash
   sudo nano /etc/systemd/system/netflix-app.service
   ```
   Cập nhật:
   - `User` / `Group`: user chạy app (vd: `deployer`).
   - `WorkingDirectory`: đường dẫn đến repo (vd: `/home/deployer/app`).
   - `EnvironmentFile`: đường dẫn `.env`.
   - `ExecStart`: đường dẫn gunicorn trong venv.

   Ví dụ:
   ```ini
   [Service]
   User=deployer
   Group=deployer
   WorkingDirectory=/home/deployer/app
   EnvironmentFile=/home/deployer/app/.env
   ExecStart=/home/deployer/app/.venv/bin/gunicorn --config /home/deployer/app/gunicorn_conf.py wsgi:application
   ```
3. Khởi động service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now netflix-app
   sudo systemctl status netflix-app
   ```

## 6) (Tùy chọn) Reverse proxy với Nginx
Bạn có thể dùng mẫu có sẵn trong repo: `deploy/nginx/netflix-app.conf`.

1. Cài Nginx:
   ```bash
   sudo apt install -y nginx
   ```
2. Copy file mẫu:
   ```bash
   sudo cp deploy/nginx/netflix-app.conf /etc/nginx/sites-available/netflix-app
   ```
3. Mở file và chỉnh `server_name`:
   ```bash
   sudo nano /etc/nginx/sites-available/netflix-app
   ```
4. Kích hoạt site và reload:
   ```bash
   sudo ln -s /etc/nginx/sites-available/netflix-app /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

## 7) Kiểm tra & logs
- Kiểm tra service:
  ```bash
  sudo systemctl status netflix-app
  ```
- Xem log:
  ```bash
  sudo journalctl -u netflix-app -f
  ```

## 8) Gỡ lỗi nhanh
- App không lên: xem log gunicorn trong `journalctl`.
- Nginx 502: kiểm tra port gunicorn (`gunicorn_conf.py`) và `proxy_pass`.
- Playwright lỗi: chạy lại `python -m playwright install --with-deps`.
