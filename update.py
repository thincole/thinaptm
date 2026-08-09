"""Tự cập nhật bản mới nhất từ GitHub thincole/thinaptm (chạy trước khi mở tool). Offline thì bỏ qua, dùng bản local."""
import urllib.request, os, sys
import tkinter as tk
from tkinter import messagebox

REPO = "thincole/thinaptm"
BASE = f"https://raw.githubusercontent.com/{REPO}/main/"
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
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    print("Checking for updates from GitHub (thincole/thinaptm)...")
    pending_updates = []
    
    # 1. Kiểm tra xem có file nào có bản mới từ GitHub không
    for f in FILES:
        try:
            req = urllib.request.Request(
                BASE + f + f"?t={os.urandom(4).hex()}",
                headers={"Cache-Control": "no-cache", "User-Agent": "thinaptm-updater"}
            )
            data = urllib.request.urlopen(req, timeout=5).read()
            if not data or len(data) < 30:
                continue
            local = os.path.join(HERE, f)
            old = open(local, "rb").read() if os.path.exists(local) else b""
            if data != old:
                pending_updates.append((f, local, data))
        except Exception:
            pass  # offline hoặc lỗi mạng -> dùng bản local

    if not pending_updates:
        print("Already up to date (Đã ở bản local mới nhất).")
        return

    # 2. Bật Popup hỏi ý kiến người dùng trước khi tải cập nhật
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        changed_filenames = ", ".join([item[0] for item in pending_updates[:4]])
        if len(pending_updates) > 4:
            changed_filenames += "..."
            
        prompt_msg = (
            f"Phát hiện có bản cập nhật mới từ GitHub ({len(pending_updates)} file: {changed_filenames})!\n\n"
            f"Bạn có muốn tải bản cập nhật mới về không?\n"
            f"• Chọn Yes: Tải và đè bản cập nhật mới từ GitHub\n"
            f"• Chọn No : Bỏ qua và giữ nguyên bản local hiện tại để mở tool"
        )
        
        do_update = messagebox.askyesno("Cập nhật phần mềm Thìn Aptm", prompt_msg, parent=root)
        root.destroy()
    except Exception:
        do_update = False

    if not do_update:
        print("Người dùng chọn BỎ QUA cập nhật, giữ nguyên bản local.")
        return

    # 3. Người dùng đồng ý (Yes) -> Tiến hành ghi đè file cập nhật
    updated = 0
    for f, local, data in pending_updates:
        try:
            with open(local, "wb") as fp:
                fp.write(data)
            print(f"  -> Updated: {f}")
            updated += 1
        except Exception as e:
            print(f"  ❌ Error updating {f}: {e}")

    print(f"Update completed ({updated} files updated).")


if __name__ == "__main__":
    main()
