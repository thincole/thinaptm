"""Tự cập nhật bản mới nhất từ GitHub (Quản lý trực tiếp từ thẻ thông báo trên giao diện Thìn Aptm)."""
import os
import urllib.request
import subprocess
import sys

FILES = [
    "thin_aptm.py", 
    "engine.py", 
    "login.py", 
    "auto_voice_sub.py",
    "ghep_video.py",
    "prompt_templates.py",
    "recaptcha_farm.py",
    "shopeevideo.py",
    "update.py", 
    "bump_version.py",
    "UPDATE.bat",
    "requirements.txt", 
    "CHAY.bat", 
    "SETUP.bat",
    # ShopAPI SDK
    "_sdk/shopapi/__init__.py",
    "_sdk/shopapi/_client.py",
    "_sdk/shopapi/_constants.py",
    "_sdk/shopapi/_exceptions.py",
    "_sdk/shopapi/_models.py",
    "_sdk/shopapi/_money.py",
    "_sdk/shopapi/_nhip_do.py",
    "_sdk/shopapi/_nho_nhip.py",
    "_sdk/shopapi/_pagination.py",
    "_sdk/shopapi/_polling.py",
    "_sdk/shopapi/_sse.py",
    "_sdk/shopapi/_validation.py",
    "_sdk/shopapi/_version.py",
    "_sdk/shopapi/py.typed",
    "_sdk/shopapi/webhooks.py",
    "_sdk/shopapi/resources/__init__.py",
    "_sdk/shopapi/resources/balance.py",
    "_sdk/shopapi/resources/images.py",
    "_sdk/shopapi/resources/jobs.py",
    "_sdk/shopapi/resources/ledger.py",
    "_sdk/shopapi/resources/pricing.py",
    "_sdk/shopapi/resources/stats.py",
    "_sdk/shopapi/resources/topup.py",
    "_sdk/shopapi/resources/tts.py",
    "_sdk/shopapi/resources/uploads.py",
    "_sdk/shopapi/resources/usage.py",
    "_sdk/shopapi/resources/videos.py",
]

BASE_URL = "https://raw.githubusercontent.com/thincole/thinaptm/main/"

def main():
    print("[*] Dang dong bo code moi nhat tu GitHub...")
    try:
        res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            print("[OK] Da dong bo code thanh cong bang Git!")
            print(res.stdout)
            _check_requirements()
            return
    except Exception:
        pass

    success = 0
    for f in FILES:
        try:
            url = BASE_URL + f
            data = urllib.request.urlopen(url, timeout=10).read()
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f.replace("/", os.sep))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as local_f:
                local_f.write(data)
            print(f"  [OK] Da cap nhat: {f}")
            success += 1
        except Exception as e:
            print(f"  [!] Loi tai {f}: {e}")
    
    print(f"\n[=== CAP NHAT HOAN TAT ===] Da cap nhat {success}/{len(FILES)} file!")
    _check_requirements()

def _check_requirements():
    try:
        import httpx
    except ImportError:
        print("[*] Dang cai dat thu vien bo sung (httpx)...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"], timeout=30)
            print("[OK] Da cai dat httpx!")
        except Exception as e:
            print(f"[!] Loi cai httpx: {e}")

if __name__ == "__main__":
    main()
