import os
import re

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Update _seed_ai_gen_prompts signature
content = content.replace(
    'def _seed_ai_gen_prompts(self, product_name, scene_en, n_segments,',
    'def _seed_ai_gen_prompts(self, product_name, scene_en, n_segments,\n                              product_desc=None,'
)

# Update the System Prompt in _seed_ai_gen_prompts
sys_prompt_find = '''        sys_prompt = f"""
You are an expert video director creating highly realistic, TikTok/Shopee-style review videos.
Your task is to write {n_segments} scene prompts for a product named "{product_name}".'''

sys_prompt_replace = '''        desc_text = f"\\nProduct Description:\\n{product_desc}\\n" if product_desc else ""
        sys_prompt = f"""
You are an expert video director creating highly realistic, TikTok/Shopee-style review videos.
Your task is to write {n_segments} scene prompts for a product named "{product_name}".{desc_text}
Use the product description to make the script and visual actions highly relevant and attractive.
'''

content = content.replace(sys_prompt_find, sys_prompt_replace)

# Pass product_desc when calling _seed_ai_gen_prompts in work() and test()
content = content.replace(
    'prompts = self._seed_ai_gen_prompts(\n                        prod_name, scene_en, n_segments,',
    'prompts = self._seed_ai_gen_prompts(\n                        prod_name, scene_en, n_segments, product_desc=p.get("description", ""), '
)
content = content.replace(
    'prompts = self._seed_ai_gen_prompts(\n                            product_name, scene_en, n_segments_needed,',
    'prompts = self._seed_ai_gen_prompts(\n                            product_name, scene_en, n_segments_needed, product_desc=p.get("description", ""), '
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
