"""
Prompt Templates — Thư viện template tạo prompt Veo tự động.
Không cần API AI. Hoạt động hoàn toàn offline.

Cách dùng:
  1. Viết outline trong file .txt theo format đơn giản
  2. Chạy: python prompt_templates.py outline.txt -o prompts_output.txt
  3. Nạp prompts_output.txt vào Thìn Aptm

Format outline:
  TIEU_DE: 4 điều im lặng
  STYLE: stickman          (stickman / anime / realistic / chibi)

  ---
  TEXT: 4 ĐIỀU IM LẶNG
  MOOD: dramatic
  SCENE: tsunami

  ---
  TEXT: Khi ai đó khiến bạn tức giận
  MOOD: angry
  SCENE: pressure_gauge
"""

import os, sys, re, argparse, random

# ═══════════════════════════════════════════════════════════════
# CHARACTER STYLES — Phong cách nhân vật
# ═══════════════════════════════════════════════════════════════
CHAR_STYLES = {
    "stickman": "minimalist character with round white featureless head, wearing grey t-shirt and dark pants, simple body proportions",
    "stickman_hoodie": "minimalist character with round white featureless head, wearing dark hoodie and black pants, simple body proportions",
    "anime": "anime-style young male character with dark messy hair, wearing casual dark clothing, expressive eyes",
    "chibi": "cute chibi-style character with oversized round head, small body, minimal facial features, wearing simple grey outfit",
    "realistic": "photorealistic young man in casual dark clothing, dramatic cinematic lighting, moody atmosphere",
    "silhouette": "dark silhouette of a person, strong backlit dramatic lighting, cinematic shadow art style",
    "robot": "small cute robot character with round glowing head, metallic grey body, simple geometric design",
}

# ═══════════════════════════════════════════════════════════════
# SCENE TEMPLATES — Thư viện cảnh (50+ template)
# ═══════════════════════════════════════════════════════════════
# Mỗi template: (mô tả cảnh tiếng Anh, mood mặc định)
# {char} sẽ được thay bằng character style

