"""
Shopee Video Creator v3 — Tạo video review sản phẩm từ ảnh SP + ảnh người mẫu + Google Flow AI.
Luồng: Ảnh SP + Ảnh mẫu + Khung cảnh → Google Flow tạo ảnh hoàn thiện
       → Sinh N prompt liền mạch → N video thành phần (i2v) → FFmpeg concat → 1 video hoàn chỉnh.
Không cần scrape Shopee — user cung cấp ảnh + tên SP trực tiếp.
"""
import os, json, time, threading, re, traceback, random, base64, subprocess, tempfile

# ==================== KHUNG CẢNH PRESET ====================
# Mỗi tuple: (tên hiển thị, mô tả tiếng Anh, mô tả tiếng Việt)
SCENES = [
    ("📦 Tổng kho hàng hóa",
     "in a large organized warehouse with neatly stacked product shelves behind, bright industrial lighting",
     "trong nhà kho lớn ngăn nắp với các kệ sản phẩm xếp gọn phía sau, ánh sáng công nghiệp sáng rõ"),
    ("🛒 Siêu thị hiện đại",
     "inside a bright modern supermarket with shiny product displays, spacious shopping environment",
     "bên trong siêu thị hiện đại sáng sủa với các gian hàng trưng bày sản phẩm bóng loáng, không gian mua sắm rộng rãi"),
    ("🎥 Phòng review chuyên nghiệp",
     "in a professional product review studio with clean white background and softbox lighting setup",
     "trong phòng quay đánh giá sản phẩm chuyên nghiệp với phông nền trắng sạch và hệ thống đèn softbox"),
    ("🛋 Phòng khách sang trọng",
     "in a luxurious modern living room with leather sofa, warm golden ambient lighting, elegant decor",
     "trong phòng khách hiện đại sang trọng với sofa da, ánh sáng vàng ấm áp, nội thất thanh lịch"),
    ("💼 Văn phòng hiện đại",
     "in a stylish modern office with glass desk, ergonomic chair, minimalist decor and green plants",
     "trong văn phòng hiện đại phong cách với bàn kính, ghế công thái học, trang trí tối giản và cây xanh"),
    ("🌳 Ngoài trời công viên",
     "outdoors in a beautiful green park with natural sunlight filtering through tree canopy",
     "ngoài trời trong công viên xanh mát với ánh nắng tự nhiên xuyên qua tán cây"),
    ("📸 Studio chụp ảnh",
     "in a professional photo studio with grey backdrop, ring light, clean minimal setup",
     "trong studio chụp ảnh chuyên nghiệp với phông nền xám, đèn ring light, bố trí gọn gàng tối giản"),
    ("🏬 Showroom trưng bày",
     "in an upscale product showroom with glass display shelves and LED spotlight illumination",
     "trong showroom trưng bày sản phẩm cao cấp với kệ kính và đèn LED chiếu điểm"),
    ("☕ Quán café hiện đại",
     "in a stylish modern cafe with wooden table, warm ambient light, cozy relaxing atmosphere",
     "trong quán café hiện đại phong cách với bàn gỗ, ánh sáng ấm áp, không gian thư giãn ấm cúng"),
    ("� Bàn unboxing",
     "at a clean unboxing desk with brown kraft paper, scissors, and packaging materials, bright overhead lighting",
     "tại bàn unboxing gọn gàng với giấy kraft nâu, kéo và vật liệu đóng gói, ánh sáng trên đầu sáng rõ"),
    ("⚖ Bàn so sánh sản phẩm",
     "at a product comparison table with clean white surface, multiple items neatly arranged side by side, professional overhead lighting",
     "tại bàn so sánh sản phẩm với mặt bàn trắng sạch, nhiều sản phẩm xếp gọn cạnh nhau, ánh sáng chuyên nghiệp từ trên"),
    ("📱 Studio livestream",
     "in a professional livestream studio with ring light, camera tripod, colorful LED backdrop, and product display shelf",
     "trong studio livestream chuyên nghiệp với đèn ring light, chân tripod camera, phông nền LED nhiều màu, và kệ trưng bày sản phẩm"),
]

SCENE_NAMES = [s[0] for s in SCENES]
SCENE_MAP_EN = {s[0]: s[1] for s in SCENES}
SCENE_MAP_VI = {s[0]: s[2] for s in SCENES}
SCENE_MAP = SCENE_MAP_EN  # backward compat
SCENE_OPTIONS = ["🎲 Random"] + SCENE_NAMES

DURATION_OPTIONS = ["16s", "24s"]


# ==================== CHỌN KHUNG CẢNH ====================

def pick_scene(user_choice, lang="en"):
    """Trả (scene_name, scene_desc) dựa trên lựa chọn user + ngôn ngữ.
    Nếu '🎲 Random' → random từ SCENES pool.
    Nếu user chọn preset cụ thể → dùng preset đó.
    lang='vi' → trả mô tả tiếng Việt, lang='en' → tiếng Anh.
    """
    smap = SCENE_MAP_VI if lang == "vi" else SCENE_MAP_EN
    default = "trong phòng quay đánh giá chuyên nghiệp" if lang == "vi" else "in a professional review studio"
    if user_choice == "🎲 Random":
        scene = random.choice(SCENES)
        idx = 2 if lang == "vi" else 1
        return scene[0], scene[idx]
    return user_choice, smap.get(user_choice, default)


# ==================== SEGMENT POOL — ENGLISH ====================
# Mỗi clip từ API Google Flow dài ~8 giây.
# → 16s = 2 clip × ~8s, 24s = 3 clip × ~8s
#
# CẤU TRÚC 16s (2 CLIP):
#   Clip 1 (0-8s):  HOOK + DEMO/PAIN — Thu hút + Trình diễn sản phẩm
#   Clip 2 (8-16s): BENEFIT/CLOSE + CTA — Lợi ích + Kêu gọi mua hàng
#
# CẤU TRÚC 24s (3 CLIP):
#   Clip 1 (0-8s):  REVIEW — Đánh giá tổng quan
#   Clip 2 (8-16s): ADVANTAGES — Ưu điểm nổi bật
#   Clip 3 (16-24s): TARGET AUDIENCE + CTA — Đối tượng + Kêu gọi hành động
#
# {lang_instruction} sẽ được thay bằng "The model speaks English" hoặc
# "Người mẫu nói tiếng Việt" tùy ngôn ngữ khi build prompt.

_CONT_EN = (
    "**Directives**\n"
    "- Ensure perfect temporal consistency — the character's face, body, clothing, and the product must remain identical and stable across all frames with no morphing, no identity drift, and no sudden changes.\n"
    "- PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Its color, shape, size, material texture, and all distinguishing features must not change, swap, or gradually transform.\n"
    "- The character naturally and fluidly interacts with the product. Movements must be smooth, realistic. No robotic or dreamy motion.\n"
    "- ITEM PERSISTENCE: Any object the character holds or wears must remain naturally present throughout.\n"
    "\n"
    "**Subject & Character Consistency:**\n"
    "- Character: A 22-year-old {country_en} woman with a bright, cheerful face and natural beauty.\n"
    "- Face & Features: Soft oval face shape, dark brown almond eyes, clear skin, natural rosy blush.\n"
    "- Hair: Shoulder-length, dark brown hair styled in a straight, neat bob.\n"
    "- CRITICAL IDENTITY LOCK: The reviewer's face identity must match the reference image exactly (same facial structure, proportions, eyes, skin tone). Do NOT change makeup, age, or hairstyle.\n"
    "\n"
    "**Environment & Atmosphere:**\n"
    "- {scene}\n"
    "\n"
    "**The Product To Advertise**\n"
    "- Product: {name}\n"
    "- If the attached image includes multiple objects, select ONLY ONE (1) main product as the focal item.\n"
    "\n"
    "**Camera & Tech Specs:**\n"
    "- style: Professional studio product-review video with smooth camera movement and realistic material reproduction.\n"
    "- camera_and_lens: Shot on a professional cinema or full-frame mirrorless camera, 4K DCI/4K UHD – 60fps, high dynamic range, tripod + subtle gimbal stabilization.\n"
    "- color_and_grading: Neutral color calibration, natural skin tones, crisp details, modern bright/clean color grading.\n"
    "\n"
    "**Negative / Constraints:**\n"
    "- No anatomical anomalies, no extra limbs, no extra hands, no extra fingers, no weird hand deformations.\n"
    "- No chaotic or unintended rapid morphing. No slow-motion effects.\n"
    "- No text overlays, no watermarks, no on-screen graphics or UI elements.\n"
    "- Do NOT remove, hide, or make any accessory disappear during the video.\n"
    "[{lang_instruction} throughout the video. The model must speak this exact dialogue: \"{dialogue}\"]\n\n"
)

