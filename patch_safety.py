import os
import re

file_path = r'E:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

find_str = 'NEGATIVE DIRECTIVES: extra limbs, extra hands, extra arms, third arm, floating hands, six fingers.\\nOutput EXACTLY {n_segments} lines. One prompt per line.\\n"'
replace_str = 'CRITICAL: DO NOT use negative words like "extra limbs", "mutated", "deformed", or "missing fingers" in your output because the video AI will block it for safety. Instead, describe the anatomy POSITIVELY (e.g., "two perfectly normal hands", "natural five fingers").\\nOutput EXACTLY {n_segments} lines. One prompt per line.\\n"'

content = content.replace(find_str, replace_str)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
