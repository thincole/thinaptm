import os, sys, json, time, threading, urllib.request, urllib.error, random, re
import shopeevideo as SV
import engine as E

_ai_key_lock = threading.Lock()
_gemini_key_rr_idx = 0
_groq_key_rr_idx = 0
def ai_gen_prompts(product_name, scene_en, n_segments,
                    duration_sec, lang_code, review_style,
                    mode="gemini", gemini_keys=None, groq_keys=None,
                    product_desc="", image_path=None, no_model=False, log_cb=None):
    def _log(msg):
        if log_cb:
            try: log_cb(msg)
            except: pass
        else:
            print(msg)
    """Gọi Gemini (Multimodal Vision) hoặc Groq để sinh prompt video review sản phẩm chuẩn xác,
    đúng góc nhìn logic, khóa giải phẫu bàn tay (2 tay, 5 ngón, không tay ma/chi thừa).
    Trả về list[str] prompts hoặc None nếu thất bại."""
    lang_map = {"vi": "Vietnamese", "en": "English", "id": "Indonesian", "my": "Malay", "ph": "Filipino"}
    lang_name = lang_map.get(lang_code, "English")

    # Đọc ảnh sang base64 nếu có (dành cho Gemini Multimodal Vision)
    image_b64 = None
    if image_path and os.path.isfile(image_path):
        try:
            import base64
            with open(image_path, "rb") as imf:
                image_b64 = base64.b64encode(imf.read()).decode("utf-8")
        except Exception:
            image_b64 = None

    # Nếu người dùng chọn Không mẫu (no_model), ép kiểu review sang POV / Showcase để tránh bịa MC
    if no_model:
        if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
            review_style = "POV (Góc nhìn thứ nhất)"
        elif review_style not in ("POV (Góc nhìn thứ nhất)", "Unboxing", "Demo Công Dụng"):
            review_style = "POV (Góc nhìn thứ nhất)"

    # Mô tả phong cách review — 7 kiểu chuyên dụng cho video affiliate
    _REVIEW_STYLE_DESCS = {
        "Review tự nhiên": (
            "NATURAL STANDING REVIEW style: The presenter stands naturally, picks up the product, "
            "walks around the scene, holds items up to camera. Free movement, energetic and authentic. "
            "Casual handheld camera feel with smooth tracking. "
            "CAMERA: Medium shot, handheld with subtle natural shake, 35mm lens feel. "
            "LIGHTING: Natural window light from the side, mixed with warm indoor ambient light, soft shadows. "
            "ENVIRONMENT: Clean but lived-in room, slightly visible background details for authenticity. "
            "ANTI-AI: Include slight camera drift, natural micro-expressions, smartphone camera quality feel."
        ),
        "Ngồi Review": (
            "SEATED DESK REVIEW style: The presenter sits behind a clean minimalist wooden desk "
            "throughout the ENTIRE video. She NEVER stands up or walks. All product interactions "
            "happen on the desk or held above it. Camera is at desk-level, frontal or slightly angled. "
            "CAMERA: Static or slow push-in, eye-level, 50mm lens feel. "
            "LIGHTING: Soft LED panel or ring light from front, warm tone, even illumination. "
            "ENVIRONMENT: Clean desk surface, minimalist background, soft bokeh. "
            "ANTI-AI: Natural hand gestures, occasional glance away from camera, realistic skin texture."
        ),
        "POV (Góc nhìn thứ nhất)": (
            "POV FIRST-PERSON style: Camera IS the viewer's eyes looking down at the desk. We NEVER see the presenter's face. "
            "Only the hands and arms visible interacting with the product. The viewer feels like THEY are "
            "the one holding, opening, and using the product themselves. "
            "CAMERA: First-person POV, looking-down angle, handheld with natural shake. "
            "LIGHTING: Natural mixed indoor light, overhead kitchen/room light, uncontrolled ambient. "
            "ENVIRONMENT: Real desk/table/counter surface. "
            "ANTI-AI: Natural hand movement speed, iPhone camera compression feel. "
            "CRITICAL: NO face visible. Exactly TWO hands. Product is the HERO."
        ),
        "Unboxing": (
            "UNBOXING style: Focus on the satisfying experience of opening packaging and revealing "
            "the product for the first time. Slow, deliberate hand movements. Build anticipation. "
            "CAMERA: Top-down flat lay angle for opening, then switch to close-up for product reveal. "
            "Handheld with subtle movement. "
            "LIGHTING: Warm overhead light, soft shadows on packaging textures, cozy atmosphere. "
            "ENVIRONMENT: Clean wooden desk surface. "
            "ANTI-AI: ASMR-adjacent aesthetic — tactile textures visible, natural finger movements. "
            "CRITICAL: Show FULL unboxing journey — sealed box/blister → unpack → reveal."
        ),
        "UGC Authentic": (
            "UGC AUTHENTIC style: Raw, unpolished, genuine — like a real customer sharing with friends. "
            "NOT a professional review. This should feel like someone filming with their phone in their "
            "room, genuinely excited about a product they just received. "
            "CAMERA: iPhone selfie front-camera angle, slightly off-center framing, visible camera shake. "
            "LIGHTING: Bedroom lamp + window light, warm indoor tone. "
            "ENVIRONMENT: Cozy lived-in room. "
            "CRITICAL: Must feel like a REAL person's phone video, NOT a commercial."
        ),
        "Demo Công Dụng": (
            "PRODUCT DEMONSTRATION style: Focus entirely on showing HOW the product works. "
            "Step-by-step functional demonstration with clear visibility of features and results. "
            "CAMERA: Alternating between close-up macro shots (product details, textures) "
            "and medium shots (hands demonstrating usage). Steady, controlled movement. "
            "LIGHTING: Bright, even lighting for maximum product visibility. "
            "ENVIRONMENT: Clean test surface — white/light desk, neutral background. "
            "CRITICAL: Product FUNCTIONALITY is the hero — demonstrating real durability and utility."
        ),
        "So Sánh/Đánh Giá": (
            "COMPARISON REVIEW style: Side-by-side honest evaluation. The presenter compares "
            "the product against expectations, price point, or similar alternatives. "
            "Analytical, trustworthy tone. "
            "CAMERA: Medium shot with product clearly featured, alternating close-ups. "
            "LIGHTING: Consistent even lighting. "
            "ENVIRONMENT: Clean comparison surface. "
            "CRITICAL: Must show genuine honest evaluation."
        ),
    }
    if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
        import random as _rnd
        actual_style = _rnd.choice(list(_REVIEW_STYLE_DESCS.keys()))
        style_desc = _REVIEW_STYLE_DESCS[actual_style]
    else:
        style_desc = _REVIEW_STYLE_DESCS.get(review_style, _REVIEW_STYLE_DESCS["Review tự nhiên"])

    # Mô tả kịch bản theo số segment
    if n_segments == 2:
        flow_desc = (
            "VIDEO FLOW (2 segments × 8 seconds = 16 seconds total):\n"
            "- Segment 1 (8s): Opening — presenter/hands reveal and pick up the product with genuine excitement, "
            "examining key features while speaking enthusiastically about it.\n"
            "- Segment 2 (8s): Closing — presenter/hands demonstrate the product in use, giving final verdict "
            "with satisfaction, recommending it confidently.\n"
            "CONTINUITY: Segment 2 must start from the EXACT pose/position where Segment 1 ended."
        )
    else:
        flow_desc = (
            "VIDEO FLOW (3 segments × 8 seconds = 24 seconds total):\n"
            "- Segment 1 (8s): Opening — reveal and introduce product by name and key features.\n"
            "- Segment 2 (8s): Middle — close-up showcase of product details, testing textures and durability.\n"
            "- Segment 3 (8s): Closing — final recommendation with enthusiasm and thumbs-up.\n"
            "CONTINUITY: Each segment must start from the EXACT pose/position where the previous one ended."
        )
    desc_part = f"═══ DETAILED PRODUCT DESCRIPTION (MÔ TẢ SẢN PHẨM) ═══\n{product_desc}\n\n" if product_desc else ""
    
    system_prompt = (
        f"You are an elite viral TikTok / Reels UGC content creator and master prompt engineer for Google Veo 3.1 (image-to-video AI).\n"
        f"Your mission: Write EXACTLY {n_segments} highly engaging, viral video prompts for a Shopee product review that converts viewers into buyers.\n\n"
        f"═══ PRODUCT INFO ═══\n"
        f"Product Name: \"{product_name}\"\n"
        f"{desc_part}"
        f"═══ HOW TO USE THE PRODUCT DESCRIPTION (CRITICAL) ═══\n"
        f"1. EXTRACT 2-3 CORE SELLING POINTS: Deeply analyze the Product Description above. Identify the key real-world benefits: specific materials, standout durability, unique functions, texture, design details, problem-solving aspects.\n"
        f"2. VISUAL DEMONSTRATION: Make the hands or presenter interact with and demonstrate THESE EXACT FEATURES (e.g. feeling the texture, demonstrating the function, showing the snug fit/finish up close).\n"
        f"3. CAPTIVATING DIALOGUE & VOICE: The spoken words MUST explicitly reference the genuine highlights from the description with genuine emotion, making the review sound authentic, convincing, and irresistible.\n\n"
        f"═══ VIDEO SETTINGS ═══\n" 
        f"Total Duration: {duration_sec} seconds ({n_segments} segments × 8 seconds each)\n"
        f"Background/Scene: {scene_en}\n"
        f"Presenter Language: {lang_name}\n"
        f"Review Style: {style_desc}\n\n"
        f"═══ {flow_desc} ═══\n\n"
        f"═══ CRITICAL VISUAL PERSPECTIVE & ANATOMICAL INTEGRITY RULES (PREVENT MUTATIONS & EXTRA LIMBS) ═══\n"
        f"You MUST strictly follow these rules to guarantee anatomical and physical plausibility:\n"
        f"1. PRE-EXISTING HANDS / POV IMAGE DETECTION (MOST CRITICAL RULE):\n"
        f"   - Check the reference image carefully. If the image ALREADY shows hands or arms holding/touching the product from a first-person POV (e.g. hands holding a phone case, skincare item, gadget, or item on a surface):\n"
        f"     * You MUST write a FIRST-PERSON POV video prompt looking down at the tabletop!\n"
        f"     * ABSOLUTELY DO NOT ADD A PRESENTER'S FACE, HEAD, OR BODY IN THE BACKGROUND! (Adding a person behind pre-existing hands creates horrifying multi-arm glitches where 3 or 4 arms appear, with floating/disembodied hands).\n"
        f"     * Animate ONLY those exact hands from the image (matching the exact clothing sleeves, skin tone, and nails/fingers) smoothly rotating, handling, tilting, and demonstrating the product on the desk.\n"
        f"2. NO-MODEL / PRODUCT SHOWCASE:\n"
        f"   - If 'no_model' is active OR if the image only contains the product without any human:\n"
        f"     * If 'no_model' is active: ABSOLUTELY NO human presenter face or body! Either a sleek commercial product showcase with smooth camera motion (orbit, slow push-in, macro pan), 360-degree rotation, studio lighting, NO human bodies. If hands are needed to interact, use ONLY two clean hands in first-person POV on the tabletop.\n"
        f"3. PRESENTER ANATOMY LOCK (When a presenter/model is used):\n"
        f"   - STRICT 2-ARM LIMIT: Exactly ONE person in the scene with strictly TWO arms naturally attached at her/his shoulders.\n"
        f"   - EXACTLY 5 FINGERS: Each hand has strictly five normal, distinct fingers with realistic joints and fingernails. No mutated digits, no fused fingers, no extra fingers.\n"
        f"   - PHYSICAL SUPPORT & NO FLOATING HANDS: Every hand in frame must have an obvious, unbroken anatomical connection to the person's body:\n"
        f"     * If holding with two hands: Both of her own hands hold the sides of the product at chest level.\n"
        f"     * If holding with one hand: One hand firmly grips the base/side of the product at chest level, while the other hand rests naturally on the desk or gestures. Both arms stay visibly connected to her torso.\n"
        f"     * ABSOLUTELY NEVER generate a third arm, a floating hand, or an extra hand coming into frame from off-camera to hold the product! The presenter's own hands must do all the holding.\n"
        f"4. PROMPT LOCKS & NEGATIVE ENFORCEMENT:\n"
        f"   - FRAMING LOCK: Full-frame vertical 9:16 portrait video. Reference image fills frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO storyboard/collage layout.\n"
        f"   - PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Color, shape, size, material texture, and logos must NOT change, swap, or transform at any point.\n"
        f"   - NEGATIVE DIRECTIVES: extra limbs, extra hands, extra arms, third arm, disembodied hand, floating limbs, phantom hands, reaching hands from off-screen, six fingers, four fingers, mutated fingers, fused digits, deformed hands, broken wrists, detached limbs, unnatural joints, malformed limbs, cartoon, anime, illustration, CGI, text overlays, watermarks.\n"
        f"2. SECTION 2 (PRODUCT HERO & HIGHLIGHTS): \"{product_name}\" is the HERO. Prominently featured, sharp focus, showing the real textures and details from the description.\n"
    )
    # Section 3: Người mẫu hoặc POV (Không mặt)
    is_pov_or_unbox = any(k in str(review_style or "").lower() for k in ("pov", "unbox", "đập hộp", "góc nhìn thứ nhất")) or no_model
    if is_pov_or_unbox:
        system_prompt += (
            f"3. SECTION 3 (POV / UNBOXING / SHOWCASE - NO PRESENTER FACE):\n"
            f"   - ABSOLUTELY NO human face, NO head, NO model body visible in any frame.\n"
            f"   - Define strictly First-person POV or top-down desk perspective looking directly at the product.\n"
            f"   - If hands are shown: ONLY the pair of clean natural human hands interacting with and showcasing the product on the table. Exactly two hands with 5 normal fingers each. No third hand, no disembodied limbs.\n"
            f"   - Voiceover speaks off-camera while hands or camera demonstrate the product.\n"
        )
    elif lang_code == "my":
        # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
        system_prompt += (
            f"3. SECTION 3 (PRESENTER & OUTFIT LOCK):\n"
            f"   - Define ONE fixed Malay MALE presenter (~25-30yo, modest clothing: clean long-sleeve button-down or polo shirt, dark trousers, neat well-groomed hair, friendly professional appearance).\n"
            f"   - ANATOMY ENFORCEMENT: Strictly two arms attached to his shoulders, two hands with 5 fingers each. Hand coordination: Left hand holds the product at chest level, right hand gestures. Absolutely NO third arm or external hands.\n"
            f"   - REPEAT THAT EXACT MALE CHARACTER AND OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts.\n"
        )
    else:
        system_prompt += (
            f"3. SECTION 3 (PRESENTER & OUTFIT LOCK):\n"
            f"   - Define ONE fixed presenter anchor (~22-26yo Asian woman, exact face, exact hairstyle, exact clothing outfit style and color).\n"
            f"   - ANATOMY ENFORCEMENT: Strictly two arms attached to her shoulders, two hands with 5 fingers each. Hand coordination: Left hand holds the product steadily at chest level, right hand gestures. Absolutely NO third arm or external hands.\n"
            f"   - REPEAT THAT EXACT CHARACTER AND OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts.\n"
        )
    system_prompt += (
        f"4. SECTION 4 (ACTION & TIMELINE CONTINUITY):\n"
        f"   - Follow strict timeline progression: 0-1s engaging visual hook introducing product; 1-3s speaking while demonstrating the specific features from the description; 3-7s tactile demonstration or functional proof; 7-8s confident final showcase and freeze to clean handoff pose.\n"
        f"   - Continuity: Segment 1 ends with a distinct static pose; Segment 2 starts EXACTLY from that pose.\n"
        f"5. SECTION 5 (CAMERA & TECHNICAL SPECS): Smartphone-style photorealism, eye-level angle, 35mm/50mm lens feel, natural soft lighting, clean white balance, optical depth of field.\n"
        f"6. SECTION 6 (VIRAL UGC DIALOGUE & VOICE SCRIPT):\n"
        f"   - High-energy, authentic viral TikTok/Reels UGC dialogue in {lang_name}.\n"
        f"   - Formula: [HOOK GIẬT TÍT HẤP DẪN (0-2s)] + [ĐIỂM NỔI BẬT ĐÁNG TIỀN TỪ MÔ TẢ (2-6s)] + [KÊU GỌI HÀNH ĐỘNG TỰ NHIÊN (6-8s)].\n"
        f"   - Length: ~20-28 words per segment. Spoken with lively pacing, relatable expression, and natural enthusiasm, avoiding robotic ad copy.\n"
        f"   - Must explicitly mention real benefits from the Product Description!\n\n"
        f"═══ OUTPUT FORMAT ═══\n"
        f"Output EXACTLY {n_segments} lines. One prompt per line.\n"
        f"No numbering (1. 2. 3.), no bullet points, no markdown, no explanations.\n"
        f"Just {n_segments} raw prompt lines.\n"
    )

    # Định nghĩa hàm gọi Gemini helper xoay vòng (Round-Robin so le qua tất cả API keys)
    def _run_gemini(keys):
        if not keys: return None
        global _gemini_key_rr_idx
        with _ai_key_lock:
            start_idx = _gemini_key_rr_idx % len(keys)
            _gemini_key_rr_idx += 1
        # Xếp danh sách key bắt đầu từ start_idx rồi xoay vòng đều cho các luồng
        keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
        
        # Thứ tự model ưu tiên: gemini-flash-lite-latest (quota cao, phản hồi nhanh) → gemini-flash-latest
        _MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
        for key in keys_ordered:
            k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
            for model_name in _MODELS:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                    parts = []
                    if image_b64:
                        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
                    parts.append({"text": system_prompt})
                    payload = json.dumps({
                        "contents": [{"parts": parts}],
                        "generationConfig": {"temperature": 0.7}
                    }).encode("utf-8")
                    req = urllib.request.Request(url, data=payload,
                                                 headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    text = ""
                    for part in (data.get("candidates", [{}])[0].get("content", {}).get("parts", [])):
                        text += part.get("text", "")
                    prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                    if len(prompts) >= n_segments:
                        _log(f"  ✅ Gemini Vision OK ({model_name} | key {k_tag})")
                        return prompts[:n_segments]
                except urllib.error.HTTPError as he:
                    if he.code == 429:
                        _log(f"  ⚠ {model_name} key {k_tag} quota 429 → chuyển key/model tiếp")
                        continue  # thử model tiếp trong _MODELS
                    _log(f"  ⚠ Gemini {model_name} key {k_tag} HTTP {he.code}")
                    break  # lỗi khác → thử key khác
                except Exception as e:
                    _log(f"  ⚠ Gemini key {k_tag} lỗi: {str(e)[:50]}")
                    break
        return None

    # Định nghĩa hàm gọi Groq helper (Cố định model llama-3.1-8b-instant, xoay vòng so le API keys)
    def _run_groq(keys):
        if not keys: return None
        global _groq_key_rr_idx
        with _ai_key_lock:
            start_idx = _groq_key_rr_idx % len(keys)
            _groq_key_rr_idx += 1
        keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
        groq_model = "llama-3.1-8b-instant"
        for key in keys_ordered:
            k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
            try:
                url = "https://api.groq.com/openai/v1/chat/completions"
                payload = json.dumps({
                    "model": groq_model,
                    "messages": [
                        {"role": "system", "content": "You generate Google Veo 3 video prompts for Shopee product reviews."},
                        {"role": "user", "content": system_prompt}
                    ],
                    "temperature": 0.9,
                    "max_tokens": 2000
                }).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                if len(prompts) >= n_segments:
                    _log(f"  ✅ Groq OK ({groq_model} | key {k_tag})")
                    return prompts[:n_segments]
            except Exception as e:
                err_str = str(e).lower()
                if any(tok in err_str for tok in ("401", "403", "restricted", "blocked", "invalid", "forbidden")):
                    _log(f"  ⚠ Groq key {k_tag} bị khóa/lỗi ({e}) → Chuyển key tiếp theo.")
                    continue
                continue
        return None

    # Thực hiện gọi và tự động fallback
    if mode == "gemini":
        if gemini_keys:
            res = _run_gemini(gemini_keys)
            if res: return res
        if groq_keys:
            _log("  🔄 Gemini thất bại, tự động chuyển sang Groq...")
            res = _run_groq(groq_keys)
            if res: return res
    elif mode == "groq":
        if groq_keys:
            res = _run_groq(groq_keys)
            if res: return res
        if gemini_keys:
            _log("  🔄 Groq thất bại, tự động chuyển sang Gemini...")
            res = _run_gemini(gemini_keys)
            if res: return res
    return None
