import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    if 'cmd.extend(["-threads", "2"])' in line:
        # We are at the start of the block
        # Let's remove the broken finally block and just wrap it cleanly
        new_lines.append(line)
        new_lines.append(lines[i+1]) # self._ffmpeg_sem.acquire()
        new_lines.append('            try:\n')
        
        # Skip the old 'try:', the subprocess.run, return, finally, release, excepts...
        # Wait, it's easier to just do string replacement on the file content.
        break
    else:
        new_lines.append(line)
        i += 1
