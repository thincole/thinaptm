import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix signature
content = content.replace(
    'def _seed_ai_gen_prompts(self, product_name, scene_en, n_segments,\n                              product_desc=None,\n                              duration_sec, lang_code, review_style,\n                              mode="gemini", gemini_keys=None, groq_keys=None):',
    'def _seed_ai_gen_prompts(self, product_name, scene_en, n_segments,\n                              duration_sec, lang_code, review_style,\n                              mode="gemini", gemini_keys=None, groq_keys=None, product_desc=None):'
)

# Fix calls
content = content.replace(
    'product_desc=p.get("description", ""),  duration_sec',
    'duration_sec'
)
content = content.replace(
    'product_desc=p.get("description", ""), \n                              duration_sec',
    'duration_sec'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
