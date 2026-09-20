    def _build_shopee(self):
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["shopee"] = f
        # Header
        hdr = ctk.CTkFrame(f, fg_color="#EE4D2D", corner_radius=12); hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🛒 Tạo Video Shopee v3", font=("", 18, "bold"), text_color="#fff").pack(side="left", padx=20, pady=14)
        self._shopee_status = ctk.CTkLabel(hdr, text="Sẵn sàng", font=("", 12), text_color="#FFD3C7")
        self._shopee_status.pack(side="right", padx=20)

        # --- Cài đặt ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); cfg.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(cfg, text="⚙ Cài đặt", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))

        # Row 1: Tỉ lệ + Khung cảnh + Độ dài
        row1 = ctk.CTkFrame(cfg, fg_color="transparent"); row1.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._sp_aspect = ctk.CTkOptionMenu(row1, values=list(E.VID_ASPECTS.keys()), width=150)
        self._sp_aspect.pack(side="left", padx=(4, 12))
        self._sp_aspect.set(self.settings.get("shopee_aspect", "Dọc 9:16 (TikTok)"))

        scene_opts = SV.SCENE_OPTIONS if SV else ["🎲 Random", "📦 Tổng kho hàng hóa"]
        ctk.CTkLabel(row1, text="Khung cảnh:", font=("", 12)).pack(side="left")
        self._sp_scene = ctk.CTkOptionMenu(row1, values=scene_opts, width=200)
        self._sp_scene.pack(side="left", padx=(4, 12))
        self._sp_scene.set(self.settings.get("shopee_scene", "🎲 Random"))

        dur_opts = ["8s"] + (SV.DURATION_OPTIONS if SV else ["16s", "24s"])
        ctk.CTkLabel(row1, text="Độ dài:", font=("", 12)).pack(side="left")
        self._sp_duration = ctk.CTkOptionMenu(row1, values=dur_opts, width=80,
                                               command=lambda v: self._sp_on_duration_change())
        self._sp_duration.pack(side="left", padx=(4, 12))
        self._sp_duration.set(self.settings.get("shopee_duration", "16s"))

        lang_opts = SV.LANG_OPTIONS if SV else ["Tiếng Anh", "Tiếng Việt"]
        ctk.CTkLabel(row1, text="Ngôn ngữ:", font=("", 12)).pack(side="left")
        self._sp_lang = ctk.CTkOptionMenu(row1, values=lang_opts, width=110)
        self._sp_lang.pack(side="left", padx=(4, 0))
        self._sp_lang.set(self.settings.get("shopee_lang", "Tiếng Việt"))

        # Row 1b: Model
        row1b_sp = ctk.CTkFrame(cfg, fg_color="transparent"); row1b_sp.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row1b_sp, text="🤖 Model:", font=("", 12)).pack(side="left")
        self._sp_model = ctk.CTkOptionMenu(row1b_sp, values=list(E.VID_MODELS.keys()), width=220,
                                            command=lambda v: self._sp_on_model_change())
        self._sp_model.pack(side="left", padx=(4, 12))
        self._sp_model.set(self.settings.get("shopee_model", "Veo 3.1 (miễn phí)"))

        self._sp_remove_wm = ctk.BooleanVar(value=self.settings.get("shopee_remove_wm", True))
        ctk.CTkCheckBox(row1b_sp, text="🧹 Xóa logo", variable=self._sp_remove_wm,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        self._sp_skip_img = ctk.BooleanVar(value=self.settings.get("shopee_skip_img", False))
        ctk.CTkCheckBox(row1b_sp, text="⏭ Bỏ qua SP đã có ảnh", variable=self._sp_skip_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        # Row 1c: Chế độ tạo video (API / Extension)
        row_mode_sp = ctk.CTkFrame(cfg, fg_color="transparent"); row_mode_sp.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row_mode_sp, text="Chế độ:", font=("", 12)).pack(side="left", padx=(0, 2))
        self._sp_gen_mode = ctk.StringVar(value=self.settings.get("sp_gen_mode", "API"))
        self._sp_gen_mode_seg = ctk.CTkSegmentedButton(row_mode_sp, values=["API", "Extension"],
                                                       variable=self._sp_gen_mode, font=("", 11),
                                                       command=self._on_sp_gen_mode_change)
        self._sp_gen_mode_seg.pack(side="left", padx=(2, 10))
        self._sp_gen_mode_lbl = ctk.CTkLabel(row_mode_sp, text="", font=("", 10), text_color=T2)
        self._sp_gen_mode_lbl.pack(side="left")
        self._on_sp_gen_mode_change(self._sp_gen_mode.get())

        # Row 1.5: Review Style Config
        row1_5 = ctk.CTkFrame(cfg, fg_color="transparent"); row1_5.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(row1_5, text="Kiểu Review:", font=("", 12)).pack(side="left")
        self._sp_review_style = ctk.StringVar(value=self.settings.get("shopee_review_style", "🎲 Random"))
        style_opts = ["🎲 Random", "Review tự nhiên", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "Unboxing", "UGC Authentic", "Demo Công Dụng", "So Sánh/Đánh Giá"]
        self._sp_style_menu = ctk.CTkOptionMenu(row1_5, values=style_opts, variable=self._sp_review_style, width=200)
        self._sp_style_menu.pack(side="left", padx=(4, 12))

        # AI Prompt
        ctk.CTkLabel(row1_5, text="AI Prompt:", font=("", 12)).pack(side="left")
        self._sp_ai_prompt = ctk.CTkOptionMenu(
            row1_5,
            values=["Gemini", "Groq", "Prompt A + B"],
            width=150
        )
        self._sp_ai_prompt.pack(side="left", padx=(4, 6))
        saved_sp_ai = self.settings.get("shopee_ai_prompt", "Prompt A + B")
        if saved_sp_ai == "Template (mặc định)": saved_sp_ai = "Prompt A + B"
        self._sp_ai_prompt.set(saved_sp_ai)

        ctk.CTkButton(
            row1_5,
            text="🧪 Test prompt",
            command=self._sp_test_prompt,
            fg_color="#5C6BC0",
            hover_color="#3949AB",
            height=28,
            width=100,
            font=("", 11)
        ).pack(side="left", padx=(0, 12))

        self._sp_use_laundering = ctk.BooleanVar(value=self.settings.get("shopee_use_laundering", False))
        self._sp_chk_laundering = ctk.CTkCheckBox(row1_5, text="Rửa ảnh (Bypass 429)", variable=self._sp_use_laundering, font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_laundering.pack(side="left", padx=(4, 12))

        self._sp_del_img = ctk.BooleanVar(value=self.settings.get("shopee_del_img", True))
        ctk.CTkCheckBox(row1_5, text="🗑 Xóa ảnh khi tạo xong", variable=self._sp_del_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 12))

        self._sp_ghep_anh = ctk.BooleanVar(value=self.settings.get("shopee_ghep_anh", False))
        self._sp_chk_ghep_anh = ctk.CTkCheckBox(row1_5, text="🎞 Ghép ảnh (12s)", variable=self._sp_ghep_anh,
                                                 font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_ghep_anh.pack(side="left", padx=(0, 12))

        # Khởi tạo trạng thái model + duration
        self._sp_on_model_change()

        # Row 2: Thư mục người mẫu & Thư mục lưu
        row2 = ctk.CTkFrame(cfg, fg_color="transparent"); row2.pack(fill="x", padx=12, pady=(4, 10))
        
        # --- Phần Người mẫu ---
        ctk.CTkLabel(row2, text="👤 Người mẫu:", font=("", 12)).pack(side="left")
        self._sp_model_dir = ctk.CTkEntry(row2)
        self._sp_model_dir.pack(side="left", padx=6, fill="x", expand=True)
        if self.settings.get("shopee_model_dir"):
            self._sp_model_dir.insert(0, self.settings["shopee_model_dir"])
        self._sp_model_count = ctk.CTkLabel(row2, text="", font=("", 10), text_color=T2)
        self._sp_model_count.pack(side="left", padx=(0, 4))
        ctk.CTkButton(row2, text="Chọn", width=56, command=self._sp_pick_model,
                      fg_color="#EE4D2D", hover_color="#D73211").pack(side="left", padx=(0, 8))

        self._sp_no_model = ctk.BooleanVar(value=self.settings.get("shopee_no_model", False))
        self._sp_no_model_chk = ctk.CTkCheckBox(row2, text="Không mẫu", variable=self._sp_no_model,
                                                font=("", 11), checkbox_width=18, checkbox_height=18,
                                                command=self._sp_toggle_no_model)
        self._sp_no_model_chk.pack(side="left", padx=(0, 16))

        # --- Phần Lưu video ---
        ctk.CTkLabel(row2, text="📁 Lưu video:", font=("", 12)).pack(side="left")
        self._sp_outdir = ctk.CTkEntry(row2)
        self._sp_outdir.pack(side="left", padx=6, fill="x", expand=True)
        if self.settings.get("shopee_out_dir"):
            self._sp_outdir.insert(0, self.settings["shopee_out_dir"])
        ctk.CTkButton(row2, text="Chọn", width=56, command=lambda: self._pick(self._sp_outdir),
                      fg_color="#EE4D2D", hover_color="#D73211").pack(side="left", padx=(0, 4))

        # --- Bottom Container (để các nút ở dưới không bị lấp khi cửa sổ nhỏ) ---
        bottom_container = ctk.CTkFrame(f, fg_color="transparent")
        bottom_container.pack(side="bottom", fill="x")

        # --- Middle Container (2 hàng) ---
        middle_split = ctk.CTkFrame(f, fg_color="transparent")
        middle_split.pack(fill="both", expand=True, pady=(10, 0))

        # --- Hàng trên: Nhập sản phẩm (Tên | Đường dẫn ảnh) ---
        prod_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        prod_card.pack(fill="both", expand=True, pady=(0, 5))
        lbl_row = ctk.CTkFrame(prod_card, fg_color="transparent"); lbl_row.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(lbl_row, text="📦 Danh sách sản phẩm (mỗi dòng: ảnh.jpg | Tên SP):",
                     font=("", 13, "bold"), text_color=T1).pack(side="left")
        self._sp_prod_count = ctk.CTkLabel(lbl_row, text="0 SP", font=("", 11), text_color=T2)
        self._sp_prod_count.pack(side="right")

        # Textbox nhập liệu sản phẩm
        self._sp_products = ctk.CTkTextbox(prod_card, font=("Consolas", 11))
        self._sp_products.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        # Cấu hình màu sắc cho từng trạng thái dòng
        self._sp_products.tag_config("status_success", foreground="#1B7D2C")  # xanh lá
        self._sp_products.tag_config("status_error", foreground="#D32F2F")    # đỏ
        self._sp_products.tag_config("status_running", foreground="#E65100")  # cam
        saved_products = self.settings.get("shopee_products", "")
        if saved_products:
            self._sp_products.insert("1.0", saved_products)
            # Khôi phục màu sắc cho các dòng đã có trạng thái
            self._sp_restore_line_colors()
        self._sp_count_debounce_id = None
        def _sp_debounced_count(event=None):
            if self._sp_count_debounce_id:
                self.after_cancel(self._sp_count_debounce_id)
            self._sp_count_debounce_id = self.after(500, self._sp_update_count)
        self._sp_products.bind("<KeyRelease>", _sp_debounced_count)

        # Nút import + xem trước
        btn_import_row = ctk.CTkFrame(prod_card, fg_color="transparent"); btn_import_row.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(btn_import_row, text="📂 Import thư mục ảnh", width=160,
                      command=self._sp_import_folder,
                      fg_color="#5C6BC0", hover_color="#3949AB").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="📄 Import tên SP (TXT)", width=160,
                      command=self._sp_import_names_txt,
                      fg_color="#43A047", hover_color="#2E7D32").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="🗑 Xóa hết", width=80,
                      command=self._sp_clear_all,
                      fg_color="#E53935", hover_color="#B71C1C").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="🔄 Xóa trạng thái", width=120,
                      command=self._sp_clear_status,
                      fg_color="#7B1FA2", hover_color="#4A148C").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="✅ Xóa thành công", width=120,
                      command=self._sp_clear_success,
                      fg_color="#00897B", hover_color="#00695C").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(btn_import_row, text="① Ảnh → ② TXT",
                     font=("", 10), text_color=T2).pack(side="left", padx=4)

        # --- Log & Progress ---
        bottom = ctk.CTkFrame(bottom_container, fg_color="transparent"); bottom.pack(fill="x", pady=(8, 0))
        self._sp_progress = ctk.CTkProgressBar(bottom, height=8, progress_color="#EE4D2D")
        self._sp_progress.pack(fill="x", pady=(0, 4))
        self._sp_progress.set(0)

        # --- Hàng dưới: Pool Status Panel (AIMD) ---
        pool_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        pool_card.pack(fill="both", expand=True, pady=(5, 0))
        pool_hdr = ctk.CTkFrame(pool_card, fg_color="transparent"); pool_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(pool_hdr, text="🚀 Pool tài khoản (AIMD)", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sp_pool_eta_lbl = ctk.CTkLabel(pool_hdr, text="", font=("", 11), text_color=AC)
        self._sp_pool_eta_lbl.pack(side="right")
        # 4 stat boxes
        stat_row = ctk.CTkFrame(pool_card, fg_color="transparent"); stat_row.pack(fill="x", padx=12, pady=2)
        self._sp_pool_stat = {}
        for key, icon, color in [("acc", "👥 Tổng", T1), ("run", "🟢 Chạy", GR), ("gen", "⚡ Tạo", AC), ("rest", "😴 Nghỉ", "#F9A825")]:
            box = ctk.CTkFrame(stat_row, fg_color="transparent"); box.pack(side="left", padx=(0, 16))
            ctk.CTkLabel(box, text=icon, font=("", 10), text_color=T2).pack(side="left")
            lbl = ctk.CTkLabel(box, text="0", font=("", 11, "bold"), text_color=color); lbl.pack(side="left", padx=(4, 0))
            self._sp_pool_stat[key] = lbl
        # Account rows container
        self._sp_pool_rows_frame = ctk.CTkScrollableFrame(pool_card, fg_color=CARD, height=80)
        self._sp_pool_rows_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._sp_pool_rows = {}
        self._sp_pool_row_sig = ()
        self._sp_pool_states = None  # set during run

        self._sp_log = ctk.CTkTextbox(bottom_container, height=120, font=("Consolas", 10), state="disabled")
        self._sp_log.pack(fill="x", pady=(4, 0))

        # --- Bảng kết quả (hiện sau khi xử lý) ---
        self._sp_result_card = ctk.CTkFrame(bottom_container, fg_color=CARD, corner_radius=10)
        result_hdr = ctk.CTkFrame(self._sp_result_card, fg_color="transparent")
        result_hdr.pack(fill="x", padx=12, pady=(8, 2))
        self._sp_result_title = ctk.CTkLabel(result_hdr, text="📊 Kết quả xử lý",
                                              font=("", 13, "bold"), text_color=T1)
        self._sp_result_title.pack(side="left")
        self._sp_result_summary = ctk.CTkLabel(result_hdr, text="", font=("", 11), text_color=T2)
        self._sp_result_summary.pack(side="right")
        self._sp_result_scroll = ctk.CTkScrollableFrame(self._sp_result_card, fg_color=CARD, height=100)
        self._sp_result_scroll.pack(fill="x", padx=8, pady=(0, 8))

        # --- Nút bấm ---
        self._sp_btn_row = ctk.CTkFrame(bottom_container, fg_color="transparent"); self._sp_btn_row.pack(fill="x", pady=(8, 0))
        self._sp_btn_start = ctk.CTkButton(self._sp_btn_row, text="▶  Bắt đầu tạo video",
                                           command=self._shopee_start, fg_color="#EE4D2D",
                                           hover_color="#D73211", height=42,
                                           font=("", 15, "bold"))
        self._sp_btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._sp_btn_stop = ctk.CTkButton(self._sp_btn_row, text="⏹ Dừng", command=self._shopee_stop,
                                          fg_color="#9aa0a6", hover_color="#5f6368",
                                          height=42, width=100, state="disabled")
        self._sp_btn_stop.pack(side="left", padx=(0, 4))
        self._sp_btn_open = ctk.CTkButton(self._sp_btn_row, text="📂 Mở thư mục",
                                          command=self._shopee_open_folder,
                                          fg_color="#5C6BC0", hover_color="#3949AB",
                                          height=42, width=120)
        self._sp_btn_open.pack(side="left")

        self._shopee_running = False
        self._shopee_stop_flag = False
        self._shopee_results = []
        self._sp_img_folder = self.settings.get("shopee_img_folder", "")  # thư mục ảnh SP
        # Xóa trắng shopee.txt mỗi lần khởi động
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shopee.txt"), "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

        self._sp_toggle_no_model()

    def _sp_pick_model(self):
        """Chọn thư mục chứa ảnh người mẫu."""
        from tkinter import filedialog as fd
        p = fd.askdirectory(title="Chọn thư mục chứa ảnh người mẫu")
        if p:
            self._sp_model_dir.delete(0, "end")
            self._sp_model_dir.insert(0, p)
            # Đếm số ảnh trong thư mục
            n = len(SV.list_model_images(p)) if SV else 0
            self._sp_model_count.configure(text=f"({n} ảnh)")
            self._sp_log_msg(f"👤 Thư mục người mẫu: {p} ({n} ảnh)")

    def _sp_toggle_no_model(self):
        """Bật/tắt trạng thái nhập thư mục người mẫu dựa trên nút checkbox."""
        st = "disabled" if self._sp_no_model.get() else "normal"
        self._sp_model_dir.configure(state=st)
        if self._sp_no_model.get():
            self._sp_model_count.configure(text="(Không chọn)")
        else:
            p = self._sp_model_dir.get().strip()
            if p and os.path.isdir(p):
                n = len(SV.list_model_images(p)) if SV else 0
                self._sp_model_count.configure(text=f"({n} ảnh)")
            else:
                self._sp_model_count.configure(text="")

    _SP_STATUS_PREFIXES = ("✅ ", "❌ ", "⏳ ")

