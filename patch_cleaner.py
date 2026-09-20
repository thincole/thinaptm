import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

cleaner_code = '''
    def _start_temp_cleaner(self):
        def _cleaner_loop():
            import time
            import shutil
            while True:
                interval_mins = int(self.settings.get("seedvis_clean_interval", 60))
                time.sleep(interval_mins * 60)
                if getattr(self, '_seed_stop_flag', False):
                    break
                
                try:
                    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
                    if os.path.exists(temp_dir):
                        count = 0
                        for file in os.listdir(temp_dir):
                            # Skip recent files (less than 10 mins old) to avoid deleting active processing files!
                            filepath = os.path.join(temp_dir, file)
                            if time.time() - os.path.getmtime(filepath) > 600:
                                try:
                                    os.remove(filepath)
                                    count += 1
                                except Exception:
                                    pass
                        if count > 0:
                            self._seed_log_msg(f"  dYZz [Auto-Clean] dA? d?n d?p {count} file rAc trong temp_render.")
                except Exception:
                    pass
                    
        import threading
        threading.Thread(target=_cleaner_loop, daemon=True).start()
'''

if '_start_temp_cleaner' not in content:
    # Add method
    content = content.replace('    def _on_closing(self):', cleaner_code + '\n    def _on_closing(self):')
    
    # Call method in __init__
    content = content.replace('        self._poll_ui_queue()', '        self._poll_ui_queue()\n        self._start_temp_cleaner()')

# Add UI for setting
ui_code = '''
        self._seed_clean_interval = ctk.CTkEntry(row2, width=40, font=("", 11))
        self._seed_clean_interval.pack(side="left", padx=(12, 0))
        self._seed_clean_interval.insert(0, str(self.settings.get("seedvis_clean_interval", "60")))
        ctk.CTkLabel(row2, text="phAt d?n rAc", font=("", 11)).pack(side="left", padx=(2, 0))
'''

if 'seedvis_clean_interval' not in content:
    content = content.replace(
        'self._seed_chk_ghep_anh.pack(side="left", padx=(12, 0))',
        'self._seed_chk_ghep_anh.pack(side="left", padx=(12, 0))\n' + ui_code
    )

    # Save setting
    content = content.replace(
        '"seedvis_del_img": self._seed_del_img.get(),',
        '"seedvis_del_img": self._seed_del_img.get(),\n                  "seedvis_clean_interval": self._seed_clean_interval.get().strip(),'
    )

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
