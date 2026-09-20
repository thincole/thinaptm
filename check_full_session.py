import os
from datetime import datetime
import re

file_path = r'e:\ThinAptm0707\logseedvis.txt'
try:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    # Find the start of the current session
    # A session typically starts with something like "Bat dau" or a large row of =====
    # But to be robust, we can look for "Thiet lap Seedvis API Key..." or "Dang kiem tra ket noi..." 
    # Or we just find the last time the progress was [1/5000]!
    
    session_lines = []
    current_session = []
    
    for line in lines:
        if re.search(r'\[1/\d+\]', line): # [1/5000]
            current_session = [line]
        elif 'Bắt đầu' in line or 'B\\xef\\xbf\\xbd\\xef\\xbf\\xbdt \\xef\\xbf\\xbd\\xef\\xbf\\xbd' in line:
            # Maybe start of session
            current_session.append(line)
        else:
            current_session.append(line)

    success = 0
    failed = 0
    start_time = None
    end_time = None

    now = datetime.now()
    
    for line in current_session:
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
        if match:
            time_str = match.group(1)
            try:
                t = datetime.strptime(time_str, '%H:%M:%S')
                t = t.replace(year=now.year, month=now.month, day=now.day)
                
                # handle midnight rollover roughly
                if end_time and t < end_time and (end_time - t).total_seconds() > 43200:
                    t = t + timedelta(days=1)
                
                if not start_time:
                    start_time = t
                end_time = t
                
                if 'HoAn tt video' in line or 'Hoàn tất video' in line or 'HoA\\xef\\xbf\\xbdn t\\xef\\xbf\\xbd' in line or '4.mp4' in line or 'thA\\xef\\xbf\\xbdnh cA' in line or '.mp4' in line:
                    if 'Ho' in line and 'video' in line:
                        success += 1
                elif 'thất bại' in line or 'th\\xef\\xbf\\xbd' in line and 'b\\xef\\xbf\\xbd' in line:
                    if 'Segment' in line or 'Submit' in line:
                        failed += 1
            except Exception:
                pass
                
    if start_time and end_time and end_time > start_time:
        duration_mins = (end_time - start_time).total_seconds() / 60
        speed = success / duration_mins if duration_mins > 0 else 0
        print(f"Thong ke tu dau phien (bat dau luc {start_time.strftime('%H:%M:%S')} den {end_time.strftime('%H:%M:%S')}):")
        print(f"- So video tao thanh cong: {success}")
        print(f"- So loi (failed/retry): {failed}")
        print(f"- Thoi gian hoat dong thuc te: {duration_mins:.2f} phut ({duration_mins/60:.2f} gio)")
        print(f"- Toc do trung binh: {speed:.2f} video/phut")
    else:
        print("Khong du du lieu de tinh toan.")
except Exception as e:
    print(e)
