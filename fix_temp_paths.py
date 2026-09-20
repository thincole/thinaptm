import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'clip_path = os.path.join(temp_dir, f"seed_{item_id}_seg{seg_idx}.mp4")',
    'clip_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_seg{seg_idx}.mp4")'
)

content = content.replace(
    'out_12s = os.path.join(temp_dir, f"12s_{item_id}.mp4")',
    'out_12s = os.path.join(temp_dir, f"12s_{item_id}_{idx}.mp4")'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched temp paths to be unique per task!")
