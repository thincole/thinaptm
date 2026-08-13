"""Tự cập nhật bản mới nhất từ GitHub (Quản lý trực tiếp từ thẻ thông báo trên giao diện Thìn Aptm)."""
import os

FILES = [
    "thin_aptm.py", 
    "engine.py", 
    "login.py", 
    "auto_voice_sub.py",
    "ghep_video.py",
    "prompt_templates.py",
    "recaptcha_farm.py",
    "update.py", 
    "UPDATE.bat",
    "requirements.txt", 
    "CHAY.bat", 
    "SETUP.bat",
    "logo.ico",
    "logo.png"
]

def main():
    # Không hiện popup cảnh báo khi vào ứng dụng.
    # Việc kiểm tra và cập nhật được quản lý trực tiếp tại Thẻ Cập Nhật (góc dưới bên trái Sidebar).
    pass

if __name__ == "__main__":
    main()
