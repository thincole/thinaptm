import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_on_closing = '''    def _on_closing(self):
        self.withdraw()
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            def create_image():
                image = Image.new('RGB', (64, 64), color=(26, 115, 232))
                draw = ImageDraw.Draw(image)
                draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
                return image

            def on_show(icon, item):
                icon.stop()
                self.after(0, self.deiconify)
                
            def on_quit(icon, item):
                icon.stop()
                self._seed_stop_flag = True
                self._save_settings()
                self.after(0, self.destroy)
                
            menu = pystray.Menu(
                pystray.MenuItem('Hiển thị cửa sổ', on_show, default=True),
                pystray.MenuItem('Thoát hoàn toàn', on_quit)
            )
            
            icon = pystray.Icon("Seedvis", create_image(), "Thin Aptm - Seedvis", menu)
            import threading
            threading.Thread(target=icon.run, daemon=True).start()
        except ImportError:
            self._seed_stop_flag = True
            self._save_settings()
            self.destroy()
'''

content = re.sub(
    r'    def _on_closing\(self\):\s+self\._seed_stop_flag = True\s+self\._save_settings\(\)\s+self\.destroy\(\)',
    new_on_closing,
    content
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched _on_closing for minimize to tray!")