SEGMENT_POOL_EN = [
    # ──── 16s FORMAT: 2 CLIPS ────
    # 0: CLIP 1 — HOOK + DEMO/PAIN (0-8s)
    (
        _CONT_EN +
        "**Timeline Action for Segment 1 (0-8 seconds):**\n"
        "- The character is a professional product reviewer, speaking confidently and engagingly with a cheerful expression.\n"
        "- Seconds 0-1: Start from the attached reference image as the anchor frame. Apply only a simple fade-in/brightness change. Preserve the reviewer identity, clothing, pose, hand placement, product, and background exactly; only minimal natural motion may begin (blink/breath).\n"
        "- Seconds 1-3: Front-facing camera. The character holds or gently touches '{name}' and begins speaking naturally. Keep the product fully visible in the frame.\n"
        "- Seconds 3-7: Still front-facing. The character highlights key details using subtle gestures: slight tilting/rotating of the product or a gentle pointing motion. Maintain stable framing.\n"
        "- Seconds 7-8 (CRITICAL RETURN TO REFERENCE): Front-facing camera. Cease all motion; the character and product must hold a completely static pose with zero movement. Both the reviewer and the product must remain in sharp focus and clearly visible within the frame. No morphing, no drifting of details."
    ),
    # 1: CLIP 2 — BENEFIT/CLOSE-UP + CTA (8-16s)
    (
        _CONT_EN +
        "**Timeline Action for Segment 2 (8-16 seconds):**\n"
        "- This is a flawless, seamless continuation of the previous video. Start exactly from the static pose of the reference image.\n"
        "- The character remains generally in place, but performs subtle, natural movements. Maintain character and setting consistency.\n"
        "- Seconds 8-10: Maintain the camera angle from the attached image. This is a front view, focusing tightly on the character and the product '{name}'. The character speaks naturally.\n"
        "- Seconds 10-14: Professional close-up shots of the product: texture, materials, buttons, detailed components.\n"
        "- Seconds 14-16: Return to the final front-facing shot with high clarity, where the product '{name}' and the reviewer appear sharp, clean, and well-lit. End with a confident, persuasive smile."
    ),
    # ──── 24s FORMAT: 3 CLIPS (SEAMLESS HANDOFF) ────
    # Kỹ thuật "handoff pose": mỗi clip kết thúc ở tư thế cụ thể,
    # clip tiếp theo bắt đầu từ CHÍNH tư thế đó → liền mạch khi ghép.
    #
    # Clip 1 kết thúc: cầm SP ngang ngực bằng 2 tay, đang nói, medium shot
    # Clip 2 bắt đầu: cầm SP ngang ngực bằng 2 tay, đang nói (tiếp tục)
    # Clip 2 kết thúc: giơ SP lên cạnh mặt bằng 1 tay, tay kia chỉ vào SP
    # Clip 3 bắt đầu: giơ SP cạnh mặt bằng 1 tay (tiếp tục)
    #
    # 2: CLIP 1 — REVIEW (0-8s)
    (
        _CONT_EN +
        "SEGMENT 1 of 3 (0-8 seconds): Product review opening. "
        "CRITICAL: DO NOT start with any greeting, waving, welcoming, or introduction gesture. "
        "NO 'hello', NO waving at camera, NO welcome pose. Start DIRECTLY with product interaction. "
        "The person from the reference image is ALREADY holding '{name}' with both hands at chest level "
        "and carefully examining it from multiple angles — turning it over, inspecting the build quality, "
        "running their fingers along the surface with a thoughtful, analytical expression. "
        "They look at the camera and begin sharing their honest first impressions with natural speaking gestures. "
        "ENDING POSE (IMPORTANT): The clip MUST END with the person holding '{name}' with BOTH HANDS "
        "at CHEST LEVEL, facing the camera, mouth slightly open as if mid-sentence — "
        "this exact pose will be the starting point of the next segment, "
        "{scene}. {lang_instruction} naturally. "
        "The person has the SAME face and wears the SAME outfit as in the reference image. "
        "CAMERA: Steady medium shot (waist-up framing), gentle subtle orbit. "
        "The product is clearly visible and IDENTICAL to the reference image. "
        "Warm cinematic lighting, shallow depth of field."
    ),
    # 3: CLIP 2 — DEMO/TEST HANDS-ON (8-16s)
    (
        _CONT_EN +
        "SEGMENT 2 of 3 (8-16 seconds): Hands-on product demo — seamless continuation. "
        "CRITICAL: DO NOT start with any greeting, waving, welcoming, or introduction. "
        "NO 'hello', NO waving, NO welcome pose. This clip is a SEAMLESS CONTINUATION. "
        "STARTING POSE (MUST MATCH): The person is ALREADY holding '{name}' with BOTH HANDS "
        "at CHEST LEVEL, facing the camera, mid-sentence — continuing directly from where they left off. "
        "From this pose, the person actively DEMONSTRATES '{name}' in action — "
        "flipping it around to show all sides, pressing buttons or opening compartments, "
        "running fingers along the surface to show texture and build quality, "
        "bringing it very close to the camera for a detailed macro view. "
        "Their expression shows genuine satisfaction and pleasant surprise at the quality. "
        "Camera smoothly pushes in for tight close-ups of the product details, texture, and craftsmanship. "
        "ENDING POSE (IMPORTANT): The clip MUST END with the person holding '{name}' UP "
        "with ONE HAND near their FACE level, the other hand pointing at the product — "
        "this exact pose will be the starting point of the next segment, "
        "{scene}. {lang_instruction}. "
        "SAME person, SAME face, SAME outfit, SAME background — no changes to appearance. "
        "The product must look EXACTLY like the reference image. "
        "Same warm cinematic lighting as the previous segment."
    ),
    # 4: CLIP 3 — TARGET AUDIENCE + CTA (16-24s)
    (
        _CONT_EN +
        "SEGMENT 3 of 3 (16-24 seconds): Final call to action — seamless continuation to the end. "
        "CRITICAL: DO NOT start with any greeting, waving, welcoming, or introduction. "
        "NO 'hello', NO waving, NO welcome pose. This clip is a SEAMLESS CONTINUATION. "
        "STARTING POSE (MUST MATCH): The person is ALREADY holding '{name}' UP "
        "with ONE HAND near their FACE level — continuing directly from where they left off. "
        "From this pose, the person smoothly transitions to speaking directly to the camera with a warm, relatable tone, "
        "using inclusive hand gestures — pointing toward the viewer, open palm gestures, "
        "as if personally recommending the product to different types of people. "
        "Then they hold '{name}' up prominently with both hands, looking directly into the camera "
        "with a confident, persuasive smile. They give an enthusiastic double thumbs-up, "
        "then gesture invitingly toward the camera as if saying 'go get yours now!' "
        "with irresistible energy and conviction, "
        "{scene}. {lang_instruction}. "
        "SAME person, SAME face, SAME outfit, SAME background as all previous shots — identity must not change. "
        "The product must be a PIXEL-PERFECT copy from the reference image. "
        "CAMERA: Medium shot with gentle push-in, then slow cinematic zoom out to wide shot. "
        "Warm, trustworthy final expression. Professional product endorsement ending."
    ),
]



TTS_MIDDLES_VI = [
    "Nhìn thiết kế quá mượt mà, đường nét vô cùng tinh xảo, cầm rất chắc tay.",
    "Chất liệu của nó xịn xò lắm, sờ vào cảm giác cao cấp khác bọt hẳn.",
    "Khi dùng thử tôi mới thấy nó đa năng và vi diệu hơn quảng cáo rất nhiều.",
    "Hàng chuẩn từng centimet, màu sắc thì đẹp y hệt hình mẫu, quá mãn nhãn.",
    "Càng nhìn kỹ càng thấy độ tinh tế, nhà sản xuất chăm chút từng tiểu tiết.",
    "Không chỉ đẹp mã, mà công dụng của nó thực sự giải quyết bao rắc rối cho tôi.",
    "Nó hoạt động cực êm ái, nhẹ nhàng mà lại rất chắc chắn và an toàn nha.",
    "Tôi test đủ kiểu rồi, xài vẫn siêu bền, xứng đáng từng đồng mình bỏ ra.",
    "Form dáng hoàn hảo, màu sắc bắt mắt, nói chung không có điểm nào để chê.",
    "Phải công nhận là từ khi xài nó, tôi thấy tiện lợi và tiết kiệm bao thời gian.",
    "Để gần soi kỹ thì chẳng thấy lỗi nhỏ nào, độ hoàn thiện xứng đáng 10 điểm.",
    "Trải nghiệm thực tế mới hiểu tại sao ai cũng săn lùng cái này nhiệt tình vậy.",
    "Công năng thì tuyệt hảo, kích thước lại nhỏ gọn không chiếm nhiều diện tích.",
    "Điều tôi ưng nhất là độ nhẹ nhàng êm ái khi tương tác, rất thư giãn.",
    "Từ độ bền đến thẩm mỹ đều làm tôi phải trầm trồ ngạc nhiên luôn đấy."
]

TTS_ENDINGS_VI = [
    "Chốt lại là quá hời! Các bà nhấp ngay vào giỏ hàng dốt đơn nhé.",
    "Không mua sớm là tiếc hùi hụi đó, link gốc tôi để ở góc trái màn hình nha.",
    "Shop đang có flash sale cực hời, tranh thủ chốt đơn kẻo hết nha mọi người.",
    "Túm lại là nên mua! Xứng đáng 100 điểm, ấn ngay biểu tượng giỏ hàng nhé.",
    "Cầm trên tay là ưng ngay, các tình yêu ấn ngay vào giỏ vàng nha.",
    "Ai cũng cần một em như này, tôi gắn link giỏ hàng bên dưới góc trái rồi đó.",
    "Nghe mị đi, bấm mua liền đi, chắc chắn sẽ không làm bạn thất vọng đâu.",
    "Shop đang hỗ trợ freeship nữa, ngại gì không nhấp vào giỏ hàng chốt đơn.",
    "Quá ngon bổ rẻ, hàng hiếm đó! Múc lẹ múc lẹ kẻo cháy hàng mấy bà ơi.",
    "Đừng lăn tăn nữa, ấn ngay giỏ hàng xách liền môt em về dùng thử xem.",
    "Khách quen nhà tôi đều khen nức nở, link uy tín nằm dưới góc trái màn hình nha.",
    "Tiền nào của nấy mà em này lại quá rẻ so với chất lượng, quất ngay đi!",
    "Bảo bối thần thánh nằm trong giỏ hàng góc trái, nhanh tay kẻo muộn nha mấy bồ.",
    "Nhanh tay thì còn, chậm tay thì hết. Tôi mua rồi còn các bà thì sao?",
    "Mọi người ấn ngay nút mua góc dưới nhé, hàng chuẩn Auth không lo gì luôn!"
]

