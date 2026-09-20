import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add _ui_queue initialization in __init__
if 'self._ui_queue = queue.Queue()' not in content:
    init_pattern = r'(self\._seed_log_flush_scheduled = False\s+)(self\._build_ui\(\))'
    replacement = r'\g<1>self._ui_queue = queue.Queue()\n        self._poll_ui_queue()\n\n        \g<2>'
    content = re.sub(init_pattern, replacement, content)

# 2. Add thread-safe after and _poll_ui_queue methods
new_methods = '''
    def _poll_ui_queue(self):
        try:
            while True:
                ms, func, args = self._ui_queue.get_nowait()
                super().after(ms, func, *args)
        except queue.Empty:
            pass
        super().after(100, self._poll_ui_queue)

    def after(self, ms, func=None, *args):
        if threading.current_thread() is threading.main_thread():
            return super().after(ms, func, *args)
        else:
            self._ui_queue.put((ms, func, args))
            return "queued"
'''
if 'def _poll_ui_queue' not in content:
    # Insert before _build_ui
    build_ui_pattern = r'(\s+def _build_ui\(self\):)'
    content = re.sub(build_ui_pattern, new_methods + r'\g<1>', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched successfully!")
