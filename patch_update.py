import os

file_path = r'e:\ThinAptm0707\update.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

bad = '''def _is_ignored(path_str):
    low = path_str.lower().replace("\\\\", "/")
    if 'seedvis' in low or 'seedvid' in low:
        return True
    parts = low.split('/')'''

good = '''def _is_ignored(path_str):
    low = path_str.lower().replace("\\\\", "/")
    parts = low.split('/')'''

content = content.replace(bad, good)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
