import sys

with open(r'e:\ThinAptm0707\thin_aptm.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open(r'e:\ThinAptm0707\lines_output.txt', 'w', encoding='utf-8') as f_out:
    for i, line in enumerate(lines):
        if 'self.proxy_pool =' in line:
            f_out.write(f'1 {i} {line.strip()}\n')
        elif 'self._update_proxy_stats()' in line:
            f_out.write(f'2 {i} {line.strip()}\n')
        elif 'def _on_recaptcha_mode_change' in line:
            f_out.write(f'3 {i} {line.strip()}\n')
        elif 'if self._cached_px_lines:' in line:
            f_out.write(f'4 {i} {line.strip()}\n')
        elif '"disable_proxy": self.disable_proxy.get(),' in line:
            f_out.write(f'5 {i} {line.strip()}\n')
        elif 'if _cached_px_lines: self.proxy_pool.load(_cached_px_lines)' in line:
            f_out.write(f'6 {i} {line.strip()}\n')
