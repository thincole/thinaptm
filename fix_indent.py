import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.startswith('self._build_ui()'):
        lines[i] = '        self._build_ui()\n'
    elif line.startswith('                import multiprocessing'):
        lines[i] = '        import multiprocessing\n'

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
