"""Tự cập nhật bản mới nhất từ GitHub thincole/thinaptm (chạy trước khi mở tool). Offline thì bỏ qua, dùng bản local."""
import urllib.request, os

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
    updated = 0
    for f in FILES:
        try:
            req = urllib.request.Request(
                BASE + f + f"?t={os.urandom(4).hex()}",
                headers={"Cache-Control": "no-cache", "User-Agent": "thinaptm-updater"}
            )
            data = urllib.request.urlopen(req, timeout=10).read()
            if not data or len(data) < 30:
                continue
            local = os.path.join(HERE, f)
            old = open(local, "rb").read() if os.path.exists(local) else b""
            if data != old:
                with open(local, "wb") as fp:
                    fp.write(data)
                print(f"  -> Updated: {f}")
                updated += 1
        except Exception:
            pass   # offline / chua co file tren repo -> dung ban local
    if updated > 0:
        print(f"Update completed ({updated} files updated).")
    else:
        print("Already up to date.")


if __name__ == "__main__":
    main()