SCENE_TEMPLATES = {
    # ── MỞ ĐẦU / INTRO ──
    "tsunami": (
        "2D animation style, {char}, standing small at the bottom center facing a massive towering dark tsunami wave made of jagged rocks and lightning, "
        "bold large yellow Vietnamese title text centered on screen, deep dark navy blue background, dramatic cinematic lighting",
        "dramatic"
    ),
    "portal": (
        "2D animation style, {char}, standing before a massive glowing portal with swirling energy in purple and gold, "
        "bold title text centered, dark mysterious background with floating particles",
        "mysterious"
    ),
    "giant_doors": (
        "2D animation style, {char}, standing alone in a dark room looking up at giant glowing golden doors, "
        "each door has a different symbol, bold yellow title text centered, deep dark background with subtle blue fog",
        "dramatic"
    ),
    "crossroads": (
        "2D animation style, {char}, standing at a dramatic crossroads with multiple dark paths diverging, "
        "the center path glows faintly golden, bold title text centered, dark atmospheric fog background",
        "mysterious"
    ),
    "cliff_edge": (
        "2D animation style, {char}, standing at the edge of a massive cliff overlooking an endless dark void below, "
        "bold title text centered, dramatic wind effect, dark moody atmosphere with distant lightning",
        "dramatic"
    ),
    "mirror": (
        "2D animation style, {char}, standing before a giant cracked mirror showing a stronger version of themselves, "
        "bold title text centered, dark room with dramatic spotlight, metaphor for self-reflection",
        "introspective"
    ),

    # ── CẢM XÚC / EMOTIONAL ──
    "pressure_gauge": (
        "2D animation style, {char} with angry expression and clenched fists, standing in front of a giant cracked "
        "pressure gauge meter pointing to red DANGER zone, dramatic red lightning bolts, intense speed lines radiating from center, dark grey background",
        "angry"
    ),
    "fire_rage": (
        "2D animation style, {char} surrounded by raging flames and fire, fists clenched with intense expression, "
        "dark red and orange atmosphere, dramatic lighting, metaphor for uncontrolled anger",
        "angry"
    ),
    "rain_sad": (
        "2D animation style, {char} sitting alone in heavy rain on a bench, head down, puddles reflecting dim streetlight, "
        "dark blue melancholic atmosphere, metaphor for loneliness and sadness",
        "sad"
    ),
    "broken_heart": (
        "2D animation style, {char} kneeling on ground, a giant glowing heart above shattering into pieces, "
        "red and dark atmosphere, dramatic lighting, emotional pain metaphor",
        "sad"
    ),
    "crying_rain": (
        "2D animation style, {char} standing in the rain looking up at dark clouds, rain drops mixing with tears, "
        "dim blue lighting, lonely empty street, melancholic atmosphere",
        "sad"
    ),
    "mask_fake": (
        "2D animation style, {char} holding a smiling mask in front of their face but their real expression is sad behind it, "
        "dark background with spotlight, metaphor for hiding true emotions",
        "melancholic"
    ),

    # ── BẾ TẮC / CONFUSION ──
    "tangled_ropes": (
        "2D animation style, {char} kneeling on ground looking at a massive tangled mess of thick grey ropes and cables "
        "with one glowing orange thread, single dramatic spotlight beam from above, dark moody grey atmosphere, metaphor for confusion",
        "confused"
    ),
    "maze": (
        "2D animation style, {char} standing inside a massive dark stone maze, walls towering above, "
        "one faint light visible far away at the end, dark atmospheric lighting, metaphor for feeling lost",
        "confused"
    ),
    "sinking_sand": (
        "2D animation style, {char} slowly sinking into dark quicksand, reaching one hand up toward a distant light above, "
        "dark desperate atmosphere, metaphor for being stuck and overwhelmed",
        "desperate"
    ),
    "chains": (
        "2D animation style, {char} bound by heavy dark chains attached to the ground, straining to break free, "
        "dark dungeon-like background with a crack of light from above, metaphor for being trapped",
        "trapped"
    ),
    "fog_lost": (
        "2D animation style, {char} walking alone through thick dense fog, can barely see anything, "
        "holding a tiny flickering candle, dark eerie atmosphere, metaphor for uncertainty",
        "lost"
    ),

    # ── SỨC MẠNH / STRENGTH ──
    "climbing_stairs": (
        "2D animation style, {char} with determined fierce expression, climbing up glowing golden illuminated stone stairs "
        "that rise upward, bright orange flames burning behind at the bottom, dark stone circular well platform below, dramatic lighting",
        "determined"
    ),
    "lifting_weight": (
        "2D animation style, {char} lifting a heavy barbell made of dark storm clouds and lightning, "
        "feet planted firmly on cracked ground, small smile on face despite struggle, metaphor for embracing difficulty, dark red and warm lighting",
        "strong"
    ),
    "breaking_wall": (
        "2D animation style, {char} punching through a massive dark brick wall, cracks spreading outward with golden light "
        "bursting through, debris flying, metaphor for breaking through limitations, dramatic action scene",
        "powerful"
    ),
    "standing_storm": (
        "2D animation style, {char} standing firm like a mountain while a chaotic storm of arrows and sharp objects fly past "
        "but miss, the character is calm and unbothered, metaphor for emotional control, dramatic dark background",
        "calm_strength"
    ),
    "sword_draw": (
        "2D animation style, {char} drawing a glowing golden sword from a stone, dramatic light erupting upward, "
        "dark cave background, epic heroic moment, metaphor for unlocking inner power",
        "heroic"
    ),
    "mountain_top": (
        "2D animation style, {char} standing on top of a tall mountain peak planting a flag, "
        "vast landscape below with clouds, sunrise golden light, feeling of achievement and conquest",
        "triumphant"
    ),
    "shield_block": (
        "2D animation style, {char} holding up a glowing shield that blocks incoming dark arrows and projectiles, "
        "standing protectively, dramatic sparks flying, metaphor for resilience and defense",
        "defensive"
    ),

    # ── BÌNH YÊN / PEACE ──
    "meditation": (
        "2D animation style, {char} sitting in meditation pose on top of a tall mountain peak above the clouds, "
        "golden sunrise behind them, eagles flying in the distance, peaceful yet powerful atmosphere",
        "peaceful"
    ),
    "lotus_thorns": (
        "2D animation style, {char} holding a glowing white lotus flower, surrounded by sharp red thorns and spikes "
        "attacking from the left side, dark green forest background, contrast between beauty and danger, soft glow around lotus, metaphor for kindness in hostile world",
        "gentle"
    ),
    "tree_growth": (
        "2D animation style, {char} sitting under a massive ancient tree with glowing golden leaves, "
        "reading a book, peaceful warm sunlight filtering through branches, metaphor for wisdom and patience",
        "peaceful"
    ),
    "garden_tend": (
        "2D animation style, {char} carefully tending a small glowing garden of flowers in the middle of a dark wasteland, "
        "soft warm light emanating from the garden, contrast with dark surroundings, metaphor for nurturing goodness",
        "hopeful"
    ),
    "stargazing": (
        "2D animation style, {char} lying on grass looking up at a magnificent starry night sky with galaxies visible, "
        "peaceful serene atmosphere, soft moonlight, metaphor for seeing the bigger picture",
        "contemplative"
    ),

    # ── CÔ ĐƠN / SOLITUDE ──
    "alone_table": (
        "2D animation style, {char} sitting alone at a table in a dark room, other shadowy figures partying in the blurry background, "
        "the character is reading a book with a soft warm light around them, metaphor for choosing solitude over crowd",
        "solitary"
    ),
    "walking_alone": (
        "2D animation style, {char} walking alone on a long empty road stretching into the horizon, "
        "dark sky with a single star, quiet peaceful atmosphere, metaphor for choosing one's own path",
        "solitary"
    ),
    "island_one": (
        "2D animation style, {char} sitting on a small island in the middle of a vast dark ocean, "
        "single tree beside them, distant city lights on the horizon, metaphor for self-isolation and independence",
        "isolated"
    ),

    # ── ĐỐI LẬP / CONTRAST ──
    "bridge_choice": (
        "2D animation style, {char} standing on one side of a broken bridge, the other side has gold coins and luxury items, "
        "the character turns away choosing a narrow forest path, metaphor for choosing values over materialism",
        "thoughtful"
    ),
    "light_dark": (
        "2D animation style, split scene showing {char} — left half is dark chaotic with monsters, right half is bright peaceful with flowers, "
        "the character steps from dark to light side, metaphor for choosing positivity, dramatic lighting contrast",
        "transformative"
    ),
    "wolf_sheep": (
        "2D animation style, {char} standing between a fierce wolf (representing strength) and a gentle lamb (representing kindness), "
        "dramatic dark background with spotlight on the character choosing to have both, metaphor for balance",
        "balanced"
    ),
    "puppet_free": (
        "2D animation style, {char} cutting puppet strings attached to their arms and legs, rising free while a dark puppet master "
        "figure fades into shadow above, metaphor for breaking free from control, dramatic lighting",
        "liberating"
    ),

    # ── KẾT THÚC / ENDING ──
    "sunset_walk": (
        "2D animation style, {char} walking alone on dark ground toward a distant golden sunset on the horizon, "
        "glowing golden footprints trail behind the character, dark peaceful moody atmosphere, cinematic lighting, emotional ending scene",
        "hopeful_ending"
    ),
    "sunrise_cliff": (
        "2D animation style, {char} standing at a cliff edge watching a beautiful sunrise, arms spread wide, "
        "vast landscape below bathed in golden light, feeling of new beginning and hope, inspirational ending",
        "inspirational"
    ),
    "seed_plant": (
        "2D animation style, {char} planting a small glowing golden seed in dark soil, tiny sprout growing with light "
        "emanating from it, dark background with a hint of dawn on the horizon, metaphor for patience and growth, hopeful ending",
        "hopeful_ending"
    ),
    "star_path": (
        "2D animation style, {char} walking on a path made of glowing stars leading upward into a bright sky, "
        "leaving darkness behind below, cinematic wide shot, metaphor for ascending to a better version, inspirational ending",
        "inspirational"
    ),
    "phoenix": (
        "2D animation style, {char} standing as a massive golden phoenix rises behind them from flames, "
        "dramatic upward shot, dark background illuminated by phoenix fire, metaphor for rebirth and transformation, epic ending",
        "epic_ending"
    ),
    "ocean_calm": (
        "2D animation style, {char} standing on a calm shore, dark storms receding in the background, "
        "peaceful ocean reflecting moonlight ahead, metaphor for peace after struggle, serene ending atmosphere",
        "serene_ending"
    ),
    "door_open": (
        "2D animation style, {char} pushing open a massive ornate door revealing brilliant golden light flooding in, "
        "stepping forward confidently into the light, dark room behind, metaphor for new chapter, hopeful ending",
        "hopeful_ending"
    ),

    # ── QUAN HỆ / RELATIONSHIPS ──
    "backstab": (
        "2D animation style, {char} with a knife stuck in their back, looking forward undeterred, "
        "shadowy figure fading behind them, dark dramatic atmosphere, metaphor for betrayal but staying strong",
        "betrayed"
    ),
    "helping_hand": (
        "2D animation style, {char} reaching down a cliff to help pull another character up, "
        "dramatic lighting from above, metaphor for helping others, warm golden light on the hand connection",
        "compassionate"
    ),
    "toxic_crowd": (
        "2D animation style, {char} walking away from a group of dark shadowy figures pulling at them, "
        "heading toward a bright light ahead, metaphor for leaving toxic environment, dramatic contrast",
        "resolute"
    ),
    "crown_earn": (
        "2D animation style, {char} forging their own golden crown at an anvil with hammer and sparks, "
        "dark workshop background, metaphor for earning respect through hard work, warm dramatic lighting",
        "determined"
    ),
}

