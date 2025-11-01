# worker.py
import sqlite3, time
from datetime import datetime

DB_PATH = r"D:\Workspace\Get code tukitech web\data\tuki.db"

def save_result(email, code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT, code TEXT, created_at TEXT
    )""")
    c.execute("INSERT INTO results(email, code, created_at) VALUES(?,?,?)",
              (email, code, datetime.now().isoformat()))
    conn.commit(); conn.close()

def run_worker(email):
    # ... logic Selenium/Playwright tìm mã trên Tukitech ...
    # giả sử bạn đã lấy được:
    code = "2620"  # thay bằng code scrape được
    save_result(email, code)

if __name__ == "__main__":
    while True:
        try:
            run_worker(email="abc@example.com")
        except Exception as e:
            print("Worker error:", e)
        time.sleep(5)  # lặp để cập nhật
