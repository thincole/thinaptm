import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

bad = '''                            if any(k in msg_lower for k in ["policy", "violation", "filter", "safety"]):
                                return "violation", msg
                            return "failed", msg'''

good = '''                            if any(k in msg_lower for k in ["policy", "violation", "filter", "safety"]):
                                return "violation", msg
                            return "failed", msg
                return "failed", "Timeout: KhA'ng nh-n ?c video sau 10 phAAt"'''

content = content.replace(bad, good)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
