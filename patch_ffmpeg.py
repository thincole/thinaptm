import re
import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add _ffmpeg_sem to __init__
if 'self._ffmpeg_sem' not in content:
    init_pattern = r'(self\._ui_queue = queue\.Queue\(\)\s+self\._poll_ui_queue\(\)\s+)'
    sem_code = "        import multiprocessing\n        self._ffmpeg_sem = threading.Semaphore(max(2, (multiprocessing.cpu_count() or 4) // 2))\n\n"
    content = re.sub(init_pattern, r'\g<1>' + sem_code, content)

# 2. Wrap ffmpeg subprocess call with Semaphore
ffmpeg_call_pattern = r'(startupinfo = subprocess\.STARTUPINFO\(\)\s+startupinfo\.dwFlags \|= subprocess\.STARTF_USESHOWWINDOW\s+try:\s+subprocess\.run\(cmd, stdout=subprocess\.PIPE, stderr=subprocess\.PIPE, check=True, startupinfo=startupinfo, timeout=120\))'

if 'self._ffmpeg_sem.acquire()' not in content:
    # also add -threads 2
    # cmd.extend(['-threads', '2'])
    
    threads_code = "        cmd.extend(['-threads', '2'])\n        self._ffmpeg_sem.acquire()\n"
    
    replacement = threads_code + r'        try:\n            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)\n        finally:\n            self._ffmpeg_sem.release()\n'
    
    # We replace the try: subprocess.run block
    content = re.sub(r'(\s+try:\s+subprocess\.run\(cmd, stdout=subprocess\.PIPE, stderr=subprocess\.PIPE, check=True, startupinfo=startupinfo, timeout=120\))', 
        r'\n        cmd.extend(["-threads", "2"])\n        self._ffmpeg_sem.acquire()\n\g<1>\n        finally:\n            self._ffmpeg_sem.release()', content)


with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched ffmpeg semaphore!")