# ═══════════════════════════════════════════════════════════════
# MOOD SUFFIXES — Hậu tố mood thêm vào cuối prompt
# ═══════════════════════════════════════════════════════════════
MOOD_SUFFIXES = {
    "dramatic": "vertical 9:16, dramatic cinematic dark lighting, TikTok motivational video style, high quality",
    "angry": "vertical 9:16, intense red and dark lighting, dramatic atmosphere, TikTok motivational style",
    "sad": "vertical 9:16, dark blue melancholic lighting, emotional atmosphere, TikTok motivational style",
    "melancholic": "vertical 9:16, muted dark tones, soft dim lighting, emotional atmosphere",
    "confused": "vertical 9:16, moody grey atmospheric lighting, TikTok motivational style",
    "desperate": "vertical 9:16, dark desperate atmosphere, dramatic shadows, emotional",
    "trapped": "vertical 9:16, dark oppressive atmosphere, dramatic contrast lighting",
    "lost": "vertical 9:16, eerie foggy atmosphere, dim lighting, moody",
    "determined": "vertical 9:16, dramatic warm lighting with dark shadows, inspirational atmosphere",
    "strong": "vertical 9:16, dramatic red and warm lighting, powerful atmosphere",
    "powerful": "vertical 9:16, dramatic action lighting, high energy, cinematic",
    "calm_strength": "vertical 9:16, controlled dramatic lighting, calm powerful atmosphere",
    "heroic": "vertical 9:16, epic golden dramatic lighting, cinematic heroic atmosphere",
    "triumphant": "vertical 9:16, golden sunrise lighting, epic triumphant atmosphere",
    "defensive": "vertical 9:16, dramatic sparking lighting, protective atmosphere",
    "peaceful": "vertical 9:16, warm golden peaceful lighting, serene atmosphere",
    "gentle": "vertical 9:16, soft warm contrasting light, gentle atmosphere",
    "hopeful": "vertical 9:16, warm hopeful lighting emerging from darkness",
    "contemplative": "vertical 9:16, soft moonlight, contemplative serene atmosphere",
    "solitary": "vertical 9:16, moody atmospheric lighting, thoughtful solitary mood",
    "isolated": "vertical 9:16, dim isolated atmosphere, quiet moody lighting",
    "thoughtful": "vertical 9:16, dramatic lighting contrast, thoughtful atmosphere",
    "transformative": "vertical 9:16, dramatic light-dark contrast, transformative atmosphere",
    "balanced": "vertical 9:16, balanced dramatic lighting, thoughtful atmosphere",
    "liberating": "vertical 9:16, dramatic upward lighting, liberating hopeful atmosphere",
    "hopeful_ending": "vertical 9:16, warm golden cinematic lighting, hopeful emotional ending",
    "inspirational": "vertical 9:16, bright inspirational golden lighting, cinematic wide shot",
    "epic_ending": "vertical 9:16, epic dramatic golden lighting, cinematic finale",
    "serene_ending": "vertical 9:16, peaceful moonlit atmosphere, serene calm ending",
    "mysterious": "vertical 9:16, mysterious dark purple lighting, atmospheric fog",
    "introspective": "vertical 9:16, dramatic spotlight in dark room, introspective mood",
    "betrayed": "vertical 9:16, dark dramatic atmosphere, emotional",
    "compassionate": "vertical 9:16, warm golden lighting, emotional compassionate mood",
    "resolute": "vertical 9:16, dramatic contrast lighting, resolute determined atmosphere",
}

