import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if 'cmd.extend(["-threads", "2"])' in line:
        new_lines.append('            cmd.extend(["-threads", "2"])\n')
        new_lines.append('            self._ffmpeg_sem.acquire()\n')
        new_lines.append('            try:\n')
        new_lines.append('                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)\n')
        new_lines.append('                return True, ""\n')
        new_lines.append('            finally:\n')
        new_lines.append('                self._ffmpeg_sem.release()\n')
        continue
    
    if 'self._ffmpeg_sem.acquire()' in line:
        continue
    
    if 'try:' in line and 'subprocess.run(cmd' in lines[i+1] if i+1 < len(lines) else False:
        # We already replaced it
        continue
    if 'subprocess.run(cmd' in line and 'check=True' in line and 'timeout=120' in line:
        continue
    if 'finally:' in line and 'self._ffmpeg_sem.release()' in lines[i+1] if i+1 < len(lines) else False:
        continue
    if 'self._ffmpeg_sem.release()' in line:
        continue
    if 'return True, ""' in line and 'self._ffmpeg_sem.release()' in lines[i-1] if i > 0 else False:
        continue
        
    new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Fixed indentation!")
