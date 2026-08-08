import sys

with open(r'e:\ThinAptm0707\thin_aptm.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'self.proxy_pool =' in line:
        print('1', i, line.strip())
    elif 'self._update_proxy_stats()' in line:
        print('2', i, line.strip())
    elif 'def _on_recaptcha_mode_change' in line:
        print('3', i, line.strip())
    elif 'if self._cached_px_lines:' in line:
        print('4', i, line.strip())
    elif 'disable_proxy' in line:
        print('5', i, line.strip())
    elif 'if _cached_px_lines: self.proxy_pool.load(_cached_px_lines)' in line:
        print('6', i, line.strip())