# ═══════════════════════════════════════════════════════════════
# PRESET SCRIPTS — Kịch bản mẫu hoàn chỉnh (dùng ngay)
# ═══════════════════════════════════════════════════════════════
PRESET_SCRIPTS = {
    "4_dieu_im_lang": {
        "title": "4 Điều Im Lặng",
        "style": "stickman",
        "scenes": [
            {"text": "4 ĐIỀU IM LẶNG", "scene": "tsunami", "mood": "dramatic"},
            {"text": "Khi ai đó khiến bạn tức giận", "scene": "pressure_gauge", "mood": "angry"},
            {"text": "Khi bạn chẳng hề được thấu hiểu", "scene": "tangled_ropes", "mood": "confused"},
            {"text": "Khi lòng tốt bị lợi dụng", "scene": "lotus_thorns", "mood": "gentle"},
            {"text": "Hãy tiếp tục bước đi", "scene": "climbing_stairs", "mood": "determined"},
            {"text": "Con đường phía trước", "scene": "sunset_walk", "mood": "hopeful_ending"},
        ]
    },
    "5_dau_hieu_truong_thanh": {
        "title": "5 Dấu Hiệu Trưởng Thành",
        "style": "stickman",
        "scenes": [
            {"text": "5 DẤU HIỆU BẠN ĐANG TRƯỞNG THÀNH", "scene": "giant_doors", "mood": "dramatic"},
            {"text": "Bạn chọn cô đơn thay vì đám đông", "scene": "alone_table", "mood": "solitary"},
            {"text": "Bạn chọn giá trị thay vì vật chất", "scene": "bridge_choice", "mood": "thoughtful"},
            {"text": "Bạn bình tĩnh giữa bão tố", "scene": "standing_storm", "mood": "calm_strength"},
            {"text": "Bạn nhìn thấy bức tranh lớn hơn", "scene": "stargazing", "mood": "contemplative"},
            {"text": "Bạn gieo hạt cho tương lai", "scene": "seed_plant", "mood": "hopeful_ending"},
        ]
    },
    "3_quytac_nguoi_manh": {
        "title": "3 Quy Tắc Người Mạnh Mẽ",
        "style": "stickman_hoodie",
        "scenes": [
            {"text": "3 QUY TẮC CỦA NGƯỜI MẠNH MẼ", "scene": "crossroads", "mood": "dramatic"},
            {"text": "Không phản ứng với mọi thứ", "scene": "standing_storm", "mood": "calm_strength"},
            {"text": "Ôm lấy khó khăn", "scene": "lifting_weight", "mood": "strong"},
            {"text": "Làm chủ bản thân", "scene": "meditation", "mood": "peaceful"},
        ]
    },
    "5_sai_lam_tuoi_20": {
        "title": "5 Sai Lầm Tuổi 20",
        "style": "stickman",
        "scenes": [
            {"text": "5 SAI LẦM TUỔI 20", "scene": "cliff_edge", "mood": "dramatic"},
            {"text": "Sống theo kỳ vọng người khác", "scene": "puppet_free", "mood": "liberating"},
            {"text": "Sợ cô đơn nên ở bên người sai", "scene": "toxic_crowd", "mood": "resolute"},
            {"text": "Tiêu tiền để chứng tỏ", "scene": "bridge_choice", "mood": "thoughtful"},
            {"text": "Không dám thất bại", "scene": "chains", "mood": "trapped"},
            {"text": "Quên đầu tư cho bản thân", "scene": "seed_plant", "mood": "hopeful_ending"},
        ]
    },
    "khi_ban_muon_bo_cuoc": {
        "title": "Khi Bạn Muốn Bỏ Cuộc",
        "style": "stickman",
        "scenes": [
            {"text": "KHI BẠN MUỐN BỎ CUỘC", "scene": "sinking_sand", "mood": "desperate"},
            {"text": "Nhớ lại vì sao bạn bắt đầu", "scene": "mirror", "mood": "introspective"},
            {"text": "Đau khổ là tạm thời", "scene": "rain_sad", "mood": "sad"},
            {"text": "Phá vỡ giới hạn", "scene": "breaking_wall", "mood": "powerful"},
            {"text": "Tái sinh từ tro tàn", "scene": "phoenix", "mood": "epic_ending"},
        ]
    },
    "ngung_lam_nguoi_tot": {
        "title": "Ngừng Làm Người Tốt Vô Điều Kiện",
        "style": "stickman",
        "scenes": [
            {"text": "NGỪNG LÀM NGƯỜI TỐT VÔ ĐIỀU KIỆN", "scene": "portal", "mood": "dramatic"},
            {"text": "Lòng tốt bị lợi dụng", "scene": "backstab", "mood": "betrayed"},
            {"text": "Bạn che chở nhưng không ai che chở bạn", "scene": "shield_block", "mood": "defensive"},
            {"text": "Tách khỏi những kẻ độc hại", "scene": "toxic_crowd", "mood": "resolute"},
            {"text": "Tự xây vương miện cho mình", "scene": "crown_earn", "mood": "determined"},
            {"text": "Bước vào chương mới", "scene": "door_open", "mood": "hopeful_ending"},
        ]
    },
}


