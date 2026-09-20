    def _sv_ai_gen_prompts(self, product_name, scene_en, n_segments,
                            duration_sec, lang_code, review_style,
                            mode="gemini", gemini_keys=None, groq_keys=None):
        """Gọi Gemini hoặc Groq để sinh prompt video review sản phẩm chất lượng cao.
        Trả về list[str] prompts hoặc None nếu thất bại."""
        lang_map = {"vi": "Vietnamese", "en": "English", "id": "Indonesian", "my": "Malay", "ph": "Filipino"}
        lang_name = lang_map.get(lang_code, "English")

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
                "POV FIRST-PERSON style: Camera IS the viewer's eyes. We NEVER see the presenter's face. "
                "Only hands and arms visible interacting with the product. The viewer feels like THEY are "
                "the one holding, opening, and using the product themselves. "
                "CAMERA: First-person POV, over-the-shoulder or looking-down angle, handheld with natural shake. "
                "LIGHTING: Natural mixed indoor light, overhead kitchen/room light, uncontrolled ambient. "
                "ENVIRONMENT: Real desk/table/counter surface, slight clutter (pen, coffee mug, receipts) for authenticity. "
                "ANTI-AI: Slight lens flare from room lamp, visible fingerprints/dust on product, "
                "natural hand movement speed (not too smooth), iPhone camera compression feel. "
                "CRITICAL: NO face visible. Only hands and forearms. Product is the HERO."
            ),
            "Unboxing": (
                "UNBOXING style: Focus on the satisfying experience of opening packaging and revealing "
                "the product for the first time. Slow, deliberate hand movements. Build anticipation. "
                "CAMERA: Top-down flat lay angle for opening, then switch to close-up for product reveal. "
                "Handheld with subtle movement. "
                "LIGHTING: Warm overhead light, soft shadows on packaging textures, cozy atmosphere. "
                "ENVIRONMENT: Clean wooden desk or floor surface, minimal props (scissors, knife nearby). "
                "ANTI-AI: Include satisfying paper rustling and packaging sounds, tactile textures visible, "
                "slight pause of genuine excitement when product is revealed, natural finger movements "
                "(not perfectly smooth). ASMR-adjacent aesthetic — crisp sounds, deliberate slow pacing. "
                "CRITICAL: Show FULL unboxing journey — sealed box → cutting tape → lifting lid → reveal."
            ),
            "UGC Authentic": (
                "UGC AUTHENTIC style: Raw, unpolished, genuine — like a real customer sharing with friends. "
                "NOT a professional review. This should feel like someone filming with their phone in their "
                "bedroom, genuinely excited about a product they just received. "
                "CAMERA: iPhone selfie front-camera angle, slightly off-center framing, visible camera shake, "
                "occasional focus hunting, vlog-style close talking distance. "
                "LIGHTING: Messy mixed lighting — bedroom lamp + phone screen glow + window light, "
                "NOT studio lighting, slightly warm/yellow indoor tone. "
                "ENVIRONMENT: Slightly messy bedroom or living room, pillows/blankets visible, "
                "personal items in background, lived-in and imperfect. "
                "ANTI-AI: Include casual speech cadence (slight pauses, 'um'), genuine excitement not "
                "performative, natural skin texture with no filter, hair slightly imperfect, "
                "camera tilts/adjusts mid-shot. Shot on smartphone quality — slight grain, natural compression. "
                "CRITICAL: Must feel like a REAL person's phone video, NOT a commercial."
            ),
            "Demo Công Dụng": (
                "PRODUCT DEMONSTRATION style: Focus entirely on showing HOW the product works. "
                "Step-by-step functional demonstration with clear visibility of features and results. "
                "CAMERA: Alternating between close-up macro shots (product details, buttons, textures) "
                "and medium shots (hands demonstrating usage). Steady, controlled movement. "
                "LIGHTING: Bright, even, clinical-style lighting for maximum product visibility. "
                "Natural daylight or bright LED, no dramatic shadows — clarity is priority. "
                "ENVIRONMENT: Clean test surface — white/light desk, neutral background, "
                "comparison items nearby if relevant (ruler for scale, water for waterproof test). "
                "ANTI-AI: Show REAL interaction physics — weight of product visible in hand grip, "
                "realistic material textures, functional result visible (cream absorbed, device screen lit up, "
                "sound produced). Include before/after moments where relevant. "
                "CRITICAL: Product FUNCTIONALITY is the hero — every shot must demonstrate a specific feature."
            ),
            "So Sánh/Đánh Giá": (
                "COMPARISON REVIEW style: Side-by-side honest evaluation. The presenter compares "
                "the product against expectations, price point, or similar alternatives. "
                "Analytical, trustworthy, 'brutally honest' tone. "
                "CAMERA: Medium shot with both products visible, alternating close-ups on each, "
                "split-frame composition when comparing features. Steady tripod feel. "
                "LIGHTING: Consistent even lighting on both products — no favoritism in presentation. "
                "Bright, neutral-tone daylight or LED panel. "
                "ENVIRONMENT: Clean comparison surface, both products clearly labeled/visible, "
                "perhaps a notepad or checklist visible for systematic review. "
                "ANTI-AI: Show genuine contemplation (touching chin, slight frown while thinking), "
                "honest facial reactions (impressed nod OR disappointed head shake), "
                "realistic material/texture differences visible between products. "
                "CRITICAL: Must show BOTH positive and negative aspects — not purely promotional."
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
                "- Segment 1 (8s): Opening — presenter discovers/picks up the product with genuine excitement, "
                "examines it closely, shows key features while speaking enthusiastically about it.\n"
                "- Segment 2 (8s): Closing — presenter demonstrates the product in use, gives final verdict "
                "with confident smile, nods approvingly, and gives a thumbs up to recommend it.\n"
                "CONTINUITY: Segment 2 must start from the EXACT pose/position where Segment 1 ended."
            )
        else:
            flow_desc = (
                "VIDEO FLOW (3 segments × 8 seconds = 24 seconds total):\n"
                "- Segment 1 (8s): Opening — presenter reveals the product with excitement, picks it up, "
                "examines the packaging/design while introducing the product by name.\n"
                "- Segment 2 (8s): Middle — close-up showcase of product features and details, presenter "
                "demonstrates how to use it, touches textures, shows different angles.\n"
                "- Segment 3 (8s): Closing — presenter gives final review verdict, shows satisfaction, "
                "recommends with enthusiasm, smiles warmly and gives thumbs up.\n"
                "CONTINUITY: Each segment must start from the EXACT pose/position where the previous one ended."
            )

        system_prompt = (
            f"You are an expert prompt engineer for Google Veo 3 (image-to-video AI).\n"
            f"Write EXACTLY {n_segments} video prompts for a Shopee product review.\n\n"
            f"═══ PRODUCT INFO ═══\n"
            f"Product Name: \"{product_name}\"\n"
            f"(This product name is from Shopee. Use it to infer what the product looks like and how to review it.)\n\n"
            f"═══ VIDEO SETTINGS ═══\n"
            f"Total Duration: {duration_sec} seconds ({n_segments} segments × 8 seconds each)\n"
            f"Background/Scene: {scene_en}\n"
            f"Presenter Language: {lang_name}\n"
            f"Review Style: {style_desc}\n\n"
            f"═══ {flow_desc} ═══\n\n"
            f"═══ 6-SECTION PROMPT STRUCTURE & PROMPT LOCKS ═══\n"
            f"Each output prompt must strictly incorporate these 6 sections and prompt locks:\n"
            f"1. SECTION 1 (GENERAL RULES & LOCKS):\n"
            f"   - FRAMING LOCK: Full-frame vertical 9:16 portrait video. Reference image fills frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO storyboard/collage layout.\n"
            f"   - PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Color, shape, size, material texture, and logos must NOT change, swap, or transform at any point (especially final 1-2s).\n"
            f"   - HAND & ANATOMY LOCK: The presenter has exactly TWO normal human hands with 5 fingers each. DO NOT generate extra hands, extra arms, extra fingers, or limb deformations.\n"
            f"   - ITEM PERSISTENCE: Any object held or worn must remain naturally present throughout.\n"
            f"2. SECTION 2 (PRODUCT TO ADVERTISE): \"{product_name}\" is the HERO. Prominently featured and in sharp focus.\n"
        )
        # Section 3: Người mẫu hoặc POV (Không mặt)
        is_pov_or_unbox = any(k in str(review_style or "").lower() for k in ("pov", "unbox", "đập hộp", "góc nhìn thứ nhất"))
        if is_pov_or_unbox:
            system_prompt += (
                f"3. SECTION 3 (POV / UNBOXING - NO PRESENTER FACE): ABSOLUTELY NO human face, NO head, NO model body visible in any frame. "
                f"Define strictly First-person POV or top-down desk perspective looking directly at the product. "
                f"Only TWO clean natural human hands interacting with and showcasing the product on the table. "
                f"Voiceover speaks off-camera while hands demonstrate the product.\n"
            )
        elif lang_code == "my":
            # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed Malay MALE presenter (~25-30yo, "
                f"modest clothing: clean long-sleeve button-down or polo shirt, dark trousers, neat well-groomed hair, "
                f"friendly professional appearance) and REPEAT THAT EXACT MALE CHARACTER AND "
                f"OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts. (CRITICAL: MUST be a MALE presenter, NO female model).\n"
            )
        else:
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed presenter anchor (~22-26yo Asian woman, "
                f"exact face, exact hairstyle, exact clothing outfit style and color) and REPEAT THAT EXACT "
                f"CHARACTER AND OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts.\n"
            )
        system_prompt += (
            f"4. SECTION 4 (ACTION & TIMELINE CONTINUITY):\n"
            f"   - Follow strict timeline progression (0-1s anchor/intro, 1-3s speaking/handling, 3-7s demonstration/gestures, 7-8s CRITICAL RETURN TO REFERENCE & FREEZE to static handoff pose).\n"
            f"   - Segment 1 ends with a distinct static pose; Segment 2 starts EXACTLY from that pose. Segment 2 ends with a distinct pose; Segment 3 starts EXACTLY from that pose.\n"
            f"5. SECTION 5 (CAMERA & TECHNICAL SPECS): Smartphone-style photorealism, eye-level angle, 35mm/50mm lens feel, natural soft lighting, clean white balance, optical depth of field.\n"
            f"6. SECTION 6 (DIALOGUE SCRIPT): The presenter speaks naturally in {lang_name} about \"{product_name}\" (authentic UGC tone, ~15-20 words, no exaggerated claims, ending with soft CTA).\n\n"
            f"═══ OUTPUT FORMAT ═══\n"
            f"Output EXACTLY {n_segments} lines. One prompt per line.\n"
            f"No numbering (1. 2. 3.), no bullet points, no markdown, no explanations.\n"
            f"Just {n_segments} raw prompt lines.\n"
        )

        # Định nghĩa hàm gọi Gemini helper xoay vòng (Round-Robin so le qua tất cả API keys)
        def _run_gemini(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_gemini_key_rr_idx", 0) % len(keys)
                self._gemini_key_rr_idx = getattr(self, "_gemini_key_rr_idx", 0) + 1
            # Xếp danh sách key bắt đầu từ start_idx rồi xoay vòng đều cho các luồng
            keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
            
            # Thứ tự model ưu tiên: gemini-flash-lite-latest (quota dồi dào nhất) → gemini-3.5-flash-lite → gemini-3.1-flash-lite → gemini-3-flash-preview → gemini-3.5-flash → gemini-3.7-flash
            _MODELS = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.7-flash"]
            for key in keys_ordered:
                k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
                for model_name in _MODELS:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                        payload = json.dumps({
                            "contents": [{"parts": [{"text": system_prompt}]}],
                            "generationConfig": {"temperature": 0.9}
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
                            self._sv_log_msg(f"  ✅ Gemini OK ({model_name} | key {k_tag})")
                            return prompts[:n_segments]
                    except urllib.error.HTTPError as he:
                        if he.code == 429:
                            self._sv_log_msg(f"  ⚠ {model_name} key {k_tag} quota 429 → chuyển key/model tiếp")
                            continue  # thử model tiếp trong _MODELS
                        self._sv_log_msg(f"  ⚠ Gemini {model_name} key {k_tag} HTTP {he.code}")
                        break  # lỗi khác → thử key khác
                    except Exception as e:
                        self._sv_log_msg(f"  ⚠ Gemini key {k_tag} lỗi: {str(e)[:50]}")
                        break
            return None

        # Định nghĩa hàm gọi Groq helper (Cố định model llama-3.1-8b-instant, xoay vòng so le API keys)
        def _run_groq(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_groq_key_rr_idx", 0) % len(keys)
                self._groq_key_rr_idx = getattr(self, "_groq_key_rr_idx", 0) + 1
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
                        self._sv_log_msg(f"  ✅ Groq OK ({groq_model} | key {k_tag})")
                        return prompts[:n_segments]
                except Exception as e:
                    err_str = str(e).lower()
                    if any(tok in err_str for tok in ("401", "403", "restricted", "blocked", "invalid", "forbidden")):
                        self._sv_log_msg(f"  ⚠ Groq key {k_tag} bị khóa/lỗi ({e}) → Chuyển key tiếp theo.")
                        continue
                    continue
            return None

        # Thực hiện gọi và tự động fallback
        if mode == "gemini":
            if gemini_keys:
                res = _run_gemini(gemini_keys)
                if res: return res
            if groq_keys:
                self._sv_log_msg("  🔄 Gemini thất bại, tự động chuyển sang Groq...")
                res = _run_groq(groq_keys)
                if res: return res
        elif mode == "groq":
            if groq_keys:
                res = _run_groq(groq_keys)
                if res: return res
            if gemini_keys:
                self._sv_log_msg("  🔄 Groq thất bại, tự động chuyển sang Gemini...")
                res = _run_gemini(gemini_keys)
                if res: return res
        return None

    def _sv_start(self):
        """Bắt đầu tạo video từ danh sách SP đã nhận."""
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được."); return
        if not self._sv_claimed_products:
            messagebox.showwarning("Thiếu SP", "Hãy bấm 📥 Nhận Lô Sản Phẩm trước."); return
        out_dir = self._sv_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu", "Hãy chọn thư mục lưu video."); return

        enabled_accs = [a for a in self.accounts if a.get("enabled", True) and a.get("role") != "donor"]
        if not enabled_accs:
            messagebox.showerror("Lỗi", "Không có tài khoản nào được chọn.\nHãy tích chọn ở tab Tài khoản."); return

        self._sv_running = True
        self._sv_stop_flag = False
        self._reset_global_circuit_breakers()
        self._sv_btn_start.configure(state="disabled")
        self._sv_btn_stop.configure(state="normal")
        self._sv_btn_claim.configure(state="disabled")
        self._sv_status_lbl.configure(text="⏳ Đang tạo video...")
        self._sv_last_video_time = time.time()

        products = list(self._sv_claimed_products)
        aspect_key = E.VID_ASPECTS.get(self._sv_aspect.get(), "VIDEO_ASPECT_RATIO_PORTRAIT")
        img_aspect = E.IMG_ASPECTS.get(self._sv_aspect.get(), "IMAGE_ASPECT_RATIO_PORTRAIT")
        scene_choice = self._sv_scene.get()
        duration_sec = SV.parse_duration(self._sv_duration.get())
        lang_val = self._sv_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
        sv_model_key = E.VID_MODELS.get(self._sv_model.get(), "veo_3_1_t2v_lite_low_priority")
        remove_wm = self._sv_remove_wm.get()
        del_img = self._sv_del_img.get()
        ghep_anh = self._sv_ghep_anh.get()
        sv_use_laundering = self._sv_use_laundering.get()
        naming_mode = self._sv_naming.get()
        review_style = self._sv_review_style.get()
        client_id = self._sv_client_entry.get().strip()
        ai_mode = self._sv_ai_prompt.get()  # "Gemini" | "Groq" | "Template (mặc định)" | "📺 TVC Template"
        gen_mode = self._sv_gen_mode.get()  # "API" (REST/bearer) | "Extension" (batchexecute qua trình duyệt thật)

        # Workers per account = upload_threads + 1 (1 luồng dư đang chờ poll/render trong khi các luồng khác upload)
        _sv_cached_wpa = None  # sẽ set riêng cho từng TK bên dưới
        _sv_cached_submit_max = 7.0

        self.settings["sv_remove_wm"] = remove_wm
        self.settings["sv_del_img"] = del_img
        self.settings["sv_ghep_anh"] = ghep_anh
        self.settings["sv_use_laundering"] = sv_use_laundering
        self.settings["sv_naming"] = naming_mode
        self.settings["sv_review_style"] = review_style
        self.settings["sv_ai_prompt"] = ai_mode
        self.settings["sv_gen_mode"] = gen_mode
        self.settings["sv_submit_max"] = _sv_cached_submit_max

        # Lấy keys từ tab Tài khoản (dùng chung)
        sv_gemini_keys = [k.strip() for k in self.txt_gemini.get("1.0", "end").splitlines() if k.strip()]
        sv_groq_key = [k.strip() for k in self.txt_groq_keys.get("1.0", "end").splitlines() if k.strip()]

        # Cache proxy trên main thread trước khi vào worker thread
        try:
            _cached_px_lines = [l.strip() for l in self.txt_proxy.get("1.0", "end").splitlines() if l.strip()]
        except Exception:
            _cached_px_lines = []
        # Gắn mô tả giọng nói cố định vào engine (ưu tiên nhập tay, nếu trống → dùng preset theo ngôn ngữ)
        manual_voice = self.ent_voice_desc.get().strip()
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang(lang_code)
