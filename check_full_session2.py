import os
from datetime import datetime
import re

file_path = r'e:\ThinAptm0707\logseedvis.txt'
try:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    success = 0
    failed = 0
    
    # Extract all timestamps and find the last big gap (> 5 mins) to define the session start
    now = datetime.now()
    valid_lines = []
    for line in lines:
        match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
        if match:
            time_str = match.group(1)
            try:
                t = datetime.strptime(time_str, '%H:%M:%S')
                t = t.replace(year=now.year, month=now.month, day=now.day)
                valid_lines.append((t, line))
            except:
                pass
                
    if not valid_lines:
        print("No valid lines found")
        exit()

    # Find last gap > 10 minutes
    session_start_idx = 0
    for i in range(1, len(valid_lines)):
        prev_t = valid_lines[i-1][0]
        curr_t = valid_lines[i][0]
        # Calculate diff safely (ignoring midnight rollover for simple gap check since we only care about large gaps)
        diff = (curr_t - prev_t).total_seconds()
        if diff > 600 or diff < -40000: # gap > 10 mins OR negative gap (midnight rollover)
            session_start_idx = i

    session_lines = valid_lines[session_start_idx:]
    
    start_time = session_lines[0][0]
    end_time = session_lines[-1][0]

    for t, line in session_lines:
        if 'HoAn tt video' in line or 'Hoàn tất video' in line or 'HoA\\xef\\xbf\\xbdn t\\xef\\xbf\\xbd' in line or '4.mp4' in line or 'thA\\xef\\xbf\\xbdnh cA' in line or '.mp4' in line:
            if 'Ho' in line and 'video' in line:
                success += 1
        elif 'thất bại' in line or 'th\\xef\\xbf\\xbd' in line and 'b\\xef\\xbf\\xbd' in line:
            if 'Segment' in line or 'Submit' in line:
                failed += 1
                
    if start_time and end_time:
        if end_time < start_time:
            # Handle 1 midnight rollover
            duration_mins = ((end_time.timestamp() + 86400) - start_time.timestamp()) / 60
        else:
            duration_mins = (end_time - start_time).total_seconds() / 60
            
        speed = success / duration_mins if duration_mins > 0 else 0
        print(f"Thong ke phien hien tai (bat dau luc {start_time.strftime('%H:%M:%S')} den {end_time.strftime('%H:%M:%S')}):")
        print(f"- So video tao thanh cong: {success}")
        print(f"- So loi (failed/retry tu choi): {failed}")
        print(f"- Thoi gian hoat dong thuc te: {duration_mins:.2f} phut ({duration_mins/60:.2f} gio)")
        print(f"- Toc do trung binh: {speed:.2f} video/phut")
    else:
        print("Khong du du lieu de tinh toan.")
except Exception as e:
    print(e)
