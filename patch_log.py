import os
import re
import time

file_path = r'E:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

init_find = '        self._seed_run_started_at = time.time()'
init_replace = '''        self._seed_run_started_at = time.time()
        # Xoa trang file log.txt khi khoi dong
        with open("log.txt", "w", encoding="utf-8") as f:
            f.write(f"--- PHIEN LAM VIEC MOI SEEDVIS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\\n")
'''

content = content.replace(init_find, init_replace)
content = content.replace('"logseedvis.txt"', '"log.txt"')
content = content.replace("'logseedvis.txt'", '"log.txt"')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
