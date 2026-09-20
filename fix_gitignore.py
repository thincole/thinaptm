import os
file_path = r'e:\ThinAptm0707\.gitignore'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if line.strip() == '# Seedvis / Seedvid (Private - Do not upload to GitHub)':
        skip = True
    elif skip and line.strip() == '':
        skip = False
        continue
    
    if not skip:
        new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
