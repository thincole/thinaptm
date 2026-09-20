import os
import re
import base64

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add release-jobs on quit
on_quit_replace = '''
            def on_quit(icon, item):
                icon.stop()
                self._seed_stop_flag = True
                self._save_settings()
                try:
                    c_id = self._seed_client_entry.get().strip()
                    if c_id:
                        self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": c_id})
                except Exception:
                    pass
'''
content = re.sub(r'def on_quit\(icon, item\):\s*icon\.stop\(\)\s*self\._seed_stop_flag = True\s*self\._save_settings\(\)', on_quit_replace.strip(), content)


# 2. Add img_path to _seed_ai_gen_prompts
content = content.replace(
    'mode="gemini", gemini_keys=None, groq_keys=None, product_desc=None):',
    'mode="gemini", gemini_keys=None, groq_keys=None, product_desc=None, img_path=None):'
)

# 3. Add img_path passing in work()
content = content.replace(
    'product_desc=p.get("description", "")\n                    )',
    'product_desc=p.get("description", ""), img_path=img_path\n                    )'
)

# 4. Modify the payload logic in _seed_ai_gen_prompts
payload_old = '''                    parts = [{"text": sys_prompt}]
                    payload = {
                        "contents": [{"parts": parts}],
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800}
                    }'''

payload_new = '''                    parts = []
                    if img_path and os.path.exists(img_path):
                        import base64
                        with open(img_path, "rb") as imf:
                            b64_img = base64.b64encode(imf.read()).decode('utf-8')
                        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_img}})
                        sys_prompt += "\\n\\n[VISION ANALYSIS]: Look at the attached product image. If the image already shows hands holding the product (POV), you MUST LOCK the perspective to POV and absolutely DO NOT add a presenter or face. If it's a standalone product, you can use a presenter but strictly LOCK hand anatomy to 2 hands attached to shoulders."
                        
                    parts.append({"text": sys_prompt})
                    payload = {
                        "contents": [{"parts": parts}],
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800}
                    }'''
content = content.replace(payload_old, payload_new)

# Add negative prompt to sys_prompt
negative_old = 'Output EXACTLY {n_segments} lines. One prompt per line.\\n"'
negative_new = 'NEGATIVE DIRECTIVES: extra limbs, extra hands, extra arms, third arm, floating hands, six fingers.\\nOutput EXACTLY {n_segments} lines. One prompt per line.\\n"'
content = content.replace(negative_old, negative_new)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
