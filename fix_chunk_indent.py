import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '                    while True:\n                    chunk = resp.read(65536)\n                    if not chunk: break\n                    wf.write(chunk)',
    '                    while True:\n                        chunk = resp.read(65536)\n                        if not chunk: break\n                        wf.write(chunk)'
)

content = content.replace(
    '                              while True:\n                                chunk = _dl_resp.read(65536)\n                                if not chunk: break\n                                _dl_f.write(chunk)',
    '                              while True:\n                                  chunk = _dl_resp.read(65536)\n                                  if not chunk: break\n                                  _dl_f.write(chunk)'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