def build_prompt(scene_key, char_style_key="stickman", mood_override=None):
    """Sinh prompt hoàn chỉnh từ scene template + character style + mood."""
    if scene_key not in SCENE_TEMPLATES:
        raise ValueError(f"Scene '{scene_key}' không tồn tại. Có: {list(SCENE_TEMPLATES.keys())}")
    
    template, default_mood = SCENE_TEMPLATES[scene_key]
    char_desc = CHAR_STYLES.get(char_style_key, CHAR_STYLES["stickman"])
    mood = mood_override or default_mood
    suffix = MOOD_SUFFIXES.get(mood, MOOD_SUFFIXES["dramatic"])
    
    prompt = template.format(char=char_desc)
    return f"{prompt}, {suffix}"


def build_script_prompts(script_data):
    """Sinh danh sách prompt từ script data (dict)."""
    style = script_data.get("style", "stickman")
    prompts = []
    for scene in script_data["scenes"]:
        prompt = build_prompt(
            scene["scene"],
            char_style_key=style,
            mood_override=scene.get("mood")
        )
        prompts.append(prompt)
    return prompts


def parse_outline_file(filepath):
    """Parse file outline .txt thành script data."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Parse header
    data = {"style": "stickman", "scenes": []}
    
    # Tách header và scenes bằng ---
    parts = re.split(r'\n---\s*\n', content)
    
    # Parse header (phần đầu)
    header = parts[0] if parts else ""
    for line in header.strip().splitlines():
        line = line.strip()
        if line.upper().startswith("TIEU_DE:") or line.upper().startswith("TITLE:"):
            data["title"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("STYLE:"):
            val = line.split(":", 1)[1].strip().lower()
            if val in CHAR_STYLES:
                data["style"] = val
    
    # Parse scenes
    for part in parts[1:]:
        scene = {}
        for line in part.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith("TEXT:"):
                scene["text"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("SCENE:"):
                scene["scene"] = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("MOOD:"):
                scene["mood"] = line.split(":", 1)[1].strip().lower()
        
        if "scene" in scene:
            if "text" not in scene:
                scene["text"] = ""
            prompts_scene = scene
            data["scenes"].append(prompts_scene)
    
    return data


def list_presets():
    """Liệt kê tất cả kịch bản mẫu có sẵn."""
    print("\n📋 KỊCH BẢN MẪU CÓ SẴN:")
    print("=" * 60)
    for key, script in PRESET_SCRIPTS.items():
        n = len(script["scenes"])
        print(f"  • {key:30s} — {script['title']} ({n} cảnh)")
    print()


def list_scenes():
    """Liệt kê tất cả scene templates."""
    print("\n🎬 SCENE TEMPLATES CÓ SẴN:")
    print("=" * 60)
    categories = {}
    for key in SCENE_TEMPLATES:
        # Group by category (first word in comments)
        categories.setdefault("all", []).append(key)
    
    for key in sorted(SCENE_TEMPLATES.keys()):
        _, mood = SCENE_TEMPLATES[key]
        print(f"  • {key:25s} (mood: {mood})")
    print()


def list_styles():
    """Liệt kê tất cả character styles."""
    print("\n👤 CHARACTER STYLES:")
    print("=" * 60)
    for key, desc in CHAR_STYLES.items():
        print(f"  • {key:20s} — {desc[:60]}...")
    print()


def generate_from_preset(preset_key, output_file=None):
    """Sinh prompt từ kịch bản mẫu."""
    if preset_key not in PRESET_SCRIPTS:
        print(f"❌ Kịch bản '{preset_key}' không tồn tại.")
        list_presets()
        return None
    
    script = PRESET_SCRIPTS[preset_key]
    prompts = build_script_prompts(script)
    
    print(f"\n🎬 Kịch bản: {script['title']}")
    print(f"👤 Style: {script['style']}")
    print(f"📊 Số cảnh: {len(prompts)}")
    
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(prompts))
        print(f"✅ Đã lưu: {output_file}")
    else:
        print("\n" + "─" * 60)
        for i, p in enumerate(prompts, 1):
            print(f"\nCảnh {i}:")
            print(f"  {p[:120]}...")
        print("─" * 60)
    
    return prompts


def generate_from_outline(outline_file, output_file=None):
    """Sinh prompt từ file outline."""
    data = parse_outline_file(outline_file)
    prompts = build_script_prompts(data)
    
    title = data.get("title", os.path.basename(outline_file))
    print(f"\n🎬 Kịch bản: {title}")
    print(f"👤 Style: {data['style']}")
    print(f"📊 Số cảnh: {len(prompts)}")
    
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(prompts))
        print(f"✅ Đã lưu: {output_file}")
    
    return prompts


def main():
    parser = argparse.ArgumentParser(
        description="Prompt Template Generator — Tạo prompt Veo từ template (không cần API AI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python prompt_templates.py --list-presets
  python prompt_templates.py --list-scenes
  python prompt_templates.py --preset 4_dieu_im_lang -o prompts.txt
  python prompt_templates.py outline.txt -o prompts.txt
        """
    )
    parser.add_argument("outline", nargs="?", default=None, help="File outline .txt")
    parser.add_argument("-o", "--output", default=None, help="File output prompt .txt")
    parser.add_argument("--preset", default=None, help="Dùng kịch bản mẫu có sẵn")
    parser.add_argument("--list-presets", action="store_true", help="Liệt kê kịch bản mẫu")
    parser.add_argument("--list-scenes", action="store_true", help="Liệt kê scene templates")
    parser.add_argument("--list-styles", action="store_true", help="Liệt kê character styles")
    
    args = parser.parse_args()
    
    if args.list_presets:
        list_presets()
        return
    if args.list_scenes:
        list_scenes()
        return
    if args.list_styles:
        list_styles()
        return
    
    if args.preset:
        generate_from_preset(args.preset, args.output)
    elif args.outline:
        generate_from_outline(args.outline, args.output)
    else:
        print("🎬 Prompt Template Generator")
        print("Dùng --help để xem hướng dẫn, hoặc --list-presets để xem kịch bản mẫu.")
        list_presets()


if __name__ == "__main__":
    main()
