import os
import re

file_path = r'e:\ThinAptm0707\install.bat'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Update fallback pip install line
content = re.sub(
    r'%PYTHON_EXE% -m pip install customtkinter .*',
    '%PYTHON_EXE% -m pip install customtkinter curl_cffi pyreqwest_impersonate pillow edge-tts groq google-genai google-generativeai google-auth DrissionPage cryptography pyotp psutil requests httpx pystray opencv-python numpy websockets',
    content
)

# Update diagnostic import list
full_mods = "customtkinter, curl_cffi, pyreqwest_impersonate, PIL, edge_tts, groq, google.genai, google.auth, DrissionPage, cryptography, pyotp, psutil, requests, tkinter, httpx, pystray, cv2, numpy, websockets"

content = re.sub(
    r'%PYTHON_EXE% -c "import customtkinter.*?" >nul 2>&1',
    f'%PYTHON_EXE% -c "import {full_mods}; print(\'   [OK] TOAN BO THU VIEN PYTHON DA SAN SANG 100%!\')" >nul 2>&1',
    content
)

# Update the for loop in diagnostic
for_mods = "customtkinter curl_cffi pyreqwest_impersonate PIL edge_tts groq google.genai google.auth DrissionPage cryptography pyotp psutil requests tkinter httpx pystray cv2 numpy websockets"
content = re.sub(
    r'for %%M in \(customtkinter.*?\) do \(',
    f'for %%M in ({for_mods}) do (',
    content
)

# Update the success message from 14/14 to 19/19
content = content.replace("14/14 THU VIEN", "19/19 THU VIEN")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated install.bat!")
