import os
import ast

def get_imports(filepath):
    imports = set()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.add(name.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except:
        pass
    return imports

all_imports = set()
for root, dirs, files in os.walk(r'e:\ThinAptm0707'):
    if '__pycache__' in root or '.git' in root: continue
    for file in files:
        if file.endswith('.py'):
            all_imports.update(get_imports(os.path.join(root, file)))

stdlib = set(["os", "sys", "time", "json", "threading", "queue", "urllib", "subprocess", "random", "re", "multiprocessing", "datetime", "base64", "hashlib", "math", "sqlite3", "tempfile", "shutil", "traceback", "logging", "ctypes", "winreg", "socket", "pathlib", "concurrent", "uuid", "hmac", "struct", "io", "string", "itertools", "collections", "functools", "typing"])
external = sorted(list(all_imports - stdlib))
print("External imports found:")
print(external)