TTS_MIDDLES_ID = [
    "Desainnya sangat mulus, detailnya rapi, dan nyaman digenggam.",
    "Bahannya sangat berkualitas, terasa premium saat disentuh.",
    "Setelah mencoba, ternyata fiturnya jauh lebih canggih daripada iklannya.",
    "Sangat presisi, warnanya persis seperti di foto, sangat memuaskan.",
    "Melihat lebih dekat, detailnya sangat diperhatikan oleh produsen.",
    "Tidak hanya bagus penampilannya, tapi sangat membantu menyelesaikan masalah saya.",
    "Kerjanya sangat halus, ringan tapi tetap kokoh dan aman.",
    "Saya sudah tes berkali-kali, terbukti awet dan sangat bernilai.",
    "Bentuknya sempurna, warnanya menarik, tidak ada kekurangan.",
    "Sangat praktis dan menghemat banyak waktu saya sejak menggunakannya.",
    "Dilihat dari dekat pun tidak ada cacat, kualitasnya bintang sepuluh.",
    "Sekarang saya paham kenapa produk ini sangat viral dan banyak dicari.",
    "Fungsinya luar biasa, ukurannya ringkas tidak memakan tempat.",
    "Yang paling saya suka adalah sensasi nyaman saat menggunakannya.",
    "Daya tahan dan estetikanya benar-benar membuat saya kagum."
]

TTS_ENDINGS_ID = [
    "Kesimpulannya ini sangat menguntungkan! Buruan klik keranjang kuning ya.",
    "Jangan sampai menyesal, link pembelian ada di sudut kiri bawah layar.",
    "Toko lagi ada flash sale besar, langsung checkout sebelum kehabisan.",
    "Sangat direkomendasikan! Nilai 100, klik ikon keranjang sekarang.",
    "Begitu dipegang langsung suka, yuk klik keranjang kuning.",
    "Semua orang butuh ini, link toko ada di bawah kiri.",
    "Percayalah, langsung beli sekarang, dijamin tidak menyesal.",
    "Ada promo gratis ongkir juga, tunggu apa lagi, langsung checkout.",
    "Murah tapi berkualitas, stok terbatas, langsung beli sekarang.",
    "Jangan ragu lagi, klik keranjang sekarang dan cobain sendiri."
]

TTS_MIDDLES_PH = [
    "Napakaganda ng disenyo, napakapino ng mga detalye, at napakasarap hawakan.",
    "Napakaganda ng kalidad ng materyal, premium ang pakiramdam kapag hinawakan.",
    "Nang subukan ko, mas maganda at advanced ang mga feature kaysa sa nakikita sa ad.",
    "Eksakto ang sukat, parehong-pareho ang kulay sa larawan, napakasiya ko.",
    "Kapag tiningnan nang malapitan, makikitang pulido ang pagkakagawa sa bawat detalye."
]

TTS_MIDDLES_EN = [
    "It is incredibly designed with premium materials, making it feel very high-quality.",
    "The overall build is sturdy and highly functional, perfect for daily usage.",
    "It exceeded all my expectations with its outstanding design and usability.",
    "This product is a game-changer for me and has solved so many of my problems.",
    "The shape is elegant and the color is gorgeous, absolutely no flaws to complain about.",
    "Even when inspected closely, there are no defects whatsoever, 10 out of 10.",
    "It is lightweight yet very durable, making it highly portable and convenient.",
    "I highly recommend this to everyone looking for a reliable and stylish solution."
]

TTS_ENDINGS_EN = [
    "You definitely need this, I put the purchase link in the bottom left corner.",
    "Don't miss this opportunity, grab yours now before the sale ends.",
    "Click the yellow cart below to checkout right now, you won't regret it.",
    "It is very affordable yet high quality, limited stock, so buy it now.",
    "There is also free shipping available, checkout immediately to save big."
]

TTS_ENDINGS_PH = [
    "Sa pangkalahatan, sulit na sulit! I-click na ang dilaw na cart ngayon.",
    "Huwag nang mag-atubili, ang link ng produkto ay nasa ibabang kaliwang bahagi.",
    "May malaking flash sale ngayon, mag-checkout na bago maubusan.",
    "Dapat itong bilhin! 100 points, i-click ang icon ng cart.",
    "Magugustuhan mo kapag hinawakan mo, i-click ang dilaw na cart.",
    "Kailangan ito ng lahat, inilagay ko ang link sa ibabang kaliwa.",
    "Maniwala ka sa index, bilhin mo na ngayon, hindi ka magsisi.",
    "May libreng shipping din ang shop, i-checkout na ang order mo.",
    "Mura at magandang kalidad, limited stock lang, bili na ngayon.",
    "Huwag nang magdalawang-isip, i-click ang cart ngayon at subukan."
]

def generate_tts_script(product_name, segment_index, total_segments, lang="vi"):
    import random
    seed_val = sum(ord(c) for c in product_name)
    rng = random.Random(seed_val)
    
    if lang == "vi":
        middles_pool = TTS_MIDDLES_VI
        endings_pool = TTS_ENDINGS_VI
        prefix_format = "Đối với {name}, "
        prefix_format_24s = "Về {name}, "
    elif lang == "id":
        middles_pool = TTS_MIDDLES_ID
        endings_pool = TTS_ENDINGS_ID
        prefix_format = "Untuk {name}, "
        prefix_format_24s = "Mengenai {name}, "
    elif lang == "ph":  # Tagalog (Philippines)
        middles_pool = TTS_MIDDLES_PH
        endings_pool = TTS_ENDINGS_PH
        prefix_format = "Para sa {name}, "
        prefix_format_24s = "Tungkol sa {name}, "
    else:  # en (English default)
        middles_pool = TTS_MIDDLES_EN
        endings_pool = TTS_ENDINGS_EN
        prefix_format = "For {name}, "
        prefix_format_24s = "About {name}, "
        
    middles = rng.sample(middles_pool, 2)
    ending = rng.choice(endings_pool)
    
    if total_segments == 2:
        if segment_index == 0:
            feat1 = middles[0]
            prefix = prefix_format.format(name=product_name)
            return prefix + feat1[0].lower() + feat1[1:]
        else:
            feat2 = middles[1]
            return feat2 + " " + ending
    else:
        if segment_index == 0:
            feat1 = middles[0]
            prefix = prefix_format_24s.format(name=product_name)
            return prefix + feat1[0].lower() + feat1[1:]
        elif segment_index == 1:
            return middles[1]
        else:
            return ending

def generate_audio_file(text, output_path, voice="vi-VN-HoaiMyNeural"):
    """Sử dụng subprocess để gọi edge-tts (chặn cmd window) nhằm tạo file .wav miễn phí"""
    import subprocess, os
    cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", output_path]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        if res.returncode == 0 and os.path.exists(output_path):
            return True
        return False
    except Exception as e:
        print(f"generate_audio_file exception: {e}")
        return False

def generate_gemini_audio_file(text, output_path, voice="Achernar", keys=None):
    """Sử dụng Google Gemini API để tạo audio TTS (cần cài google-genai)"""
    import os, time, wave
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Lỗi: Cần cài đặt thư viện google-genai (pip install google-genai) để dùng Gemini TTS.")
        return False
    
    if not keys: return False
    
    import random
    for k in keys:
        try:
            client = genai.Client(api_key=k)
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        )
                    )
                )
            )
            data = response.candidates[0].content.parts[0].inline_data.data
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(data)
            return True
        except Exception as e:
            print(f"Lỗi Gemini TTS với key {k[:6]}... : {e}")
            time.sleep(2)
            continue
    return False

# ==================== SEGMENT POOL — TIẾNG VIỆT ====================

