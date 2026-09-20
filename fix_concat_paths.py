import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'concat_path = os.path.join(temp_dir, f"seed_{item_id}_concat.mp4")',
    'concat_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_concat.mp4")'
)

content = content.replace(
    'merged_path = os.path.join(temp_dir, f"seed_{item_id}_merged12s.mp4")',
    'merged_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_merged12s.mp4")'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched concat_path and merged_path!")
