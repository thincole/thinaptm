import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'product_desc=p.get("description", ""), \n                              duration_sec',
    'duration_sec'
)
content = content.replace(
    'product_desc=p.get("description", ""), \n                            duration_sec',
    'duration_sec'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
