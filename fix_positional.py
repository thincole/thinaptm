import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the positional argument error
content = content.replace(
    'product_desc=p.get("description", ""), \n                          duration_sec',
    'duration_sec'
)
content = content.replace(
    'product_desc=p.get("description", ""), \n                              duration_sec',
    'duration_sec'
)

# Insert it at the end
content = content.replace(
    'review_style, mode="gemini", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys',
    'review_style, mode="gemini", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys, product_desc=p.get("description", "")'
)
content = content.replace(
    'review_style, mode="groq", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys',
    'review_style, mode="groq", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys, product_desc=p.get("description", "")'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
