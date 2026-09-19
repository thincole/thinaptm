"""Tự cập nhật bản mới nhất từ GitHub (Quản lý trực tiếp từ thẻ thông báo trên giao diện Thìn Aptm)."""
import os
import urllib.request
import subprocess
import sys
import json

# Danh sách file tĩnh chuẩn bị sẵn (fallback khi không gọi được GitHub Tree API)
FILES = [
    "thin_aptm.py", 
    "engine.py", 
    "engine_ext.py",
    "flow_bridge.py",
    "flow_batch.py",
    "login.py", 
    "auto_voice_sub.py",
    "ghep_video.py",
    "watermark_remover.py",
    "browser_stealth.py",
    "prompt_templates.py",
    "recaptcha_farm.py",
    "shopeevideo.py",
    "SlideShow.py",
    "update.py", 
    "bump_version.py",
    "UPDATE.bat",
    "requirements.txt", 
    "CHAY.bat", 
    "SETUP.bat",
    "day_code_len_github.bat",
    "logo.ico",
    "logo.png",
    # Thư mục Extension
    "extension/manifest.json",
    "extension/background.js",
    "extension/content.js",
    "extension/injected.js",
    "extension/popup.html",
    "extension/popup.js",
    "extension/side_panel.html",
    "extension/side_panel.js",
    # Mẫu prompts
    "prompts_mau/01_4dieu_imlang_T2V.txt",
    "prompts_mau/02_5dauhi_truongthanh_T2V.txt",
    "prompts_mau/03_3quytac_nguoimanhme_T2V.txt",
]

BASE_URL = "https://raw.githubusercontent.com/thincole/thinaptm/main/"
TREE_API_URL = "https://api.github.com/repos/thincole/thinaptm/git/trees/main?recursive=1"

EXCLUDE_EXTS = {'.pyc', '.txt.bak'}
EXCLUDE_FILES = {'crash_log.txt', 'err.txt', '_probe_test.jpg', 'locate_lines.py', 'locate_lines2.py', 'patch.py', 'install.bat', 'bootstrap.json', 'docs_v2.json', 'update_urls.py', 'new_version.txt', 'settings.json'}
EXCLUDE_DIRS = {'.git', '.agents', '.gemini', '__pycache__', 'output_seedvis', 'temp_render'}

def _is_ignored(path_str):
    low = path_str.lower().replace("\\", "/")
    parts = low.split('/')
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if any(p.startswith('.') for p in parts):
        return True
    filename = os.path.basename(low)
    if filename in EXCLUDE_FILES:
        return True
    ext = os.path.splitext(low)[1]
    if ext in EXCLUDE_EXTS:
        return True
    return False

def get_file_list():
    """Lấy danh sách file từ GitHub Tree API để tự động phát hiện mọi file/thư mục mới (kể cả extension).
    Nếu lỗi mạng hoặc chạm rate-limit thì tự động fallback về danh sách FILES."""
    try:
        req = urllib.request.Request(
            TREE_API_URL,
            headers={"User-Agent": "ThinAptm-Updater", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tree = data.get("tree", [])
            dynamic_files = []
            for item in tree:
                if item.get("type") == "blob":
                    p = item.get("path", "")
                    if not _is_ignored(p):
                        dynamic_files.append(p)
            if dynamic_files and len(dynamic_files) >= 10:
                return dynamic_files
    except Exception:
        pass
    return FILES

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

    file_list = get_file_list()
    success = 0
    total = len(file_list)
    for f in file_list:
        try:
            url = BASE_URL + f
            req = urllib.request.Request(
                url + f"?t={os.urandom(4).hex()}",
                headers={"User-Agent": "ThinAptm-Updater", "Cache-Control": "no-cache"}
            )
            data = urllib.request.urlopen(req, timeout=12).read()
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f.replace("/", os.sep))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as local_f:
                local_f.write(data)
            print(f"  [OK] Da cap nhat: {f}")
            success += 1
        except Exception as e:
            print(f"  [!] Loi tai {f}: {e}")
    
    print(f"\n[=== CAP NHAT HOAN TAT ===] Da cap nhat {success}/{total} file!")
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
