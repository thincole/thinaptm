"""Theo doi log.txt cua ThinAPTM moi 20 phut: dem video/loi/gan co/xoay IP trong tung
khoang, doi chieu voi accounts.json (rate_gov/upload_threads/proxy hien tai), in ra man
hinh + gui bao cao qua Telegram (dung dung bot token/chat_id da cau hinh trong settings.json).
Chay doc lap, khong dung ThinAPTM."""
import json, os, re, time, sys, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "log.txt")
ACC_FILE = os.path.join(HERE, "accounts.json")
SETTINGS_FILE = os.path.join(HERE, "settings.json")
STATE_FILE = os.path.join(HERE, "_monitor_state.json")
INTERVAL_SEC = 20 * 60

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RE_VIDEO_OK = re.compile(r"✅ Video:")
RE_ERROR = re.compile(r"❌")
RE_WARN = re.compile(r"⚠️")
RE_FLAG = re.compile(r"🚩.*?gắn cờ")
RE_IP_BURN = re.compile(r"🔥.*?nghi IP đã cháy")
RE_IP_ROTATE_OK = re.compile(r"✅.*?Đăng nhập lại thành công qua IP mới")
RE_RECONNECT = re.compile(r"Tự mở lại trình duyệt.*?thành công")
RE_ACC_TAG = re.compile(r"\[([a-zA-Z0-9_.]{4,20})\]")


def load_state():
    if os.path.isfile(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {"offset": 0}


def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))


def read_new_lines(offset):
    if not os.path.isfile(LOG_FILE):
        return [], offset
    size = os.path.getsize(LOG_FILE)
    if size < offset:
        offset = 0  # log.txt bi ghi lai tu dau (app restart) -> doc lai tu dau
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        lines = f.readlines()
        new_offset = f.tell()
    return lines, new_offset


def summarize(lines):
    videos = sum(1 for l in lines if RE_VIDEO_OK.search(l))
    errors = sum(1 for l in lines if RE_ERROR.search(l))
    warns = sum(1 for l in lines if RE_WARN.search(l))
    flags = [l.strip() for l in lines if RE_FLAG.search(l)]
    ip_burn = [l.strip() for l in lines if RE_IP_BURN.search(l)]
    ip_rotated = [l.strip() for l in lines if RE_IP_ROTATE_OK.search(l)]
    reconnects = sum(1 for l in lines if RE_RECONNECT.search(l))
    accounts_seen = set()
    for l in lines:
        m = RE_ACC_TAG.search(l)
        if m:
            accounts_seen.add(m.group(1))
    return {
        "videos": videos, "errors": errors, "warns": warns,
        "flags": flags, "ip_burn": ip_burn, "ip_rotated": ip_rotated,
        "reconnects": reconnects, "accounts_seen": accounts_seen,
    }


def load_accounts_snapshot():
    try:
        accs = json.load(open(ACC_FILE, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for a in accs:
        if not a.get("enabled", True):
            continue
        rg = a.get("rate_gov") or {}
        out.append({
            "email": a.get("email", "?"),
            "status": a.get("status", "?"),
            "upload_threads": a.get("upload_threads"),
            "rate_limit": rg.get("limit"),
            "rate_ceiling": rg.get("ceiling"),
            "unusual_count": rg.get("unusual_count"),
            "proxy": (a.get("proxy") or "?").split("@")[-1][:34],
        })
    return out


def send_telegram(text):
    try:
        s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
    except Exception:
        return
    token, chat_id = s.get("tg_token"), s.get("tg_chatid")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"[monitor] Gửi Telegram lỗi: {e}")


def build_report(stats, accs, minutes):
    rate = stats["videos"] / minutes if minutes > 0 else 0.0
    lines = [
        f"📊 ThinAPTM — {minutes:.0f} phút qua",
        f"  ✅ Video: {stats['videos']} ({rate:.2f} video/phút)",
        f"  ❌ Lỗi: {stats['errors']}  |  ⚠️ Cảnh báo: {stats['warns']}  |  🔌 Tự kết nối lại: {stats['reconnects']}",
    ]
    if stats["flags"]:
        lines.append(f"  🚩 Gắn cờ UNUSUAL_ACTIVITY: {len(stats['flags'])} lần")
        for f in stats["flags"][-3:]:
            lines.append(f"     {f}")
    if stats["ip_burn"]:
        lines.append(f"  🔥 Nghi IP cháy: {len(stats['ip_burn'])} lần")
    if stats["ip_rotated"]:
        lines.append(f"  🔄 Xoay IP thành công: {len(stats['ip_rotated'])} lần")
    if accs:
        lines.append("  — Trạng thái tài khoản —")
        for a in accs:
            lines.append(
                f"     {a['email'][:20]:20s} {a['status']:5s} "
                f"upload={a['upload_threads']} rate={a['rate_limit']} "
                f"trần={a['rate_ceiling']} gắn_cờ_2h={a['unusual_count']} "
                f"proxy={a['proxy']}"
            )
    return "\n".join(lines)


def main():
    print(f"[monitor] Bắt đầu theo dõi {LOG_FILE} — mỗi {INTERVAL_SEC//60} phút. Ctrl+C để dừng.")
    state = load_state()
    last_ts = time.time()
    while True:
        time.sleep(INTERVAL_SEC)
        now = time.time()
        minutes = (now - last_ts) / 60.0
        last_ts = now

        lines, new_offset = read_new_lines(state.get("offset", 0))
        state["offset"] = new_offset
        save_state(state)

        stats = summarize(lines)
        accs = load_accounts_snapshot()
        report = build_report(stats, accs, minutes)
        print("\n" + "=" * 60)
        print(time.strftime("%H:%M:%S"), "—", report)
        send_telegram(report)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[monitor] Đã dừng.")
