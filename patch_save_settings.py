import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add save settings to _seed_claim_jobs
content = content.replace(
    'def _seed_claim_jobs(self):',
    'def _seed_claim_jobs(self):\n        self._save_settings()'
)

# Add save settings to _seed_start
content = content.replace(
    'def _seed_start(self):',
    'def _seed_start(self):\n        self._save_settings()'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
