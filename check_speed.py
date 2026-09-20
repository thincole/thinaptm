import os
from datetime import datetime, timedelta
import re

file_path = r'e:\ThinAptm0707\logseedvis.txt'
try:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    success = 0
    failed = 0
    start_time = None
    end_time = None

    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    
    for line in lines:
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
        if match:
            time_str = match.group(1)
            try:
                t = datetime.strptime(time_str, '%H:%M:%S')
                t = t.replace(year=now.year, month=now.month, day=now.day)
                if t > now:
                    t = t - timedelta(days=1)
                
                if t >= one_hour_ago:
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
        print(f"Trong 1 gio qua:")
        print(f"- So video tao thanh cong: {success}")
        print(f"- So loi (failed/retry): {failed}")
        print(f"- Thoi gian hoat dong thuc te: {duration_mins:.2f} phut")
        print(f"- Toc do trung binh: {speed:.2f} video/phut")
    else:
        print("Khong co du lieu trong 1 gio qua, hoac loi parse the loai.")
except Exception as e:
    print(e)
