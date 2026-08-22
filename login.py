"""
login — 3 cách lấy cookie labs.google:
  1. manual_login(): mở Chrome, người dùng TỰ đăng nhập + vào Flow -> có cookie thì tự lấy + tắt Chrome.
  2. login_get_cookie(): TỰ đăng nhập bằng email|password|2fa (DrissionPage + pyotp).
  3. reopen_profile_cookie(): mở Chrome với profile CŨ (giữ session Google) → tự lấy cookie mới mà KHÔNG cần password.
Cần: DrissionPage, pyotp.
"""
import time, os, random

LABS = "https://labs.google/fx/tools/flow"
# Dùng accounts.google.com cơ bản — Google tự redirect sang trang v3/signin mới nhất
GOOGLE_SIGNIN = "https://accounts.google.com"
_KEEP = ("next-auth", "__Secure", "__Host", "_ga", "email")


def get_chrome_path():
    """Lấy đường dẫn Google Chrome chuẩn trên Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _opts(profile_dir=None):
    from DrissionPage import ChromiumOptions
    co = ChromiumOptions()
    chrome_path = get_chrome_path()
    if chrome_path:
        co.set_browser_path(chrome_path)
    co.set_argument("--no-first-run"); co.set_argument("--no-default-browser-check")
    if profile_dir:
        try:
            os.makedirs(profile_dir, exist_ok=True)
            co.set_user_data_path(profile_dir)
            # DP4 bug: auto_port() + set_user_data_path() → address rỗng → crash
            # Dùng set_local_port(random) thay thế
            co.set_local_port(random.randint(19200, 29999))
        except Exception:
            co.auto_port()
    else:
        co.auto_port()
    return co


def _labs_cookie(cks):
    parts = []
    for c in cks or []:
        if "labs.google" in c.get("domain", "") and any(k in c.get("name", "") for k in _KEEP):
            parts.append(f"{c.get('name')}={c.get('value','')}")
    return "; ".join(parts)


def _is_cookie_valid(cookie):
    """Xác minh cookie có thực sự lấy được Bearer token còn hạn từ Google Labs hay không."""
    if not cookie or "next-auth.session-token" not in cookie:
        return False
    try:
        import engine as E
        res = E.bearer_from_cookie(cookie)
        token = res[0] if isinstance(res, tuple) else res
        return bool(token)
    except Exception:
        return False


def _totp_now(secret):
    try:
        import pyotp
        return pyotp.TOTP(str(secret).replace(" ", "")).now()
    except Exception:
        return None


def _has_profile_data(profile_dir):
    """Kiểm tra profile có dữ liệu Chrome thật sự (không chỉ thư mục rỗng)."""
    if not profile_dir or not os.path.exists(profile_dir):
        return False
    # Chrome tạo file "Local State" khi profile được dùng lần đầu
    return os.path.exists(os.path.join(profile_dir, "Local State"))


def kill_chrome_locking_profile(profile_dir, log=print):
    """Quét và tắt các tiến trình Chrome đang chiếm giữ/khóa thư mục profile này (Tuyệt đối KHÔNG chạm vào GemLogin)."""
    import os
    if not profile_dir:
        return
    profile_dir_norm = os.path.normpath(profile_dir).lower()
    profile_folder_name = os.path.basename(profile_dir_norm)
    
    try:
        import psutil
        killed_any = False
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = p.info['name'] or ''
                if name.lower() == 'chrome.exe':
                    cmdline = p.info['cmdline'] or []
                    cmd_str = " ".join(cmdline).lower()
                    # TUYỆT ĐỐI KHÔNG TẮT GEMLOGIN
                    if 'gemlogin' in cmd_str:
                        continue
                    try:
                        exe_path = psutil.Process(p.info['pid']).exe().lower()
                        if 'gemlogin' in exe_path:
                            continue
                    except Exception:
                        pass
                    if profile_folder_name in cmd_str or profile_dir_norm in cmd_str:
                        log(f"⚠️ Phát hiện tiến trình Chrome (PID {p.info['pid']}) đang khóa profile. Đang buộc dừng...")
                        psutil.Process(p.info['pid']).kill()
                        killed_any = True
            except Exception:
                pass
        if killed_any:
            import time
            time.sleep(1) # Chờ 1 giây để OS giải phóng file lock hoàn toàn
    except Exception as e:
        log(f"  ⚠️ Lỗi khi quét tiến trình khóa: {e}")


def check_and_convert_gemlogin_profile(profile_dir, log=print):
    """Kiểm tra xem profile có phải định dạng GemLogin (chứa prefix 32 bytes của cookie) không,
    nếu có thì giải mã, khử prefix 32 bytes, mã hóa lại dạng Chrome chuẩn và lưu đè.
    Điều này giúp Chrome thường (DrissionPage) đọc được session mà không bị mất login."""
    import os
    # Buộc đóng Chrome đang khóa thư mục này trước khi thực hiện thao tác file
    kill_chrome_locking_profile(profile_dir, log)
    import json
    import base64
    import sqlite3
    import shutil
    import random
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import ctypes
    from ctypes import wintypes

    if not profile_dir or not os.path.exists(profile_dir):
        return False

    local_state_path = os.path.join(profile_dir, "Local State")
    cookies_db = os.path.join(profile_dir, "Default", "Network", "Cookies")
    if not os.path.exists(cookies_db):
        cookies_db = os.path.join(profile_dir, "Default", "Cookies")

    if not os.path.exists(local_state_path) or not os.path.exists(cookies_db):
        return False

    class DATA_BLOB_LOCAL(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char))
        ]

    def decrypt_dpapi_local(data):
        try:
            in_blob = DATA_BLOB_LOCAL(len(data), ctypes.create_string_buffer(data))
            out_blob = DATA_BLOB_LOCAL()
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
                return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        except Exception:
            pass
        return None

    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        enc_key_b64 = local_state.get("os_crypt", {}).get("encrypted_key")
        if not enc_key_b64:
            return False
        
        encrypted_key = base64.b64decode(enc_key_b64)[5:]
        aes_key = decrypt_dpapi_local(encrypted_key)
        if not aes_key:
            return False

        # Copy ra file temp để kiểm tra trước
        temp_db = cookies_db + f"_convert_temp_{random.randint(1000, 9999)}"
        shutil.copy2(cookies_db, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT rowid, name, encrypted_value FROM cookies")
        rows = cursor.fetchall()

        is_gemlogin = False
        aesgcm = AESGCM(aes_key)

        # Detect GemLogin signature
        for rowid, name, enc_val in rows:
            if name in ("__Secure-next-auth.session-token", "EMAIL", "email", "__Host-next-auth.csrf-token"):
                if enc_val[:3] in (b'v10', b'v11'):
                    try:
                        iv = enc_val[3:15]
                        ciphertext_and_tag = enc_val[15:]
                        dec = aesgcm.decrypt(iv, ciphertext_and_tag, None)
                        if dec and len(dec) > 32:
                            part = dec[32:]
                            if (name == "__Secure-next-auth.session-token" and part.startswith(b"eyJ")) or \
                               (name == "email" and (b"@" in part or b"%40" in part)) or \
                               (name == "EMAIL" and (b"%" in part or b"\"" in part or b"@" in part or b"%40" in part)):
                                is_gemlogin = True
                                break
                    except Exception:
                        pass

        if not is_gemlogin:
            conn.close()
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return False

        log(f"⚠️ Phát hiện profile định dạng GemLogin (chứa prefix cookie). Tiến hành chuyển đổi sang Chrome chuẩn...")
        
        backup_db = cookies_db + "_pre_convert_backup"
        if not os.path.exists(backup_db):
            shutil.copy2(cookies_db, backup_db)

        updated_count = 0
        skipped_count = 0

        for rowid, name, enc_val in rows:
            if enc_val[:3] in (b'v10', b'v11'):
                try:
                    iv = enc_val[3:15]
                    ciphertext_and_tag = enc_val[15:]
                    dec = aesgcm.decrypt(iv, ciphertext_and_tag, None)
                    if dec and len(dec) > 32:
                        stripped_dec = dec[32:]
                        new_iv = bytes(random.getrandbits(8) for _ in range(12))
                        new_ciphertext_and_tag = aesgcm.encrypt(new_iv, stripped_dec, None)
                        new_enc_val = b'v10' + new_iv + new_ciphertext_and_tag
                        cursor.execute("UPDATE cookies SET encrypted_value = ? WHERE rowid = ?", (new_enc_val, rowid))
                        updated_count += 1
                    else:
                        skipped_count += 1
                except Exception:
                    skipped_count += 1
            else:
                skipped_count += 1

        conn.commit()
        conn.close()

        shutil.copy2(temp_db, cookies_db)
        if os.path.exists(temp_db):
            os.remove(temp_db)

        log(f"✅ Đã chuyển đổi thành công {updated_count} cookies sang định dạng Chrome chuẩn.")
        return True
    except Exception as e:
        log(f"❌ Lỗi khi chuyển đổi cookie GemLogin: {e}")
        return False


def repair_corrupted_profile(profile_dir, log=print):
    """Sửa chữa profile Chrome bị lỗi kết nối bằng cách khởi tạo lại thư mục
    nhưng giữ nguyên os_crypt key (Local State), Cookies và Local Storage."""
    import shutil
    import json
    if not profile_dir or not os.path.exists(profile_dir):
        return False
        
    kill_chrome_locking_profile(profile_dir, log)
    local_state_path = os.path.join(profile_dir, "Local State")
    if not os.path.exists(local_state_path):
        return False
        
    log(f"🛠️ Đang tự động sửa chữa profile bị lỗi kết nối: {profile_dir}")
    backup_dir = profile_dir + "_repair_backup"
    
    try:
        # 1. Đọc os_crypt key cũ
        os_crypt_data = None
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            os_crypt_data = old_data.get("os_crypt")
        except Exception as e:
            log(f"  ⚠️ Không đọc được Local State cũ: {e}")
            
        # 2. Tìm Cookies và Local Storage để backup tạm
        cookies_src = os.path.join(profile_dir, "Default", "Network", "Cookies")
        if not os.path.exists(cookies_src):
            cookies_src = os.path.join(profile_dir, "Default", "Cookies")
            
        local_storage_src = os.path.join(profile_dir, "Default", "Local Storage")
        
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        os.makedirs(backup_dir, exist_ok=True)
        
        has_cookies = False
        if os.path.exists(cookies_src):
            shutil.copy2(cookies_src, os.path.join(backup_dir, "Cookies"))
            has_cookies = True
            
        has_local_storage = False
        if os.path.exists(local_storage_src):
            shutil.copytree(local_storage_src, os.path.join(backup_dir, "Local Storage"), dirs_exist_ok=True)
            has_local_storage = True
            
        # 3. Xóa thư mục profile cũ bị lỗi
        try:
            shutil.rmtree(profile_dir)
        except Exception:
            temp_old_dir = profile_dir + f"_old_locked_{random.randint(1000, 9999)}"
            try:
                os.rename(profile_dir, temp_old_dir)
                shutil.rmtree(temp_old_dir, ignore_errors=True)
            except Exception as e:
                log(f"  ⚠️ Không thể xóa/đổi tên thư mục lỗi: {e}")
                return False
                
        # 4. Khởi tạo lại profile sạch bằng DrissionPage
        from DrissionPage import ChromiumPage, ChromiumOptions
        co = ChromiumOptions()
        chrome_path = get_chrome_path()
        if chrome_path:
            co.set_browser_path(chrome_path)
        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_user_data_path(profile_dir)
        co.set_local_port(random.randint(19200, 29999))
        
        page = ChromiumPage(co)
        page.quit()
        
        # 5. Khôi phục os_crypt
        new_local_state_path = os.path.join(profile_dir, "Local State")
        if os_crypt_data and os.path.exists(new_local_state_path):
            try:
                with open(new_local_state_path, "r", encoding="utf-8") as f:
                    new_data = json.load(f)
                new_data["os_crypt"] = os_crypt_data
                with open(new_local_state_path, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, indent=4)
            except Exception as e:
                log(f"  ⚠️ Không thể ghi Local State mới: {e}")
                
        # 6. Copy lại Cookies & Local Storage
        if has_cookies:
            dest_network = os.path.join(profile_dir, "Default", "Network")
            os.makedirs(dest_network, exist_ok=True)
            shutil.copy2(os.path.join(backup_dir, "Cookies"), os.path.join(dest_network, "Cookies"))
            
        if has_local_storage:
            dest_local_storage = os.path.join(profile_dir, "Default", "Local Storage")
            shutil.copytree(os.path.join(backup_dir, "Local Storage"), dest_local_storage, dirs_exist_ok=True)
            
        # 7. Khử định dạng GemLogin nếu có
        check_and_convert_gemlogin_profile(profile_dir, log)
        
        log("✅ Sửa chữa profile hoàn tất thành công!")
        return True
    except Exception as e:
        log(f"  ❌ Lỗi sửa profile: {e}")
        return False
    finally:
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)


# ============ 1) NHẬP THỦ CÔNG: user tự đăng nhập ============
def manual_login(log=print, timeout=360, poll=2, profile_dir=None):
    """Mở Chrome -> user tự đăng nhập Google + vào Flow. Khi có cookie labs (đã login) -> lấy + TẮT Chrome.
    Nếu có profile_dir → lưu session Google vào profile để lần sau tự đăng nhập lại.
    Trả cookie (str) hoặc None (hết giờ / user đóng)."""
    try:
        from DrissionPage import ChromiumPage
    except Exception:
        log("Thiếu DrissionPage -> chạy SETUP.bat"); return None
    page = None
    try:
        if profile_dir:
            check_and_convert_gemlogin_profile(profile_dir, log)
        try:
            page = ChromiumPage(_opts(profile_dir))
        except Exception as e:
            if profile_dir:
                log(f"⚠️ Trình duyệt lỗi kết nối, đang thử tự động sửa chữa profile...")
                if repair_corrupted_profile(profile_dir, log):
                    page = ChromiumPage(_opts(profile_dir))
                else:
                    raise e
            else:
                raise e
        page.get(LABS)
        log("👉 Đăng nhập Google trong cửa sổ Chrome vừa mở, rồi vào Flow. Tool tự nhận cookie...")
        end = time.time() + timeout
        while time.time() < end:
            try:
                ck = _labs_cookie(page.cookies(all_domains=True))
            except Exception:
                return None   # user đã đóng Chrome
            if _is_cookie_valid(ck):
                log("✅ Đã nhận cookie hợp lệ -> đóng Chrome.")
                return ck
            time.sleep(poll)
        log("⌛ Hết giờ chờ đăng nhập.")
        return None
    except Exception as e:
        log(f"Lỗi: {e}"); return None
    finally:
        try:
            if page: page.quit()
        except Exception:
            pass


# ============ 2) AUTO LOGIN: email|password|2fa ============
def login_get_cookie(email, password, totp_secret="", profile_dir=None, log=print):
    try:
        from DrissionPage import ChromiumPage
    except Exception:
        log("Thiếu DrissionPage -> chạy SETUP.bat"); return None
    page = None
    try:
        if profile_dir:
            check_and_convert_gemlogin_profile(profile_dir, log)
        log(f"🔑 Mở Chrome login {email}...")
        try:
            page = ChromiumPage(_opts(profile_dir))
        except Exception as e:
            if profile_dir:
                log(f"⚠️ Trình duyệt lỗi kết nối, đang thử tự động sửa chữa profile...")
                if repair_corrupted_profile(profile_dir, log):
                    page = ChromiumPage(_opts(profile_dir))
                else:
                    raise e
            else:
                raise e

        # ── Vào thẳng LABS → nếu chưa login, Google tự redirect sang trang sign-in ──
        page.get(LABS)
        time.sleep(4)

        # Kiểm tra nhanh: profile cũ có session còn sống và hợp lệ?
        ck = _labs_cookie(page.cookies(all_domains=True))
        if _is_cookie_valid(ck):
            log(f"✅ {email}: profile cũ vẫn có session hợp lệ → lấy cookie luôn.")
            return ck

        # ── Chưa có session → Google sẽ redirect sang trang đăng nhập ──
        log(f"🔑 {email}: chưa có session → đăng nhập bằng email+pass...")
        current = page.url

        # Navigate đến Google sign-in (accounts.google.com tự redirect sang v3/signin)
        log(f"  🌐 Navigate tới trang đăng nhập Google...")
        page.get(GOOGLE_SIGNIN)
        time.sleep(4)

        log(f"  📍 URL hiện tại: {page.url[:100]}")

        already_logged_in = "myaccount.google.com" in page.url or "myactivity.google.com" in page.url
        if already_logged_in:
            log(f"  ✅ Đã đăng nhập sẵn Google (session còn sống). Bỏ qua nhập email/pass...")
        else:
            # ── Điền email ──
            log(f"  📧 Tìm ô email...")
            e_input = None
    
            # Thử tìm ô email trên trang hiện tại
            for selector in ["#identifierId", "tag:input@type=email", "tag:input@name=identifier"]:
                e_input = page.ele(selector, timeout=5)
                if e_input:
                    break
    
            if not e_input:
                # Có thể đang ở trang chọn tài khoản (account chooser)
                log(f"  🔄 Thử tìm nút 'Use another account'...")
                for txt in ["Use another account", "Sử dụng tài khoản khác", "text:Add another account",
                            "text:Thêm tài khoản khác"]:
                    try:
                        other = page.ele(f"text:{txt}", timeout=2) if not txt.startswith("text:") else page.ele(txt, timeout=2)
                        if other:
                            other.click()
                            time.sleep(3)
                            e_input = page.ele("#identifierId", timeout=8) or page.ele("tag:input@type=email", timeout=5)
                            break
                    except Exception:
                        pass
    
            if e_input:
                log(f"  📧 Điền email: {email}")
                e_input.clear()
                e_input.input(email)
                time.sleep(0.8)
                # Bấm Next
                btn = None
                for sel in ["#identifierNext", "text:Tiếp theo", "text:Next", "tag:button@type=submit"]:
                    btn = page.ele(sel, timeout=3)
                    if btn: break
                if btn:
                    btn.click()
                    log(f"  ✅ Đã nhấn Next (email)")
                time.sleep(4)
            else:
                log(f"  ❌ Không tìm thấy ô email! (URL: {page.url[:100]})")
                log(f"  💡 Thử dùng nút 'Nhập thủ công' để login qua Chrome trực tiếp.")
                return None
    
            # ── Điền password ──
            log(f"  🔒 Tìm ô password...")
            p_input = None
            for selector in ["tag:input@type=password", "tag:input@name=Passwd", "#password"]:
                p_input = page.ele(selector, timeout=8)
                if p_input: break
    
            if p_input:
                log(f"  🔒 Điền password...")
                p_input.clear()
                p_input.input(password)
                time.sleep(0.8)
                btn = None
                for sel in ["#passwordNext", "text:Tiếp theo", "text:Next", "tag:button@type=submit"]:
                    btn = page.ele(sel, timeout=3)
                    if btn: break
                if btn:
                    btn.click()
                    log(f"  ✅ Đã nhấn Next (password)")
                time.sleep(4)
            else:
                log(f"  ❌ Không tìm thấy ô password! (URL: {page.url[:100]})")
                return None
    
            # ── Điền 2FA / TOTP ──
            if totp_secret:
                log(f"  🔐 Tìm ô 2FA...")
                for attempt in range(4):
                    tot = page.ele("tag:input@type=tel", timeout=5) or page.ele("#totpPin", timeout=3)
                    if tot:
                        code = _totp_now(totp_secret)
                        if code:
                            log(f"  🔐 Điền mã 2FA: {code}")
                            tot.clear()
                            tot.input(code)
                            time.sleep(0.6)
                            btn = None
                            for sel in ["#totpNext", "text:Tiếp theo", "text:Next", "tag:button@type=submit"]:
                                btn = page.ele(sel, timeout=3)
                                if btn: break
                            if btn:
                                btn.click()
                                log(f"  ✅ Đã nhấn Next (2FA)")
                            time.sleep(4)
                        break
                    time.sleep(2)

        # ── Chờ hoàn thành xác nhận đăng nhập (điện thoại/SMS) ──
        log(f"  ⏳ Đang chờ xác nhận đăng nhập trên Google (nếu có xác nhận điện thoại)...")
        wait_login_end = time.time() + 120
        while time.time() < wait_login_end:
            curr = page.url
            if "signin" not in curr and "challenge" not in curr:
                break
            time.sleep(2)

        # Nếu chưa ở labs, navigate đến
        if "labs.google" not in page.url:
            log(f"  🌐 Navigate về Flow (URL hiện tại: {page.url[:80]})...")
            page.get(LABS)
            time.sleep(5)

        # Chờ tối đa 35s để cookie xuất hiện và hợp lệ sau khi chuyển sang trang Flow
        end = time.time() + 35
        clicked_btn = False
        while time.time() < end:
            ck = _labs_cookie(page.cookies(all_domains=True))
            if _is_cookie_valid(ck):
                log(f"✅ {email}: login xong — có cookie hợp lệ!")
                return ck
            # Bấm nút Sign in / Create with Google Flow nếu có trên trang Labs (chỉ bấm 1 lần)
            if not clicked_btn:
                try:
                    for sel in ["text:Create with Google Flow", "text:Try Google Flow", "text:Sign in", "text:Đăng nhập", "text:Bắt đầu sáng tạo", "text:Get started", "tag:button@type=submit"]:
                        btn = page.ele(sel, timeout=1)
                        if btn:
                            btn.click(by_js=True)
                            clicked_btn = True
                            time.sleep(3)
                            break
                except Exception:
                    pass
            time.sleep(2)

        log(f"⚠️ {email}: chưa lấy được cookie hợp lệ sau khi login (URL: {page.url[:80]})")
        log(f"  💡 Có thể Google yêu cầu xác minh thêm (captcha, SMS, v.v.)")
        return None
    except Exception as e:
        log(f"login lỗi ({email}): {e}"); return None
    finally:
        try:
            if page: page.quit()
        except Exception:
            pass


# ============ 3) REOPEN PROFILE: mở Chrome profile cũ, Google tự login ============
def reopen_profile_cookie(profile_dir, log=print, timeout=120, poll=3):
    """Mở Chrome với profile CŨ (có sẵn session Google) → navigate tới Flow → Google tự đăng nhập →
    lấy cookie mới mà KHÔNG cần password/totp.
    Trả cookie (str) hoặc None (profile không tồn tại / session hết hạn / hết giờ)."""
    if not _has_profile_data(profile_dir):
        log(f"⚠️ Profile không có dữ liệu Chrome: {profile_dir}")
        return None
    try:
        from DrissionPage import ChromiumPage
    except Exception:
        log("Thiếu DrissionPage → chạy SETUP.bat"); return None
    page = None
    try:
        if profile_dir:
            check_and_convert_gemlogin_profile(profile_dir, log)
        log("🔄 Mở Chrome với profile cũ (không cần password)...")
        try:
            page = ChromiumPage(_opts(profile_dir))
        except Exception as e:
            if profile_dir:
                log(f"⚠️ Trình duyệt lỗi kết nối, đang thử tự động sửa chữa profile...")
                if repair_corrupted_profile(profile_dir, log):
                    page = ChromiumPage(_opts(profile_dir))
                else:
                    raise e
            else:
                raise e
        page.get(LABS)
        log("⏳ Chờ Google tự đăng nhập lại từ session cũ...")
        start_time = time.time()
        end = time.time() + timeout
        clicked_btn = False
        while time.time() < end:
            try:
                ck = _labs_cookie(page.cookies(all_domains=True))
            except Exception:
                return None   # Chrome đã đóng
            if _is_cookie_valid(ck):
                log("✅ Google tự đăng nhập lại → có cookie mới hợp lệ!")
                return ck
            
            # Thử bấm nút Sign in / Create with Google Flow bằng JavaScript click (chỉ bấm 1 lần)
            if not clicked_btn:
                try:
                    for sel in ["text:Create with Google Flow", "text:Try Google Flow", "text:Sign in", "text:Đăng nhập", "text:Bắt đầu sáng tạo", "text:Get started", "tag:button@type=submit"]:
                        btn = page.ele(sel, timeout=1)
                        if btn:
                            btn.click(by_js=True)
                            clicked_btn = True
                            time.sleep(3)
                            break
                except Exception:
                    pass

            # Kiểm tra thoát sớm nếu session đã chết và bị chuyển hướng sang form đăng nhập Google
            try:
                curr_url = page.url
                if "accounts.google.com/v3/signin/identifier" in curr_url or "signin/v2/identifier" in curr_url:
                    log("⌛ Session Google trong profile đã hết hạn (chuyển sang trang đăng nhập).")
                    return None
            except Exception:
                pass

            time.sleep(poll)
        log("⌛ Session Google trong profile đã hết hạn → cần dùng password.")
        return None
    except Exception as e:
        log(f"Lỗi mở profile: {e}")
        return None
    finally:
        try:
            if page: page.quit()
        except Exception:
            pass
