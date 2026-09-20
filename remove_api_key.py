import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace hardcoded default settings dictionary
content = content.replace(
    '"seedvis_api_key": "sv_live_706e3c3bb5c7080909769c77651beee1a760e89ef36bc68e810ff971049781ff",',
    '"seedvis_api_key": "",'
)

# Replace hardcoded default API key string
content = content.replace(
    'default_seed_key = self.settings.get("seedvis_api_key", "sv_live_706e3c3bb5c7080909769c77651beee1a760e89ef36bc68e810ff971049781ff")',
    'default_seed_key = self.settings.get("seedvis_api_key", "")'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
