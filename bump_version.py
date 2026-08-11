import re
import sys

def bump_version():
    filepath = "thin_aptm.py"
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_ver = ""
    def replace_ver(m):
        nonlocal new_ver
        prefix = m.group(1)
        major = m.group(2)
        minor = m.group(3)
        patch = int(m.group(4)) + 1
        new_ver = f"{prefix}{major}.{minor}.{patch}"
        return f'APP_VERSION = "{new_ver}"'

    new_content, count = re.subn(r'APP_VERSION\s*=\s*"([^"\d]*?)(\d+)\.(\d+)\.(\d+)"', replace_ver, content, count=1)
    
    if count > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(new_ver)
        with open("new_version.txt", "w", encoding="utf-8") as vf:
            vf.write(new_ver)
    else:
        print("ThinAPTM 1.2.0")

if __name__ == "__main__":
    bump_version()
