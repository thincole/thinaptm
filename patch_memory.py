import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace _seed_download_image read
content = content.replace(
    'wf.write(resp.read())',
    'while True:\n                    chunk = resp.read(65536)\n                    if not chunk: break\n                    wf.write(chunk)'
)

# Replace video download read
content = content.replace(
    '_dl_f.write(_dl_resp.read())',
    'while True:\n                                chunk = _dl_resp.read(65536)\n                                if not chunk: break\n                                _dl_f.write(chunk)'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Replaced read() with chunked read!")