_CONT_VI = (
    "**Directives**\n"
    "- Đây là video được kết nối liền mạch. Khuôn mặt, cơ thể, trang phục của nhân vật và sản phẩm phải giữ nguyên định dạng, không bị biến dạng hay thay đổi danh tính.\n"
    "- KHÓA TOÀN VẸN SẢN PHẨM: Sản phẩm xuất hiện ở giây đầu tiên phải CHÍNH XÁC LÀ CÙNG MỘT SẢN PHẨM trong mọi khung hình sau đó. Màu sắc, hình dáng, kích thước, kết cấu vật liệu không được lay chuyển.\n"
    "- Nhân vật tương tác tự nhiên với sản phẩm. Chuyển động phải mượt mà, chân thực. Không có hiệu ứng slow-motion hay múa dưỡng sinh bay bổng.\n"
    "- TÍNH BỀN VỮNG CỦA PHỤ KIỆN: Bất kỳ đồ vật, trang sức nào nhân vật mặc lúc đầu phải được giữ nguyên. Không tự ý ẩn hay làm biến mất đồ vật.\n"
    "\n"
    "**Subject & Character Consistency:**\n"
    "- Character: Một người phụ nữ trẻ {country_vi} 22 tuổi, khuôn mặt rạng rỡ tươi tắn, vẻ đẹp tự nhiên.\n"
    "- Face & Features: Mặt trái xoan mềm mại, mắt hạnh nhân nâu đen, da sáng khỏe, má hồng ửng nhẹ tự nhiên.\n"
    "- Hair: Tóc nâu đen ngang vai, cắt bob duỗi thẳng gọn gàng.\n"
    "- KHÓA DANH TÍNH (CRITICAL): Khuôn mặt người review phải khớp CHÍNH XÁC 100% với ảnh tham chiếu. KHÔNG tự ý đổi lớp trang điểm, độ tuổi, kiểu tóc hay thêm phụ kiện.\n"
    "\n"
    "**Environment & Atmosphere:**\n"
    "- {scene}\n"
    "\n"
    "**The Product To Advertise**\n"
    "- Sản phẩm: {name}\n"
    "- Nếu khung hình có nhiều đồ vật, CHỈ TẬP TRUNG vào một sản phẩm chính duy nhất.\n"
    "\n"
    "**Camera & Tech Specs:**\n"
    "- style: Chuyên nghiệp, đánh giá sản phẩm trong studio với chuyển động máy quay mượt mà, vật liệu chân thực.\n"
    "- camera_and_lens: Quay bằng dòng Cinema hoặc ngàm full-frame, 4K 60fps, chống rung gimbal tinh tế.\n"
    "- color_and_grading: Màu sắc cân bằng trung tính, màu da người thật, chi tiết sắc nét, hiện đại.\n"
    "\n"
    "**Negative / Constraints:**\n"
    "- Tuyệt đối KHÔNG sinh thêm tay, KHÔNG sinh thêm chi, KHÔNG thừa ngón tay, KHÔNG biến dạng bàn tay.\n"
    "- Không chuyển đổi hình khối hỗn loạn. Không có hiệu ứng làm chậm slow-mo.\n"
    "- Tuyệt đối KHÔNG chèn văn bản (text), logo, watermark hay các phần tử UI lên màn hình video.\n"
    "- KHÔNG tráo đổi sản phẩm sang biến thể khác.\n"
    "[{lang_instruction} trong suốt video. Người mẫu phải nói chính xác đoạn thoại sau: \"{dialogue}\"]\n\n"
)

SEGMENT_POOL_VI = [
    # ──── 16s FORMAT: 2 CLIPS ────
    # 0: CLIP 1 — HOOK + DEMO/PAIN (0-8s)
    (
        _CONT_VI +
        "**Timeline Action cho Đoạn 1 (0-8 giây):**\n"
        "- Nhân vật là một reviewer chuyên nghiệp, nói chuyện tự tin, cuốn hút với nét mặt rạng rỡ.\n"
        "- Giây 0-1: Bắt đầu từ ảnh tham chiếu làm khung neo giữ. Chỉ áp dụng hiệu ứng mờ dần sáng lên. Giữ nguyên 100% người review, trang phục, dáng tay, sản phẩm và cảnh nền; chỉ có chuyển động chớp mắt/thở tự nhiên.\n"
        "- Giây 1-3: Góc máy trực diện. Nhân vật cầm hoặc chạm nhẹ vào '{name}' và bắt đầu nói chuyện tự nhiên. Giữ sản phẩm luôn rõ ràng trong khung hình.\n"
        "- Giây 3-7: Góc máy giữ nguyên trực diện. Nhân vật nhấn mạnh các chi tiết nổi bật bằng thao tác tay nhẹ nhàng: hơi nghiêng/xoay sản phẩm hoặc chỉ ngón tay tinh tế.\n"
        "- Giây 7-8 (QUAN TRỌNG: TRỞ LẠI NEO GIỮ): Góc trực diện. BẮT BUỘC DỪNG MỌI CHUYỂN ĐỘNG; nhân vật và sản phẩm chốt thẳng ở một tư thế tĩnh hoàn toàn (Zero movement). Không bị biến dạng vật thể hay dịch chuyển."
    ),
    # 1: CLIP 2 — BENEFIT/CLOSE-UP + CTA (8-16s)
    (
        _CONT_VI +
        "**Timeline Action cho Đoạn 2 (8-16 giây):**\n"
        "- Đây là sự tiếp nối hoàn hảo và liền mạch từ video trước. Bắt đầu CHÍNH XÁC từ tư thế đứng tĩnh của ảnh tham chiếu.\n"
        "- Nhân vật tiếp tục đứng ở vị trí cũ, thực hiện chuyển động nhẹ nhàng tự nhiên.\n"
        "- Giây 8-10: Giữ nguyên góc máy như ảnh tham chiếu. Ở góc trực diện, tập trung chặt vào nhân vật và sản phẩm '{name}'. Nhân vật đang nói chuyện.\n"
        "- Giây 10-14: CAMERA CẨN CẢNH (Close-up b-roll) sản phẩm: lướt qua kết cấu vật liệu, nút bấm, chất liệu bên ngoài cực sắc nét.\n"
        "- Giây 14-16: Camera quay trở lại khuôn mặt trực diện. Sản phẩm '{name}' và người mẫu đều rõ nét, sạch sẽ và bắt sáng hoàn hảo. Kết thúc bằng nụ cười chốt sale tự tin."
    ),
    # ──── 24s FORMAT: 3 CLIPS (LIỀN MẠCH HANDOFF) ────
    # Kỹ thuật "handoff pose": mỗi clip kết thúc ở tư thế cụ thể,
    # clip tiếp theo bắt đầu từ CHÍNH tư thế đó → liền mạch khi ghép.
    #
    # Clip 1 kết thúc: cầm SP ngang ngực bằng 2 tay, đang nói, medium shot
    # Clip 2 bắt đầu: cầm SP ngang ngực bằng 2 tay, đang nói (tiếp tục)
    # Clip 2 kết thúc: giơ SP lên cạnh mặt bằng 1 tay, tay kia chỉ vào SP
    # Clip 3 bắt đầu: giơ SP cạnh mặt bằng 1 tay (tiếp tục)
    #
    # 2: CLIP 1 — ĐÁNH GIÁ (0-8s)
    (
        _CONT_VI +
        "ĐOẠN 1 trên 3 (0-8 giây): Mở đầu đánh giá sản phẩm. "
        "QUAN TRỌNG: KHÔNG được bắt đầu bằng lời chào, vẫy tay, chào mừng, hay giới thiệu. "
        "KHÔNG 'xin chào', KHÔNG vẫy tay vào camera, KHÔNG tư thế chào đón. Bắt đầu TRỰC TIẾP với hành động sản phẩm. "
        "Người trong ảnh tham chiếu ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC "
        "và quan sát kỹ lưỡng từ nhiều góc — xoay qua xoay lại, kiểm tra chất lượng gia công, "
        "lướt ngón tay trên bề mặt với biểu cảm suy nghĩ, phân tích. "
        "Nhìn vào camera và bắt đầu chia sẻ cảm nhận ban đầu với cử chỉ nói chuyện tự nhiên. "
        "TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với người cầm '{name}' bằng HAI TAY "
        "ở tầm NGANG NGỰC, mặt hướng camera, miệng hơi mở như đang nói dở — "
        "tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo, "
        "{scene}. {lang_instruction}. "
        "CÙNG khuôn mặt, CÙNG trang phục như ảnh tham chiếu. "
        "CAMERA: Medium shot ổn định (khung hình ngang hông trở lên), xoay nhẹ tinh tế. "
        "Sản phẩm rõ ràng và GIỐNG HỆT ảnh tham chiếu. "
        "Ánh sáng điện ảnh ấm, độ sâu trường ảnh nông."
    ),
    # 3: CLIP 2 — DEMO/TEST THỰC TẾ (8-16s)
    (
        _CONT_VI +
        "ĐOẠN 2 trên 3 (8-16 giây): Trình diễn sản phẩm thực tế — tiếp nối liền mạch. "
        "QUAN TRỌNG: KHÔNG được bắt đầu bằng lời chào, vẫy tay, chào mừng, hay giới thiệu. "
        "KHÔNG vẫy tay, KHÔNG chào đón. Đây là ĐOẠN TIẾP NỐI LIỀN MẠCH. "
        "TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): Người ĐANG cầm '{name}' bằng HAI TAY "
        "ở tầm NGANG NGỰC, mặt hướng camera, đang nói dở — tiếp tục trực tiếp từ chỗ dừng. "
        "Từ tư thế này, người chủ động TRÌNH DIỄN '{name}' thực tế — "
        "lật qua lật lại để xem mọi mặt, nhấn nút hoặc mở ngăn, "
        "lướt ngón tay trên bề mặt để cảm nhận chất liệu và độ hoàn thiện, "
        "đưa sản phẩm rất gần camera để xem cận cảnh chi tiết macro. "
        "Biểu cảm thể hiện sự hài lòng chân thực và ngạc nhiên thú vị về chất lượng. "
        "Camera push-in mượt mà cho cận cảnh chi tiết bề mặt, chất liệu, độ gia công. "
        "TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với người giơ '{name}' LÊN CAO "
        "bằng MỘT TAY gần tầm MẶT, tay kia đang chỉ vào sản phẩm — "
        "tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo, "
        "{scene}. {lang_instruction}. "
        "CÙNG người, CÙNG khuôn mặt, CÙNG trang phục, CÙNG phông nền — không thay đổi. "
        "Sản phẩm phải GIỐNG HỆT ảnh tham chiếu. "
        "Ánh sáng điện ảnh ấm giống đoạn trước."
    ),
    # 4: CLIP 3 — ĐỐI TƯỢNG + CTA (16-24s)
    (
        _CONT_VI +
        "ĐOẠN 3 trên 3 (16-24 giây): Kêu gọi hành động cuối cùng — tiếp nối liền mạch đến kết thúc. "
        "QUAN TRỌNG: KHÔNG được bắt đầu bằng lời chào, vẫy tay, chào mừng, hay giới thiệu. "
        "KHÔNG vẫy tay, KHÔNG chào đón. Đây là ĐOẠN TIẾP NỐI LIỀN MẠCH. "
        "TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): Người ĐANG giơ '{name}' LÊN CAO "
        "bằng MỘT TAY gần tầm MẶT — tiếp tục trực tiếp từ chỗ dừng. "
        "Từ tư thế này, người chuyển sang nói trực tiếp vào camera với giọng ấm áp, gần gũi, "
        "dùng cử chỉ tay bao quát — chỉ về phía người xem, cử chỉ lòng bàn tay mở, "
        "như đang giới thiệu sản phẩm cho nhiều nhóm người khác nhau. "
        "Sau đó giơ '{name}' lên nổi bật bằng cả hai tay, nhìn thẳng camera "
        "với nụ cười tự tin, thuyết phục. Giơ hai ngón cái lên nhiệt tình, "
        "rồi ra hiệu mời gọi về phía camera như nói 'mua ngay đi!' "
        "với năng lượng và sự thuyết phục không thể cưỡng lại, "
        "{scene}. {lang_instruction}. "
        "CÙNG người, CÙNG khuôn mặt, CÙNG trang phục, CÙNG phông nền — danh tính không được thay đổi. "
        "Sản phẩm GIỐNG HỆT ảnh tham chiếu. "
        "CAMERA: Medium shot với push-in nhẹ, rồi zoom ra điện ảnh chậm sang cảnh rộng. "
        "Biểu cảm cuối ấm áp, đáng tin cậy. Kết thúc chuyên nghiệp."
    ),
]

