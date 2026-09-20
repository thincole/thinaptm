import sys
import json
sys.path.append(r'E:\ThinAptm0707')
from seedvis_app import SeedvisApp

with open(r'E:\ThinAptm0707\settings.json', 'r', encoding='utf-8') as f:
    settings = json.load(f)
    keys = settings.get("gemini_keys", [])

app = SeedvisApp()
app.gemini_keys = keys
prompts = app._seed_ai_gen_prompts(
    "Test Product", "Studio", 1, "8s", "vi", "Review", mode="gemini", gemini_keys=keys
)
print("--- GENERATED PROMPTS ---")
for p in (prompts or []):
    print(p)
