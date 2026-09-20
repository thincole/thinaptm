import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add creationflags to hide windows completely
content = content.replace(
    'result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo)',
    'result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo, creationflags=0x08000000)'
)
content = content.replace(
    'subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)',
    'subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120, creationflags=0x08000000)'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