# 16s: indices 0-1 (2 clip × ~8s), 24s: indices 2-4 (3 clip × ~8s)
DURATION_MAP = {
    16: [0, 1],     # 16s = 2 clip × ~8s
    24: [2, 3, 4],  # 24s = 3 clip × ~8s
}

LANG_OPTIONS = ["Tiếng Việt", "Tiếng Philippines", "Tiếng Indonesia", "Tiếng Anh"]

_LANG_MAP = {
    "ph": {
        "instruction": "The model speaks Filipino",
        "country_en": "Filipino",
        "country_vi": "Philippines"
    },
    "vi": {
        "instruction": "Người mẫu nói tiếng Việt",
        "country_en": "Vietnamese",
        "country_vi": "Việt Nam"
    },
    "id": {
        "instruction": "The model speaks Indonesian",
        "country_en": "Indonesian",
        "country_vi": "Indonesia"
    },
    "en": {
        "instruction": "The model speaks English",
        "country_en": "American",
        "country_vi": "Mỹ"
    }
}


# ==================== PROMPT BUILDERS ====================

def build_image_prompt(product_name, scene_en, lang="en"):
    """Tạo prompt cho Google Flow generate_image.
    Kết hợp: người mẫu (từ ảnh tham chiếu) + sản phẩm (từ ảnh SP) + khung cảnh.
    """
    if lang == "vi":
        prompt = (
            f"Ảnh chụp đánh giá sản phẩm chuyên nghiệp. Người trong ảnh tham chiếu "
            f"đang cầm và giới thiệu tự nhiên sản phẩm '{product_name}', {scene_en}. "
            f"Trang phục của cô ấy lịch sự, thanh lịch, không hở hang hay phản cảm. "
            f"QUAN TRỌNG NHẤT: Sản phẩm phải là bản sao CHÍNH XÁC PIXEL-PERFECT từ ảnh tham chiếu — giữ nguyên 100% hình dạng, "
            f"màu sắc, logo, nhãn mác, bao bì. "
            f"TẤT CẢ chữ viết, ký tự, tên thương hiệu, thành phần, mã vạch in trên sản phẩm phải giữ nguyên TẪNGKÝ TỰ — "
            f"cùng font, cùng kích cỡ, cùng vị trí, cùng ngôn ngữ. KHÔNG được bịa, thay thế, làm mờ, hay biến dạng chữ trên SP. "
            f"KHÔNG được thay đổi, thiết kế lại, hay tưởng tượng lại bất kỳ chi tiết nào. "
            f"Sản phẩm được nhìn rõ ràng và nổi bật trong khung hình. "
            f"Chụp thương mại chất lượng cao, ánh sáng chuyên nghiệp, lấy nét sắc, "
            f"tư thế tự tin tự nhiên. Siêu thực, chất lượng 8K, bố cục điện ảnh."
        )
    else:
        prompt = (
            f"Professional product review photograph. The person from the reference image "
            f"is naturally presenting and holding the product '{product_name}', {scene_en}. "
            f"Her outfit is elegant, polite, and modest; NOT revealing or inappropriate. "
            f"MOST CRITICAL: The product must be a PIXEL-PERFECT, EXACT DUPLICATE from the reference image. "
            f"ALL text, letters, characters, brand names, logos, labels, ingredient lists, barcodes, and printed information "
            f"on the product MUST be reproduced CHARACTER-BY-CHARACTER exactly as they appear in the reference image — "
            f"same font, same size, same position, same language, same spelling. DO NOT invent, replace, blur, or distort any text on the product. "
            f"DO NOT alter, redesign, or reimagine its shape, color, packaging, or any visual detail whatsoever. "
            f"The product is clearly visible and prominently featured in the frame. "
            f"High quality commercial photography, professional lighting, sharp focus, "
            f"natural confident pose. Ultra realistic, 8K quality, cinematic composition."
        )
    return prompt


def build_video_prompts(product_name, scene_en, duration_sec=16, lang="en", review_style="Review tự nhiên"):
    """Sinh list prompt liền mạch dựa trên độ dài video (16s hoặc 24s).
    Tất cả prompt dùng CÙNG khung cảnh + trang phục + ánh sáng
    → đảm bảo đồng bộ visual giữa các đoạn.
    Ngôn ngữ nói được đồng bộ qua {lang_instruction} placeholder.
    """
    pool = SEGMENT_POOL_VI if lang == "vi" else SEGMENT_POOL_EN
    indices = DURATION_MAP.get(duration_sec, DURATION_MAP[16])
    lang_info = _LANG_MAP.get(lang, _LANG_MAP["en"])
    n_segments = len(indices)
    
    prompts = []
    for i, idx in enumerate(indices):
        dialogue = generate_tts_script(product_name, i, n_segments, lang=lang)
        prompt = pool[idx].format(
            name=product_name,
            scene=scene_en,
            lang_instruction=lang_info["instruction"],
            country_en=lang_info["country_en"],
            country_vi=lang_info["country_vi"],
            dialogue=dialogue
        )
        if review_style == "Ngồi Review":
            if lang == "vi":
                sitting_constraint = "[ĐIỀU CHỈNH BỐ CỤC: Người dẫn/reviewer ngồi lịch sự phía sau một chiếc bàn gỗ tối giản trong suốt video. Mọi hành động diễn ra tại bàn này. Không đứng hoặc đi lại. Luôn giữ tư thế ngồi sau bàn. Sản phẩm được đặt trên bàn hoặc được cầm trên tay phía trên mặt bàn.]\n\n"
            else:
                sitting_constraint = "[LAYOUT CONSTRAINT: The presenter is sitting politely behind a clean, minimalist wooden desk throughout the video. All actions are performed while seated at this desk. Do not show the presenter standing or walking. Keep her seated behind the desk. The product is either placed on the desk or held above it.]\n\n"
            prompt = sitting_constraint + prompt
        prompts.append(prompt)
    return prompts


# ==================== FALLBACK PROMPTS (khi hết quota tạo ảnh) ====================
# Dùng khi TẤT CẢ account hết quota generate_image → không tạo được ảnh composite.
# Ảnh reference CHỈ CÓ sản phẩm → prompt phải MÔ TẢ MC bằng text.
# Vẫn dùng I2V (image-to-video) với ảnh SP làm reference.
# Handoff pose: cuối clip N = đầu clip N+1 → liền mạch khi ghép.
# {hair} và {outfit} được random mỗi sản phẩm → video luôn mới mẻ.

_HAIR_POOL_EN = [
    "long straight black hair",
    "shoulder-length wavy brown hair",
    "short bob cut with dark hair",
    "long curly dark brown hair",
    "medium-length straight hair with subtle highlights",
    "ponytail with bangs, dark hair",
    "long flowing hair with soft waves",
    "elegant updo hairstyle with loose strands",
]

