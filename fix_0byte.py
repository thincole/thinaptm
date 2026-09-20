import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_func = False
for i, line in enumerate(lines):
    if line.startswith('    def _seed_download_image(self, image_url, save_path):'):
        in_func = True
        new_lines.append(line)
        continue
    
    if in_func:
        if line.startswith('    def '):
            in_func = False
        else:
            if '            return True' in line:
                new_lines.append('            if os.path.exists(save_path) and os.path.getsize(save_path) == 0:\n')
                new_lines.append('                os.remove(save_path)\n')
                new_lines.append('                return False\n')
                new_lines.append(line)
                continue
            if '        except Exception as e:' in line:
                new_lines.append(line)
                new_lines.append('            if os.path.exists(save_path):\n')
                new_lines.append('                try: os.remove(save_path)\n')
                new_lines.append('                except: pass\n')
                continue
            new_lines.append(line)
            continue
            
    new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Patched _seed_download_image!")
