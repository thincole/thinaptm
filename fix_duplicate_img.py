import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace img_path = ...
content = content.replace(
    'img_path = os.path.join(temp_dir, f"{item_id}.jpg")',
    'img_path = os.path.join(temp_dir, f"{item_id}_{idx}.jpg")'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Replaced img_path with unique id!")