_HAIR_POOL_VI = [
    "tóc đen dài thẳng",
    "tóc nâu ngang vai hơi xoăn",
    "tóc ngắn kiểu bob đen",
    "tóc nâu đen dài xoăn tự nhiên",
    "tóc thẳng dài vừa có highlight nhẹ",
    "tóc buộc đuôi ngựa với mái trước, tóc đen",
    "tóc dài bồng bềnh xoăn sóng nhẹ",
    "tóc búi cao thanh lịch với vài lọn rơi",
]

_OUTFIT_POOL_EN = [
    "a crisp white blouse tucked into high-waisted beige trousers",
    "a soft pastel pink knit sweater with dark jeans",
    "a light blue button-down shirt with rolled sleeves and cream skirt",
    "a classic striped navy-and-white top with tailored pants",
    "an elegant sage green midi dress with subtle floral pattern",
    "a warm beige turtleneck with a brown corduroy skirt",
    "a lavender cardigan over a white camisole with light gray trousers",
    "a chic camel blazer over a black turtleneck with dark slacks",
]

_OUTFIT_POOL_VI = [
    "áo sơ mi trắng bỏ trong quần tây beige cạp cao",
    "áo len hồng pastel nhẹ nhàng phối quần jeans đen",
    "áo sơ mi xanh nhạt xắn tay phối chân váy kem",
    "áo kẻ sọc xanh navy-trắng cổ điển phối quần tây",
    "váy midi xanh lá nhạt thanh lịch có họa tiết hoa nhẹ",
    "áo cổ lọ beige ấm áp phối chân váy nhung nâu",
    "áo cardigan tím lavender khoác ngoài áo hai dây trắng phối quần xám nhạt",
    "áo blazer camel lịch lãm khoác ngoài áo cổ lọ đen phối quần tây đen",
]

_CONT_FALLBACK_EN = (
    "[CONTINUITY: This is one continuous single-take video. "
    "THE PRESENTER: A beautiful {country_en} woman, approximately 20 years old. She has {hair}. She wears {outfit} — her clothing is polite, not revealing or inappropriate. "
    "CRITICAL — The presenter must have the EXACT SAME face, facial features, skin tone, hairstyle, "
    "hair color, body build, and outfit throughout ALL segments — DO NOT change her identity or clothing. "
    "The background, lighting, color grading remain IDENTICAL across all shots. "
    "PRODUCT INTEGRITY (MOST IMPORTANT): The product is shown in the reference image. "
    "It must be a PIXEL-PERFECT, EXACT DUPLICATE from the reference image in every frame. "
    "DO NOT alter, redesign, reimagine, or regenerate ANY detail of the product. "
    "ALL text, letters, brand names, logos, labels on the product "
    "MUST be reproduced CHARACTER-BY-CHARACTER exactly as in the reference image. "
    "REALISTIC PRODUCT SIZE (CRITICAL): The product MUST have its REAL-LIFE, NATURAL size proportional to the human body. "
    "DO NOT enlarge or exaggerate the product size — it must look exactly as it would in real life when held by a person. "
    "A small product (cosmetics, phone, bottle) should be small in the person's hands, NOT oversized. "
    "ABSOLUTELY NO overlay text, subtitles, captions, titles, or watermarks on the video screen. "
    "NO anatomical anomalies, no extra limbs, no extra hands, no extra fingers, no weird hand deformations. "
    "{lang_instruction} throughout the video. The presenter must speak this exact dialogue: \"{dialogue}\"] "
)

_CONT_FALLBACK_VI = (
    "[LIÊN TỤC: Đây là một video quay liền mạch không cắt. "
    "NGƯỜI DẪN: Một phụ nữ {country_vi} xinh đẹp, khoảng 20 tuổi. Cô có {hair}. Cô mặc {outfit} — trang phục của người phụ nữ lịch sự, không hở hang hay phản cảm. "
    "QUAN TRỌNG — Người dẫn phải có ĐÚNG khuôn mặt, đặc điểm gương mặt, màu da, kiểu tóc, "
    "vóc dáng, và trang phục GIỐNG HỆT nhau xuyên suốt TẤT CẢ các đoạn — KHÔNG thay đổi danh tính hay quần áo. "
    "Phông nền, ánh sáng, tông màu phải GIỐNG HỆT nhau giữa các cảnh. "
    "TOÀN VẸN SẢN PHẨM (QUAN TRỌNG NHẤT): Sản phẩm được hiển thị trong ảnh tham chiếu. "
    "Phải là BẢN SAO CHÍNH XÁC PIXEL-PERFECT từ ảnh tham chiếu trong mọi khung hình. "
    "KHÔNG được thay đổi, thiết kế lại, hay tưởng tượng lại BẤT KỲ chi tiết nào. "
    "TẤT CẢ chữ viết, tên thương hiệu, logo, nhãn mác trên sản phẩm phải giữ nguyên TỪNG KÝ TỰ. "
    "KÍCH THƯỚC SẢN PHẨM THỰC TẾ (QUAN TRỌNG): Sản phẩm PHẢI có kích thước CHUẨN như đời thật, tỷ lệ tự nhiên so với cơ thể người. "
    "KHÔNG được phóng to hay phóng đại kích thước sản phẩm — phải trông giống hệt khi cầm trên tay ngoài đời thực. "
    "Sản phẩm nhỏ (mỹ phẩm, điện thoại, chai lọ) phải NHỎ trong tay người, KHÔNG được to quá cỡ. "
    "TUYỆT ĐỐI KHÔNG hiển thị text phụ đề, chú thích, tiêu đề, watermark trên video. "
    "TUYỆT ĐỐI KHÔNG sinh thêm tay, KHÔNG sinh thêm chi, KHÔNG thừa ngón tay, KHÔNG biến dạng bàn tay. "
    "{lang_instruction} xuyên suốt video. Người mẫu phải nói chính xác đoạn thoại sau: \"{dialogue}\"] "
)

SEGMENT_POOL_FALLBACK_EN = [
    # ──── 16s FORMAT: 2 CLIPS (FALLBACK — ảnh ref chỉ có SP) ────
    # 0: CLIP 1 — HOOK + DEMO (0-8s)
    (
        _CONT_FALLBACK_EN +
        "HOOK + DEMO (0-8 seconds): Eye-catching opening with product demonstration. "
        "The presenter suddenly reveals "
        "the product '{name}' (shown in the reference image) from behind her back "
        "with a surprised, excited expression — eyes wide, mouth slightly open in a 'wow' reaction. "
        "FAST dynamic camera zoom-in on the product for a dramatic reveal moment. "
        "Then she smoothly transitions into demonstrating how '{name}' works — "
        "showing it in action with clear hand movements. Her expression shifts to genuine satisfaction "
        "as she uses the product, "
        "{scene}. {lang_instruction} naturally. "
        "The product is clearly visible and IDENTICAL to the reference image throughout. "
        "ENDING POSE (IMPORTANT): The clip MUST END with the woman holding '{name}' "
        "with BOTH HANDS at CHEST LEVEL, facing the camera, smiling — "
        "this exact pose will be the starting point of the next segment. "
        "Dynamic camera movement: zoom-in on reveal, then medium shot. "
        "Punchy cinematic lighting, ultra sharp focus."
    ),
    # 1: CLIP 2 — BENEFIT + CTA (8-16s)
    (
        _CONT_FALLBACK_EN +
        "BENEFIT + CALL TO ACTION (8-16 seconds): Seamless continuation — close-up benefits to final CTA. "
        "CRITICAL: DO NOT start with any greeting or introduction. This is a SEAMLESS CONTINUATION. "
        "STARTING POSE (MUST MATCH): The SAME presenter (SAME face, SAME hair, SAME outfit) "
        "is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL — continuing from where she left off. "
        "She holds the product '{name}' (from reference image) close to camera, "
        "pointing at key features with a genuine impressed expression — nodding approvingly. "
        "Camera slowly zooms into a tight close-up showing product details and quality. "
        "Then she holds '{name}' up prominently next to her face, looking directly into camera "
        "with a confident, persuasive smile. She gives an enthusiastic thumbs-up, "
        "creating an irresistible 'you need this!' energy, "
        "{scene}. {lang_instruction}. "
        "SAME woman, SAME face, SAME outfit as the previous shot. "
        "The product remains EXACTLY as shown in the reference image. "
        "Macro close-up then slow cinematic zoom out. Professional endorsement ending."
    ),
    # ──── 24s FORMAT: 3 CLIPS (FALLBACK — ảnh ref chỉ có SP, HANDOFF POSE) ────
    # Clip 1 kết thúc: cầm SP ngang ngực 2 tay, đang nói
    # Clip 2 bắt đầu: cầm SP ngang ngực 2 tay (tiếp tục)
    # Clip 2 kết thúc: giơ SP lên cạnh mặt 1 tay, tay kia chỉ vào SP
    # Clip 3 bắt đầu: giơ SP cạnh mặt 1 tay (tiếp tục)
    #
    # 2: CLIP 1 — REVIEW (0-8s)
    (
        _CONT_FALLBACK_EN +
        "SEGMENT 1 of 3 (0-8 seconds): Product review opening. "
        "CRITICAL: DO NOT start with greeting, waving, or introduction. Start DIRECTLY with product. "
        "The presenter "
        "is ALREADY holding the product '{name}' (from the reference image) with both hands at chest level "
        "and carefully examining it from multiple angles — turning it over, inspecting build quality, "
        "running her fingers along the surface with a thoughtful, analytical expression. "
        "She looks at the camera and begins sharing her honest first impressions naturally. "
        "ENDING POSE (IMPORTANT): The clip MUST END with the woman holding '{name}' with BOTH HANDS "
        "at CHEST LEVEL, facing the camera, mouth slightly open as if mid-sentence — "
        "this exact pose will be the starting point of the next segment, "
        "{scene}. {lang_instruction} naturally. "
        "The product is clearly visible and IDENTICAL to the reference image. "
        "CAMERA: Steady medium shot (waist-up), gentle subtle orbit. "
        "Warm cinematic lighting, shallow depth of field."
    ),
    # 3: CLIP 2 — DEMO HANDS-ON (8-16s)
    (
        _CONT_FALLBACK_EN +
        "SEGMENT 2 of 3 (8-16 seconds): Hands-on product demo — seamless continuation. "
        "CRITICAL: DO NOT start with greeting or introduction. SEAMLESS CONTINUATION. "
        "STARTING POSE (MUST MATCH): The SAME presenter (SAME face, SAME hair, SAME outfit) "
        "is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL, mid-sentence — "
        "continuing directly from where she left off. "
        "From this pose, she actively DEMONSTRATES '{name}' (from reference image) in action — "
        "flipping it to show all sides, pressing buttons or opening compartments, "
        "running fingers along the surface to show texture, "
        "bringing it very close to camera for detailed macro view. "
        "Her expression shows genuine satisfaction and pleasant surprise at the quality. "
        "Camera pushes in for tight close-ups of product details. "
        "ENDING POSE (IMPORTANT): The clip MUST END with the woman holding '{name}' UP "
        "with ONE HAND near her FACE level, the other hand pointing at the product — "
        "this exact pose will be the starting point of the next segment, "
        "{scene}. {lang_instruction}. "
        "SAME woman, SAME face, SAME outfit, SAME background — no appearance changes. "
        "The product must look EXACTLY like the reference image."
    ),
    # 4: CLIP 3 — TARGET + CTA (16-24s)
    (
        _CONT_FALLBACK_EN +
        "SEGMENT 3 of 3 (16-24 seconds): Final call to action — seamless continuation. "
        "CRITICAL: DO NOT start with greeting or introduction. SEAMLESS CONTINUATION. "
        "STARTING POSE (MUST MATCH): The SAME presenter (SAME face, SAME hair, SAME outfit) "
        "is ALREADY holding '{name}' UP with ONE HAND near her FACE level — "
        "continuing directly from where she left off. "
        "From this pose, she smoothly transitions to speaking directly to camera with warm, relatable tone, "
        "using inclusive hand gestures — pointing toward the viewer, open palm gestures. "
        "Then she holds '{name}' (from reference image) up prominently with both hands, "
        "looking directly into camera with a confident, persuasive smile. "
        "She gives an enthusiastic double thumbs-up, "
        "then gestures invitingly as if saying 'go get yours now!' "
        "with irresistible energy, "
        "{scene}. {lang_instruction}. "
        "SAME woman, SAME face, SAME outfit, SAME background as all previous shots. "
        "Product must be PIXEL-PERFECT copy from reference image. "
        "CAMERA: Medium shot with gentle push-in, then slow zoom out. "
        "Warm, trustworthy final expression. Professional ending."
    ),
]

