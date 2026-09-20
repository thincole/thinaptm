import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

bad = '''            def on_quit(icon, item):
                icon.stop()
                self._seed_stop_flag = True
                self._save_settings()
                self.after(0, self.destroy)'''

good = '''            def on_quit(icon, item):
                icon.stop()
                self._seed_stop_flag = True
                self._save_settings()
                # Dọn dẹp temp_render khi tắt phần mềm theo Rule #8
                try:
                    import shutil
                    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
                    if os.path.exists(temp_dir):
                        for file in os.listdir(temp_dir):
                            try:
                                os.remove(os.path.join(temp_dir, file))
                            except Exception:
                                pass
                except Exception:
                    pass
                self.after(0, self.destroy)'''

content = content.replace(bad, good)
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
