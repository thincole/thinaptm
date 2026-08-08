import sys

file_path = r'e:\ThinAptm0707\thin_aptm.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("https://api.homeproxy.vn/api/v1", "https://app.homeproxy.vn/api/v2")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
    
print("Replaced API URLs.")