SEGMENT_POOL_FALLBACK_VI = [
    # ──── 16s FORMAT: 2 CLIPS (FALLBACK — ảnh ref chỉ có SP) ────
    # 0: CLIP 1 — HOOK + DEMO (0-8s)
    (
        _CONT_FALLBACK_VI +
        "HOOK + DEMO (0-8 giây): Mở đầu bắt mắt chuyển sang trình diễn sản phẩm. "
        "Cô gái bất ngờ đưa "
        "sản phẩm '{name}' (được hiển thị trong ảnh tham chiếu) ra từ sau lưng "
        "với biểu cảm ngạc nhiên, phấn khích — mắt mở to, miệng hơi mở kiểu 'wow'. "
        "Camera zoom-in NHANH vào sản phẩm tạo khoảnh khắc reveal ấn tượng. "
        "Sau đó cô chuyển sang trình diễn cách sử dụng '{name}' — "
        "thao tác tự nhiên với cử chỉ tay rõ ràng. Biểu cảm thể hiện sự hài lòng chân thực, "
        "{scene}. {lang_instruction}. "
        "Sản phẩm rõ ràng và GIỐNG HỆT ảnh tham chiếu xuyên suốt. "
        "TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái cầm '{name}' "
        "bằng HAI TAY ở tầm NGANG NGỰC, mặt hướng camera, mỉm cười — "
        "tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo. "
        "Camera động: zoom-in khi reveal, sau đó medium shot. "
        "Ánh sáng điện ảnh sắc nét, lấy nét cực sắc."
    ),
    # 1: CLIP 2 — LỢI ÍCH + CTA (8-16s)
    (
        _CONT_FALLBACK_VI +
        "LỢI ÍCH + KÊU GỌI HÀNH ĐỘNG (8-16 giây): Tiếp nối liền mạch — cận cảnh lợi ích tới CTA. "
        "QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay giới thiệu. Đây là ĐOẠN TIẾP NỐI LIỀN MẠCH. "
        "TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái xinh đẹp (~20 tuổi, CÙNG khuôn mặt, CÙNG trang phục) "
        "ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC — tiếp tục từ chỗ dừng. "
        "Cô giơ sản phẩm '{name}' (từ ảnh tham chiếu) sát camera, "
        "chỉ tay vào các tính năng nổi bật với biểu cảm ấn tượng — gật đầu tán thành. "
        "Camera zoom vào cận cảnh chi tiết và chất lượng sản phẩm. "
        "Sau đó giơ '{name}' lên nổi bật cạnh gương mặt, nhìn thẳng camera "
        "với nụ cười tự tin, thuyết phục. Giơ ngón cái lên nhiệt tình, "
        "tạo năng lượng 'bạn cần sản phẩm này!' không thể cưỡng lại, "
        "{scene}. {lang_instruction}. "
        "CÙNG cô gái, CÙNG khuôn mặt, CÙNG trang phục. "
        "Sản phẩm GIỐNG HỆT ảnh tham chiếu. "
        "Cận cảnh macro rồi zoom ra điện ảnh. Kết thúc chuyên nghiệp."
    ),
    # ──── 24s FORMAT: 3 CLIPS (FALLBACK — HANDOFF POSE) ────
    # 2: CLIP 1 — ĐÁNH GIÁ (0-8s)
    (
        _CONT_FALLBACK_VI +
        "ĐOẠN 1 trên 3 (0-8 giây): Mở đầu đánh giá sản phẩm. "
        "QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào, vẫy tay, hay giới thiệu. Bắt đầu TRỰC TIẾP với sản phẩm. "
        "Cô gái ĐANG cầm '{name}' "
        "(sản phẩm từ ảnh tham chiếu) bằng HAI TAY ở tầm NGANG NGỰC "
        "và quan sát kỹ lưỡng từ nhiều góc — xoay qua xoay lại, kiểm tra chất lượng, "
        "lướt ngón tay trên bề mặt với biểu cảm suy nghĩ, phân tích. "
        "Nhìn camera và bắt đầu chia sẻ cảm nhận với cử chỉ nói chuyện tự nhiên. "
        "TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái cầm '{name}' bằng HAI TAY "
        "ở tầm NGANG NGỰC, mặt hướng camera, miệng hơi mở như đang nói dở — "
        "tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo, "
        "{scene}. {lang_instruction}. "
        "Sản phẩm rõ ràng và GIỐNG HỆT ảnh tham chiếu. "
        "CAMERA: Medium shot ổn định, xoay nhẹ tinh tế. "
        "Ánh sáng điện ảnh ấm, độ sâu trường ảnh nông."
    ),
    # 3: CLIP 2 — DEMO THỰC TẾ (8-16s)
    (
        _CONT_FALLBACK_VI +
        "ĐOẠN 2 trên 3 (8-16 giây): Trình diễn sản phẩm — tiếp nối liền mạch. "
        "QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay giới thiệu. ĐOẠN TIẾP NỐI LIỀN MẠCH. "
        "TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái xinh đẹp (~20 tuổi, CÙNG khuôn mặt, CÙNG trang phục) "
        "ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, đang nói dở — tiếp tục từ chỗ dừng. "
        "Từ tư thế này, cô chủ động TRÌNH DIỄN '{name}' (từ ảnh tham chiếu) — "
        "lật qua lật lại xem mọi mặt, nhấn nút hoặc mở ngăn, "
        "lướt ngón tay cảm nhận chất liệu, đưa sản phẩm rất gần camera xem chi tiết macro. "
        "Biểu cảm hài lòng chân thực và ngạc nhiên thú vị về chất lượng. "
        "Camera push-in cho cận cảnh chi tiết bề mặt, chất liệu. "
        "TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái giơ '{name}' LÊN CAO "
        "bằng MỘT TAY gần tầm MẶT, tay kia đang chỉ vào sản phẩm — "
        "tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo, "
        "{scene}. {lang_instruction}. "
        "CÙNG cô gái, CÙNG khuôn mặt, CÙNG trang phục, CÙNG phông nền. "
        "Sản phẩm GIỐNG HỆT ảnh tham chiếu."
    ),
    # 4: CLIP 3 — ĐỐI TƯỢNG + CTA (16-24s)
    (
        _CONT_FALLBACK_VI +
        "ĐOẠN 3 trên 3 (16-24 giây): Kêu gọi hành động — tiếp nối liền mạch. "
        "QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay giới thiệu. ĐOẠN TIẾP NỐI LIỀN MẠCH. "
        "TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái xinh đẹp (~20 tuổi, CÙNG khuôn mặt, CÙNG trang phục) "
        "ĐANG giơ '{name}' LÊN CAO bằng MỘT TAY gần tầm MẶT — tiếp tục từ chỗ dừng. "
        "Từ tư thế này, cô chuyển sang nói trực tiếp vào camera với giọng ấm áp, gần gũi, "
        "dùng cử chỉ tay bao quát — chỉ về phía người xem, cử chỉ lòng bàn tay mở. "
        "Sau đó giơ '{name}' (từ ảnh tham chiếu) lên nổi bật bằng cả hai tay, nhìn thẳng camera "
        "với nụ cười tự tin, thuyết phục. Giơ hai ngón cái lên nhiệt tình, "
        "rồi ra hiệu mời gọi như nói 'mua ngay đi!' với năng lượng không thể cưỡng lại, "
        "{scene}. {lang_instruction}. "
        "CÙNG cô gái, CÙNG khuôn mặt, CÙNG trang phục, CÙNG phông nền. "
        "Sản phẩm GIỐNG HỆT ảnh tham chiếu. "
        "CAMERA: Medium shot với push-in nhẹ, rồi zoom ra điện ảnh. "
        "Biểu cảm ấm áp, đáng tin cậy. Kết thúc chuyên nghiệp."
    ),
]


def build_video_prompts_fallback(product_name, scene_en, duration_sec=16, lang="en", review_style="Review tự nhiên"):
    """Sinh list prompt FALLBACK khi hết quota tạo ảnh.
    Ảnh reference chỉ có sản phẩm → prompt MÔ TẢ MC bằng text.
    Vẫn dùng I2V với ảnh SP làm reference.
    Handoff pose liền mạch giữa các đoạn.
    Kiểu tóc + trang phục random mỗi SP → video luôn mới mẻ.
    """
    pool = SEGMENT_POOL_FALLBACK_VI if lang == "vi" else SEGMENT_POOL_FALLBACK_EN
    indices = DURATION_MAP.get(duration_sec, DURATION_MAP[16])
    lang_info = _LANG_MAP.get(lang, _LANG_MAP["en"])
    hair_pool = _HAIR_POOL_VI if lang == "vi" else _HAIR_POOL_EN
    outfit_pool = _OUTFIT_POOL_VI if lang == "vi" else _OUTFIT_POOL_EN
    hair = random.choice(hair_pool)
    outfit = random.choice(outfit_pool)
    n_segments = len(indices)
    
    prompts = []
    for i, idx in enumerate(indices):
        dialogue = generate_tts_script(product_name, i, n_segments, lang=lang)
        prompt = pool[idx].format(
            name=product_name,
            scene=scene_en,
            lang_instruction=lang_info["instruction"],
            country_en=lang_info["country_en"],
            country_vi=lang_info["country_vi"],
            hair=hair,
            outfit=outfit,
            dialogue=dialogue
        )
        if review_style == "Ngồi Review":
            if lang == "vi":
                sitting_constraint = "[ĐIỀU CHỈNH BỐ CỤC: Người dẫn/reviewer ngồi lịch sự phía sau một chiếc bàn gỗ tối giản trong suốt video. Mọi hành động diễn ra tại bàn này. Không đứng hoặc đi lại. Luôn giữ tư thế ngồi sau bàn. Sản phẩm được đặt trên bàn hoặc được cầm trên tay phía trên mặt bàn.]\n\n"
            else:
                sitting_constraint = "[LAYOUT CONSTRAINT: The presenter is sitting politely behind a clean, minimalist wooden desk throughout the video. All actions are performed while seated at this desk. Do not show the presenter standing or walking. Keep her seated behind the desk. The product is either placed on the desk or held above it.]\n\n"
            prompt = sitting_constraint + prompt
        prompts.append(prompt)
    return prompts


# ==================== FFMPEG CONCAT ====================

def concat_videos(clip_paths, output_path, log=None):
    """Ghép nhiều video clip thành 1 video hoàn chỉnh bằng FFmpeg.
    Thử copy trước (nhanh), nếu lỗi → re-encode fallback.
    """
    def _log(m):
        if log: log(m)

    if not clip_paths:
        _log("❌ Không có clip nào để ghép!")
        return False

    if len(clip_paths) == 1:
        # Chỉ 1 clip → copy ra output
        import shutil
        shutil.copy2(clip_paths[0], output_path)
        return True

    # Tạo file list cho concat demuxer
    list_file = os.path.join(tempfile.gettempdir(), f"concat_{int(time.time())}_{random.randint(100,999)}.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in clip_paths:
                # FFmpeg cần forward slash hoặc escaped backslash
                f.write(f"file '{p.replace(os.sep, '/')}'\n")

        # Thử 1: stream copy (nhanh, cùng codec)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ]
        _log(f"🔧 FFmpeg concat {len(clip_paths)} clip...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

        if result.returncode != 0:
            # Thử 2: re-encode (chậm hơn, an toàn hơn)
            _log("⚠️ Copy stream lỗi, chuyển sang re-encode...")
            cmd_reencode = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-threads", "2",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path
            ]
            result = subprocess.run(cmd_reencode, capture_output=True, text=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

        if result.returncode == 0:
            _log(f"✅ Ghép video xong: {os.path.basename(output_path)}")
            return True
        else:
            _log(f"❌ FFmpeg lỗi: {result.stderr[-200:]}")
            return False

    except subprocess.TimeoutExpired:
        _log("❌ FFmpeg timeout!")
        return False
    except Exception as e:
        _log(f"❌ FFmpeg exception: {e}")
        return False
    finally:
        try:
            if os.path.exists(list_file):
                os.remove(list_file)
        except Exception:
            pass


# ==================== XÓA WATERMARK VEO ====================

def remove_veo_watermark(input_path, log=None):
    """Xóa watermark Veo ở góc dưới bên phải video bằng FFmpeg delogo filter.
    Ghi đè file gốc (ghi tạm → replace).
    Trả True nếu thành công.
    """
    def _log(m):
        if log: log(m)

    if not os.path.isfile(input_path):
        return False

    # Lấy kích thước video bằng ffprobe
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", input_path],
            capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
        parts = probe.stdout.strip().split(",")
        w, h = int(parts[0]), int(parts[1])
    except Exception:
        w, h = 720, 1280  # fallback portrait 9:16

    # Veo watermark: góc dưới phải
    # Kích thước logo ~12% width × 5% height, cách mép ~1.5%
    lw = max(int(w * 0.12), 70)
    lh = max(int(h * 0.05), 28)
    lx = w - lw - max(int(w * 0.015), 8)
    ly = h - lh - max(int(h * 0.015), 8)

    tmp_out = input_path + ".nowm.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"delogo=x={lx}:y={ly}:w={lw}:h={lh}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-threads", "2",
        "-c:a", "copy",
        "-movflags", "+faststart",
        tmp_out
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        if result.returncode == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 1000:
            os.replace(tmp_out, input_path)
            _log(f"🧹 Đã xóa watermark Veo: {os.path.basename(input_path)}")
            return True
        else:
            _log(f"⚠️ Xóa watermark lỗi: {result.stderr[-150:] if result.stderr else 'unknown'}")
            # Dọn file tạm nếu lỗi
            try: os.remove(tmp_out)
            except Exception: pass
            return False
    except subprocess.TimeoutExpired:
        _log("⚠️ Xóa watermark timeout")
        try: os.remove(tmp_out)
        except Exception: pass
        return False
    except Exception as e:
        _log(f"⚠️ Xóa watermark exception: {e}")
        try: os.remove(tmp_out)
        except Exception: pass
        return False


# ==================== UTILS ====================

_MODEL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def pick_random_model(model_folder):
    """Chọn ngẫu nhiên 1 ảnh người mẫu từ thư mục.
    Trả full-path hoặc None nếu thư mục trống / không hợp lệ.
    """
    if not model_folder or not os.path.isdir(model_folder):
        return None
    imgs = [os.path.join(model_folder, f) for f in os.listdir(model_folder)
            if os.path.splitext(f)[1].lower() in _MODEL_EXTS]
    return random.choice(imgs) if imgs else None


def list_model_images(model_folder):
    """Liệt kê tất cả ảnh người mẫu trong thư mục. Trả list full-path."""
    if not model_folder or not os.path.isdir(model_folder):
        return []
    return sorted([os.path.join(model_folder, f) for f in os.listdir(model_folder)
                   if os.path.splitext(f)[1].lower() in _MODEL_EXTS])


def parse_duration(duration_str):
    """Parse '16s' → 16, '24s' → 24. Mặc định 16."""
    try:
        return int(duration_str.replace("s", "").strip())
    except Exception:
        return 16


def clean_filename(s):
    """Tạo tên file an toàn từ string."""
    return re.sub(r'[^\w\s\-]', '', s).strip().replace(' ', '_')[:60]
