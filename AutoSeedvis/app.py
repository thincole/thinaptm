import os, sys, json, time, threading, urllib.request, urllib.error, uuid, traceback, base64, random, shutil
import io
if sys.stdout is None: sys.stdout = io.StringIO()
if sys.stderr is None: sys.stderr = io.StringIO()
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

import engine as E
import shopeevideo as SV
import shopee_ai
import shopee_scraper
import watermark_remover
import prompt_templates
import recaptcha_farm as RF

ctk.set_appearance_mode("Dark")
BG = "#1e1e1e"
CARD = "#2b2b2b"
T1 = "#ffffff"
T2 = "#a0a0a0"
AC = "#1a73e8"
AC2 = "#1557b0"
GR = "#00897B"
RD = "#EA4335"
SEEDVIS_UA = "AutoSeedvis/1.0"

if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, '_MEIPASS', APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

# Tự động nạp thư mục ứng dụng vào PATH để Windows subprocess tìm thấy ffmpeg.exe cạnh autoseedvis.exe
if APP_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = APP_DIR + os.pathsep + r"C:\ffmpeg\bin" + os.pathsep + os.environ.get("PATH", "")

class AutoSeedvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Auto Seedvis - Standalone Shopee Video")
        self.geometry("1000x700")
        for ico in [os.path.join(APP_DIR, "logo.ico"), os.path.join(BUNDLE_DIR, "logo.ico"), "logo.ico"]:
            if os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                    break
                except Exception:
                    pass
        self.settings_file = os.path.join(APP_DIR, "settings.json")
        self._load_settings()
        self._log_file_path = os.path.join(APP_DIR, "log.txt")
        try:
            with open(self._log_file_path, "w", encoding="utf-8") as lf:
                lf.write(f"=== AutoSeedvis Log Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            pass
        self._shopee_running = False
        self._shopee_stop_flag = False
        self._sp_prompt_txt_path = self.settings.get("shopee_prompt_txt_path", "")
        
        self.frames = {}
        self._build_shopee()
        self._start_temp_cleaner_thread()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _load_settings(self):
        self.settings = {}
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except:
                pass
                
    def _save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print("Save settings error:", e)

    def _on_closing(self):
        self.withdraw()
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            def create_image():
                try:
                    for ico_cand in [os.path.join(BUNDLE_DIR, "logo.ico"), os.path.join(APP_DIR, "logo.ico"), "logo.ico"]:
                        if os.path.exists(ico_cand):
                            return Image.open(ico_cand).resize((64, 64))
                    return Image.open("logo.ico").resize((64, 64))
                except:
                    image = Image.new('RGB', (64, 64), color=(26, 115, 232))
                    draw = ImageDraw.Draw(image)
                    draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
                    return image

            def on_show(icon, item):
                icon.stop()
                self.after(0, self.deiconify)
                
            def on_quit(icon, item):
                icon.stop()
                def _do_quit():
                    self._shopee_stop_flag = True
                    try:
                        self._save_settings_from_ui()
                    except Exception as e:
                        print("Save settings error:", e)
                    try:
                        import shutil, os
                        temp_dir = os.path.join(APP_DIR, "temp_render")
                        if os.path.exists(temp_dir):
                            for item in os.listdir(temp_dir):
                                ipath = os.path.join(temp_dir, item)
                                if os.path.isfile(ipath): os.remove(ipath)
                                elif os.path.isdir(ipath): shutil.rmtree(ipath)
                    except Exception:
                        pass
                    self.destroy()
                self.after(0, _do_quit)
                
            menu = pystray.Menu(
                pystray.MenuItem('Hiển thị cửa sổ', on_show, default=True),
                pystray.MenuItem('Thoát hoàn toàn', on_quit)
            )
            
            icon = pystray.Icon("AutoSeedvis", create_image(), "Auto Seedvis - Shopee", menu)
            import threading
            threading.Thread(target=icon.run, daemon=True).start()
        except ImportError:
            self._shopee_stop_flag = True
            self._save_settings_from_ui()
            self.destroy()
        
    def _save_settings_from_ui(self):
        self.settings["seedvis_api_key"] = self._seed_apikey.get().strip()
        try:
            self.settings["seedvis_threads"] = int(self._seed_threads.get().strip())
        except:
            pass
        self.settings["gemini_keys"] = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
        self.settings["groq_keys"] = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]
        self.settings["shopee_aspect"] = self._sp_aspect.get()
        self.settings["shopee_scene"] = self._sp_scene.get()
        self.settings["shopee_duration"] = self._sp_duration.get()
        self.settings["shopee_lang"] = self._sp_lang.get()
        self.settings["shopee_model"] = self._sp_model.get()
        self.settings["shopee_remove_wm"] = self._sp_remove_wm.get()
        self.settings["shopee_skip_img"] = self._sp_skip_img.get()
        self.settings["shopee_review_style"] = self._sp_review_style.get()
        self.settings["shopee_ai_prompt"] = self._sp_ai_prompt.get()
        self.settings["shopee_use_laundering"] = self._sp_use_laundering.get()
        self.settings["shopee_del_img"] = self._sp_del_img.get()
        self.settings["shopee_ghep_anh"] = self._sp_ghep_anh.get()
        self.settings["shopee_auto_clean_temp"] = self._sp_auto_clean_temp.get()
        self.settings["shopee_temp_cleanup_min"] = self._sp_temp_cleanup_min.get().strip()
        self.settings["shopee_naming"] = self._sp_naming.get()
        self.settings["shopee_model_dir"] = self._sp_model_dir.get().strip()
        self.settings["shopee_no_model"] = self._sp_no_model.get()
        self.settings["shopee_out_dir"] = self._sp_outdir.get().strip()
        self.settings["shopee_prompt_txt_path"] = getattr(self, "_sp_prompt_txt_path", "")
        if hasattr(self, "txt_custom_prompts"):
            self.settings["custom_prompts"] = [l.strip() for l in self.txt_custom_prompts.get("1.0", "end").splitlines() if l.strip()]
        self.settings["shopee_products"] = self._sp_products.get("1.0", "end")
        self._save_settings()

    def _build_shopee(self):
        f = ctk.CTkFrame(self, fg_color=BG)
        f.pack(fill="both", expand=True)
        # Header
        hdr = ctk.CTkFrame(f, fg_color="#EE4D2D", corner_radius=12); hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🚀 Auto Seedvis - Tạo video Shopee", font=("", 18, "bold"), text_color="#fff").pack(side="left", padx=20, pady=14)
        self._shopee_status = ctk.CTkLabel(hdr, text="Sẵn sàng", font=("", 12), text_color="#FFD3C7")
        self._shopee_status.pack(side="right", padx=20)

        # --- Cài đặt ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); cfg.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(cfg, text="⚙ Cài đặt", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))

        
        # --- API Settings ---
        api_frame = ctk.CTkFrame(cfg, fg_color="transparent")
        api_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(api_frame, text="🔑 Seedvis API Key:", font=("", 12)).pack(side="left")
        self._seed_apikey = ctk.CTkEntry(api_frame, width=350, font=("", 11), show="*")
        self._seed_apikey.pack(side="left", padx=10)
        self._seed_apikey.insert(0, self.settings.get("seedvis_api_key", ""))
        
        ctk.CTkLabel(api_frame, text="Luồng (Threads):", font=("", 12)).pack(side="left", padx=(10, 0))
        self._seed_threads = ctk.CTkEntry(api_frame, width=50, font=("", 11))
        self._seed_threads.pack(side="left", padx=10)
        self._seed_threads.insert(0, str(self.settings.get("seedvis_threads", 3)))

        
        # --- AI Keys & Custom Prompts Settings ---
        ai_keys_frame = ctk.CTkFrame(cfg, fg_color="transparent")
        ai_keys_frame.pack(fill="x", padx=12, pady=4)
        
        ctk.CTkLabel(ai_keys_frame, text="Gemini API Keys:", font=("", 12)).pack(side="left", anchor="nw")
        self.txt_gemini = ctk.CTkTextbox(ai_keys_frame, height=60, width=170, font=("Consolas", 11))
        self.txt_gemini.pack(side="left", padx=(4, 10), fill="y")
        if self.settings.get("gemini_keys"):
            self.txt_gemini.insert("1.0", "\n".join(self.settings["gemini_keys"]))
            
        ctk.CTkLabel(ai_keys_frame, text="Groq API Keys:", font=("", 12)).pack(side="left", anchor="nw")
        self.txt_groq_keys = ctk.CTkTextbox(ai_keys_frame, height=60, width=170, font=("Consolas", 11))
        self.txt_groq_keys.pack(side="left", padx=(4, 10), fill="y")
        if self.settings.get("groq_keys"):
            self.txt_groq_keys.insert("1.0", "\n".join(self.settings["groq_keys"]))

        txt_prompt_ctrl = ctk.CTkFrame(ai_keys_frame, fg_color="transparent")
        txt_prompt_ctrl.pack(side="left", anchor="nw")
        ctk.CTkLabel(txt_prompt_ctrl, text="Prompt mẫu (TXT):", font=("", 12)).pack(anchor="w")
        ctk.CTkButton(txt_prompt_ctrl, text="📁 Tải file TXT", width=105, height=24,
                      command=self._sp_pick_prompt_txt,
                      fg_color="#00897B", hover_color="#00695C", font=("", 11)).pack(anchor="w", pady=(2, 0))
        self._sp_prompt_txt_count = ctk.CTkLabel(txt_prompt_ctrl, text="", font=("", 10), text_color="#00E676")
        self._sp_prompt_txt_count.pack(anchor="w")

        self.txt_custom_prompts = ctk.CTkTextbox(ai_keys_frame, height=60, font=("Consolas", 10))
        self.txt_custom_prompts.pack(side="left", padx=(6, 0), fill="both", expand=True)
        if self.settings.get("custom_prompts"):
            self.txt_custom_prompts.insert("1.0", "\n".join(self.settings["custom_prompts"]))
            self._sp_prompt_txt_count.configure(text=f"({len(self.settings['custom_prompts'])} prompt)")
        elif self._sp_prompt_txt_path and os.path.isfile(self._sp_prompt_txt_path):
            try:
                with open(self._sp_prompt_txt_path, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                self.txt_custom_prompts.insert("1.0", "\n".join(lines))
                self._sp_prompt_txt_count.configure(text=f"({len(lines)} prompt)")
            except Exception:
                pass

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

        ctk.CTkLabel(row1b_sp, text="🏷️ Đặt tên:", font=("", 12)).pack(side="left", padx=(6, 0))
        self._sp_naming = ctk.CTkOptionMenu(
            row1b_sp,
            values=["ItemID (mặc định)", "20 ký tự tên SP", "Tên đầy đủ SP"],
            width=160
        )
        self._sp_naming.pack(side="left", padx=(4, 12))
        self._sp_naming.set(self.settings.get("shopee_naming", "ItemID (mặc định)"))

        self._sp_remove_wm = ctk.BooleanVar(value=self.settings.get("shopee_remove_wm", True))
        ctk.CTkCheckBox(row1b_sp, text="🧹 Xóa logo", variable=self._sp_remove_wm,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        self._sp_skip_img = ctk.BooleanVar(value=self.settings.get("shopee_skip_img", False))
        ctk.CTkCheckBox(row1b_sp, text="⏭ Bỏ qua SP đã có ảnh", variable=self._sp_skip_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        

        # Row 1.5: Review Style & AI Prompt
        row1_5 = ctk.CTkFrame(cfg, fg_color="transparent"); row1_5.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(row1_5, text="Kiểu Review:", font=("", 12)).pack(side="left")
        self._sp_review_style = ctk.StringVar(value=self.settings.get("shopee_review_style", "🎲 Random"))
        style_opts = ["🎲 Random", "Review tự nhiên", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "Unboxing", "UGC Authentic", "Demo Công Dụng", "So Sánh/Đánh Giá"]
        self._sp_style_menu = ctk.CTkOptionMenu(row1_5, values=style_opts, variable=self._sp_review_style, width=180)
        self._sp_style_menu.pack(side="left", padx=(4, 12))

        # AI Prompt
        ctk.CTkLabel(row1_5, text="AI Prompt:", font=("", 12)).pack(side="left")
        self._sp_ai_prompt = ctk.CTkOptionMenu(
            row1_5,
            values=["Gemini", "Groq", "Prompt A + B", "Prompt mẫu từ txt"],
            width=165,
            command=self._sp_on_ai_prompt_change
        )
        self._sp_ai_prompt.pack(side="left", padx=(4, 6))
        saved_sp_ai = self.settings.get("shopee_ai_prompt", "Prompt A + B")
        if saved_sp_ai == "Template (mặc định)": saved_sp_ai = "Prompt A + B"
        self._sp_ai_prompt.set(saved_sp_ai)

        self._sp_btn_pick_txt = ctk.CTkButton(
            row1_5,
            text="📁 Chọn TXT",
            command=self._sp_pick_prompt_txt,
            fg_color="#00897B",
            hover_color="#00695C",
            height=28,
            width=90,
            font=("", 11)
        )
        self._sp_btn_pick_txt.pack(side="left", padx=(0, 8))

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

        # Row 1.6: Checkboxes & Tùy chọn bổ trợ
        row1_6 = ctk.CTkFrame(cfg, fg_color="transparent"); row1_6.pack(fill="x", padx=12, pady=(2, 4))

        self._sp_use_laundering = ctk.BooleanVar(value=self.settings.get("shopee_use_laundering", False))
        self._sp_chk_laundering = ctk.CTkCheckBox(row1_6, text="Rửa ảnh (Bypass 429)", variable=self._sp_use_laundering, font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_laundering.pack(side="left", padx=(0, 16))

        self._sp_del_img = ctk.BooleanVar(value=self.settings.get("shopee_del_img", True))
        ctk.CTkCheckBox(row1_6, text="🗑 Xóa ảnh khi tạo xong", variable=self._sp_del_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 16))

        self._sp_ghep_anh = ctk.BooleanVar(value=self.settings.get("shopee_ghep_anh", False))
        self._sp_chk_ghep_anh = ctk.CTkCheckBox(row1_6, text="🎞 Ghép ảnh (12s)", variable=self._sp_ghep_anh,
                                                 font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_ghep_anh.pack(side="left", padx=(0, 16))

        self._sp_auto_clean_temp = ctk.BooleanVar(value=self.settings.get("shopee_auto_clean_temp", True))
        ctk.CTkCheckBox(row1_6, text="🧹 Dọn temp sau:", variable=self._sp_auto_clean_temp,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 4))
        self._sp_temp_cleanup_min = ctk.CTkEntry(row1_6, width=45, font=("", 11))
        self._sp_temp_cleanup_min.pack(side="left", padx=(0, 2))
        self._sp_temp_cleanup_min.insert(0, str(self.settings.get("shopee_temp_cleanup_min", "60")))
        ctk.CTkLabel(row1_6, text="phút", font=("", 11), text_color=T2).pack(side="left", padx=(0, 8))

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

        # Nút import + xem trước
        btn_import_row = ctk.CTkFrame(prod_card, fg_color="transparent"); btn_import_row.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(btn_import_row, text="📂 Import thư mục ảnh", width=160,
                      command=self._sp_import_folder,
                      fg_color="#5C6BC0", hover_color="#3949AB").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="📄 Import tên SP (TXT)", width=160,
                      command=self._sp_import_names_txt,
                      fg_color="#43A047", hover_color="#2E7D32").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="🔗 Import Link (TXT)", width=100,
                      command=self._sp_scrape_links,
                      fg_color="#E65100", hover_color="#EF6C00").pack(side="left", padx=(0, 4))
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

        # Textbox nhập liệu sản phẩm
        self._sp_products = ctk.CTkTextbox(prod_card, font=("Consolas", 11))
        self._sp_products.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        # Cấu hình màu sắc cho từng trạng thái dòng
        self._sp_products.tag_config("status_success", foreground="#2ECC71")  # xanh lá
        self._sp_products.tag_config("status_error", foreground="#E74C3C")    # đỏ
        self._sp_products.tag_config("status_running", foreground="#F39C12")  # cam vàng
        self._sp_products.tag_config("process_tag", foreground="#00E676")     # xanh lá cây nổi bật
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


        # --- Log & Progress ---
        bottom = ctk.CTkFrame(bottom_container, fg_color="transparent"); bottom.pack(fill="x", pady=(8, 0))
        self._sp_progress = ctk.CTkProgressBar(bottom, height=8, progress_color="#EE4D2D")
        self._sp_progress.pack(fill="x", pady=(0, 4))
        self._sp_progress.set(0)

        

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
            with open(os.path.join(APP_DIR, "shopee.txt"), "w", encoding="utf-8") as f:
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



    def _clean_temp_files(self, max_age_seconds=None):
        """Dọn dẹp các file trong thư mục temp_render cũ hơn max_age_seconds (mặc định 60 phút)."""
        temp_dir = os.path.join(APP_DIR, "temp_render")
        if not os.path.exists(temp_dir):
            return 0
        now = time.time()
        removed_count = 0
        for fname in os.listdir(temp_dir):
            fpath = os.path.join(temp_dir, fname)
            try:
                if os.path.isfile(fpath):
                    if max_age_seconds is None or (now - os.path.getmtime(fpath) >= max_age_seconds):
                        os.remove(fpath)
                        removed_count += 1
            except Exception:
                pass
        return removed_count

    def _start_temp_cleaner_thread(self):
        """Luồng chạy nền tự động kiểm tra và dọn dẹp thư mục temp_render định kỳ."""
        def _worker():
            while True:
                time.sleep(300)  # Kiểm tra định kỳ mỗi 5 phút
                try:
                    if hasattr(self, '_sp_auto_clean_temp') and self._sp_auto_clean_temp.get():
                        try:
                            mins = float(self._sp_temp_cleanup_min.get().strip() or "60")
                        except Exception:
                            mins = 60.0
                        if mins > 0:
                            age_sec = mins * 60.0
                            deleted = self._clean_temp_files(max_age_seconds=age_sec)
                            if deleted > 0:
                                self._sp_log_msg(f"🧹 [Auto Clean] Đã dọn dẹp {deleted} file tạm trong temp_render (> {int(mins)} phút)")
                except Exception:
                    pass
        threading.Thread(target=_worker, daemon=True).start()

    def _sp_on_duration_change(self): pass
    def _sp_on_model_change(self): pass

    def _sp_pick_prompt_txt(self):
        """Mở hộp thoại để người dùng chọn file chứa prompt mẫu (.txt)."""
        fpath = filedialog.askopenfilename(
            title="Chọn file chứa prompt mẫu (.txt)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not fpath:
            return
        self._sp_prompt_txt_path = fpath
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
            if hasattr(self, "txt_custom_prompts"):
                self.txt_custom_prompts.delete("1.0", "end")
                self.txt_custom_prompts.insert("1.0", "\n".join(lines))
            self._sp_ai_prompt.set("Prompt mẫu từ txt")
            if hasattr(self, "_sp_prompt_txt_count"):
                self._sp_prompt_txt_count.configure(text=f"({len(lines)} prompt)")
            self._sp_log_msg(f"✅ Đã nạp {len(lines)} prompt từ: {os.path.basename(fpath)}")
            try:
                self._save_settings_from_ui()
            except Exception:
                pass
        except Exception as e:
            self._sp_log_msg(f"❌ Lỗi đọc file prompt: {e}")
            messagebox.showerror("Lỗi đọc file", f"Không thể đọc file prompt:\n{e}")

    def _sp_on_ai_prompt_change(self, choice=None):
        """Xử lý khi người dùng đổi lựa chọn AI Prompt."""
        val = self._sp_ai_prompt.get()
        if "txt" in val.lower() or "mẫu" in val.lower():
            prompts = self._sp_get_custom_prompts()
            if not prompts:
                self._sp_pick_prompt_txt()
            else:
                if hasattr(self, "_sp_prompt_txt_count"):
                    self._sp_prompt_txt_count.configure(text=f"({len(prompts)} prompt)")
                self._sp_log_msg(f"ℹ️ Đã chọn 'Prompt mẫu từ txt' ({len(prompts)} prompt sẵn sàng)")

    def _sp_get_custom_prompts(self):
        """Lấy danh sách các dòng prompt mẫu từ textbox hoặc file txt."""
        prompts = []
        if hasattr(self, "txt_custom_prompts"):
            prompts = [l.strip() for l in self.txt_custom_prompts.get("1.0", "end").splitlines() if l.strip() and not l.strip().startswith("#")]
        if not prompts and getattr(self, "_sp_prompt_txt_path", ""):
            p_path = getattr(self, "_sp_prompt_txt_path", "")
            if os.path.isfile(p_path):
                try:
                    with open(p_path, "r", encoding="utf-8") as f:
                        prompts = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                except Exception:
                    pass
        return prompts

    def _sp_format_custom_prompt(self, template, product_name, scene_en="", clip_dur=8):
        """Thay thế placeholder {product}, {name}, {scene}, {duration} trong prompt mẫu."""
        prompt = template
        for placeholder in ("{product}", "{product_name}", "{name}", "{title}"):
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, product_name)
        if "{scene}" in prompt and scene_en:
            prompt = prompt.replace("{scene}", scene_en)
        if "{duration}" in prompt:
            prompt = prompt.replace("{duration}", f"{clip_dur}s")
        return prompt.strip()

    def _sp_get_prompts_for_job(self, job_idx, product_name, scene_en="", n_segments=1, clip_dur=8, is_random=False):
        """Lấy list n_segments prompt cho một sản phẩm từ danh sách prompt mẫu."""
        custom_prompts = self._sp_get_custom_prompts()
        if not custom_prompts:
            return None
        selected = []
        for seg in range(n_segments):
            if is_random:
                raw_p = random.choice(custom_prompts)
            else:
                idx = (job_idx * n_segments + seg) % len(custom_prompts)
                raw_p = custom_prompts[idx]
            formatted_p = self._sp_format_custom_prompt(raw_p, product_name, scene_en, clip_dur)
            selected.append(formatted_p)
        return selected


    def _sp_test_prompt(self):
        """Kiểm tra và sinh thử prompt cho sản phẩm đầu tiên hoặc sản phẩm mẫu."""
        text = self._sp_products.get("1.0", "end").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        sample_prod = self._sp_strip_status(lines[0]) if lines else "https://shopee.vn/product/1367044604/41901130099"

        self._sp_log_msg("🧪 --- BẮT ĐẦU TEST PROMPT ---")
        self._sp_log_msg(f"📌 Sản phẩm: {sample_prod[:60]}")
        
        prompt_type = self._sp_ai_prompt.get()
        review_style = self._sp_review_style.get()
        no_model_val = self._sp_no_model.get()
        self._sp_log_msg(f"⚙️ Kiểu: {review_style} | Không mẫu: {no_model_val} | AI: {prompt_type}")

        def _worker():
            try:
                import shopee_ai, shopee_scraper
                desc_text = ""
                img_path = None
                p_name = sample_prod
                if sample_prod.startswith("http://") or sample_prod.startswith("https://"):
                    self._sp_log_msg("🌐 Đang cào thông tin link test...")
                    info = shopee_scraper.fetch_shopee_product(sample_prod)
                    if info:
                        p_name = info.get("title", sample_prod)
                        desc_text = info.get("description", "")
                        if info.get("image_url"):
                            temp_dir = os.path.join(APP_DIR, "temp_render")
                            img_path = shopee_scraper.download_image(info["image_url"], temp_dir)
                else:
                    if "|" in sample_prod:
                        parts = sample_prod.split("|", 1)
                        p_name = parts[1].strip() if os.path.exists(parts[0].strip()) else parts[0].strip()
                        raw_img = parts[0].strip() if os.path.exists(parts[0].strip()) else parts[1].strip()
                        img_path = self._sp_resolve_img(raw_img)

                lang_val = self._sp_lang.get()
                lang_code = "vi" if "Việt" in lang_val else "en"
                scene_choice = self._sp_scene.get()
                scene_en = SV.SCENE_MAP.get(scene_choice, "modern clean studio")
                clip_dur = int(SV.parse_duration(self._sp_duration.get()))
                n_segments = len(SV.DURATION_MAP.get(clip_dur, [0, 2]))

                res_prompts = None
                if "txt" in prompt_type.lower() or "mẫu" in prompt_type.lower():
                    is_rnd = "random" in review_style.lower()
                    c_prompts = self._sp_get_custom_prompts()
                    if not c_prompts:
                        self._sp_log_msg("⚠️ Ô 'Prompt mẫu (TXT)' đang trống! Vui lòng bấm '📁 Chọn TXT' hoặc dán prompt vào ô.")
                        res_prompts = SV.build_video_prompts(
                            p_name, scene_en, clip_dur, lang=lang_code,
                            review_style=review_style, no_model=no_model_val, image_path=img_path
                        )
                    else:
                        res_prompts = self._sp_get_prompts_for_job(
                            0, p_name, scene_en=scene_en, n_segments=n_segments,
                            clip_dur=clip_dur, is_random=is_rnd
                        )
                        self._sp_log_msg(f"📄 [Prompt mẫu từ TXT] Có tổng cộng {len(c_prompts)} prompt trong danh sách.")
                elif prompt_type in ("Gemini", "Groq"):
                    gem_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
                    grq_keys = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]
                    ai_mode_lower = "gemini" if prompt_type == "Gemini" else "groq"

                    res_prompts = shopee_ai.ai_gen_prompts(
                        p_name, scene_en, n_segments, clip_dur, lang_code, review_style,
                        mode=ai_mode_lower, gemini_keys=gem_keys, groq_keys=grq_keys,
                        product_desc=desc_text,
                        image_path=img_path,
                        no_model=no_model_val,
                        log_cb=self._sp_log_msg
                    )
                else:
                    res_prompts = SV.build_video_prompts(
                        p_name, scene_en, clip_dur, lang=lang_code,
                        review_style=review_style, no_model=no_model_val, image_path=img_path
                    )

                if not res_prompts:
                    self._sp_log_msg("⚠️ Fallback sang Prompt Template...")
                    res_prompts = SV.build_video_prompts(
                        p_name, scene_en, clip_dur, lang=lang_code,
                        review_style=review_style, no_model=no_model_val, image_path=img_path
                    )

                if res_prompts:
                    self._sp_log_msg("🎉 KẾT QUẢ PROMPT ĐÃ SINH:")
                    for idx, p in enumerate(res_prompts, 1):
                        self._sp_log_msg(f"[{idx}] {p}")
                else:
                    self._sp_log_msg("❌ Không sinh được prompt nào.")
            except Exception as e:
                self._sp_log_msg(f"❌ Lỗi Test prompt: {e}")

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _sp_strip_status(self, line):
        """Bỏ prefix trạng thái (✅/❌/⏳) khỏi dòng."""
        for pfx in self._SP_STATUS_PREFIXES:
            if line.startswith(pfx):
                return line[len(pfx):]
        return line
    def _sp_restore_line_colors(self):
        """Khôi phục màu sắc cho các dòng đã có trạng thái (✅/❌) khi load lại."""
        try:
            text = self._sp_products.get("1.0", "end").strip()
            for i, line in enumerate(text.splitlines()):
                tk_line = i + 1
                if line.startswith("✅ "):
                    self._sp_products.tag_add("status_success", f"{tk_line}.0", f"{tk_line}.end")
                elif line.startswith("❌ "):
                    self._sp_products.tag_add("status_error", f"{tk_line}.0", f"{tk_line}.end")
        except Exception:
            pass

    def _sp_update_count(self):
        try:
            text = self._sp_products.get("1.0", "end").strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            total = len(lines)
            done = sum(1 for l in lines if l.startswith("✅"))
            fail = sum(1 for l in lines if l.startswith("❌"))
            pending = total - done - fail
            if done or fail:
                self._sp_prod_count.configure(text=f"{total} SP (✅{done} ❌{fail} ⏳{pending})")
            else:
                self._sp_prod_count.configure(text=f"{total} SP")
        except Exception:
            pass

    def _sp_import_folder(self):
        """Import ảnh từ thư mục: tự động ghép Tên Ảnh với Tên SP hiện có (nếu có).
        Format: ảnh.jpg | Tên SP.
        Tối ưu cho 20k+ ảnh: batch insert, skip auto-preview."""
        from tkinter import filedialog as fd
        folder = fd.askdirectory(title="Chọn thư mục chứa ảnh sản phẩm")
        if not folder:
            return
        _img_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
        files = sorted((f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in _img_exts), key=natural_sort_key)
        if not files:
            messagebox.showinfo("Trống", "Không tìm thấy ảnh nào trong thư mục.")
            return
        self._sp_img_folder = folder  # lưu thư mục để resolve path khi chạy

        # Đọc danh sách hiện có trong textbox
        current_text = self._sp_products.get("1.0", "end").strip()
        current_lines = [l.strip() for l in current_text.splitlines() if l.strip()]

        existing_names = []
        for cl in current_lines:
            clean = self._sp_strip_status(cl)
            if "|" in clean:
                parts = clean.split("|", 1)
                left, right = parts[0].strip(), parts[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    existing_names.append(right)
                else:
                    existing_names.append(left)
            else:
                existing_names.append(clean)

        new_lines = []
        for i, fn in enumerate(files):
            if i < len(existing_names) and existing_names[i]:
                name = existing_names[i]
            else:
                name = os.path.splitext(fn)[0]
            new_lines.append(f"{fn} | {name}")

        bulk = "\n".join(new_lines)
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", bulk)
        self._sp_update_count()
        self._sp_log_msg(f"📂 Đã import {len(files)} ảnh từ: {folder}")

    def _sp_scrape_links(self):
        """Đọc file chứa link shopee, đưa trực tiếp link vào Textbox (tải lười khi tạo video)."""
        from tkinter import filedialog as fd
        txt_path = fd.askopenfilename(title="Chọn file TXT chứa link Shopee",
                                       filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not txt_path: return
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                links = [l.strip() for l in f if l.strip()]
        except Exception as e:
            messagebox.showerror("Lỗi", str(e)); return
            
        if not links:
            messagebox.showinfo("Trống", "File TXT không có nội dung."); return
            
        bulk = "\n".join(links)
        curr = self._sp_products.get("1.0", "end").strip()
        self._sp_products.configure(state="normal")
        if curr:
            self._sp_products.insert("end", "\n" + bulk + "\n")
        else:
            self._sp_products.insert("1.0", bulk + "\n")
        self._sp_update_count()
        self._sp_log_msg(f"🔗 Đã nạp {len(links)} link Shopee vào danh sách.")

    def _sp_import_names_txt(self):
        """Import tên SP từ file TXT (mỗi dòng 1 tên).
        Ghi đè/ghép tên SP với danh sách ảnh hiện tại (hoặc thư mục ảnh đã chọn).
        Format: ảnh.jpg | Tên SP.
        Tối ưu cho 20k+ dòng: batch build, single insert.
        """
        from tkinter import filedialog as fd
        txt_path = fd.askopenfilename(title="Chọn file TXT chứa tên sản phẩm",
                                       filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not txt_path:
            return
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                names = [l.strip() for l in f if l.strip()]
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không đọc được file: {e}")
            return
        if not names:
            messagebox.showinfo("Trống", "File TXT không có dòng nào.")
            return

        _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}

        # Đọc danh sách hiện tại
        current_text = self._sp_products.get("1.0", "end").strip()
        current_lines = [l.strip() for l in current_text.splitlines() if l.strip()]

        img_parts = []
        for cl in current_lines:
            clean = self._sp_strip_status(cl)
            if "|" in clean:
                p = clean.split("|", 1)
                left, right = p[0].strip(), p[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    img_parts.append(left)
                else:
                    img_parts.append(right)
            else:
                img_parts.append("")

        # Nếu chưa có ảnh trong textbox nhưng đã có thư mục ảnh _sp_img_folder
        if not any(img_parts) and self._sp_img_folder and os.path.isdir(self._sp_img_folder):
            import re
            def natural_sort_key(s):
                return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            folder_files = sorted(
                (f for f in os.listdir(self._sp_img_folder) if os.path.splitext(f)[1].lower() in _img_exts),
                key=natural_sort_key
            )
            if folder_files:
                img_parts = folder_files

        new_lines = []
        for i, name in enumerate(names):
            if i < len(img_parts) and img_parts[i]:
                new_lines.append(f"{img_parts[i]} | {name}")
            else:
                new_lines.append(name)

        if len(names) < len(img_parts):
            for j in range(len(names), len(img_parts)):
                if j < len(current_lines):
                    new_lines.append(current_lines[j])
                elif img_parts[j]:
                    new_lines.append(f"{img_parts[j]} | {os.path.splitext(img_parts[j])[0]}")

        bulk = "\n".join(new_lines)
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", bulk)
        self._sp_log_msg(f"📄 Đã ghép {len(names)} tên SP từ TXT với danh sách ảnh hiện có")

    def _sp_clear_all(self):
        self._sp_products.delete("1.0", "end")

    def _sp_clear_status(self):
        text = self._sp_products.get("1.0", "end")
        new_lines = []
        for line in text.splitlines():
            clean = line
            for pfx in ("✅ ", "❌ ", "⚠️ "):
                if clean.startswith(pfx): clean = clean[len(pfx):]
            new_lines.append(clean)
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", "\n".join(new_lines))

    def _sp_clear_success(self):
        text = self._sp_products.get("1.0", "end")
        new_lines = [l for l in text.splitlines() if not l.startswith("✅ ")]
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", "\n".join(new_lines))

    def _shopee_open_folder(self):
        d = self._sp_outdir.get().strip()
        if d and os.path.exists(d): os.startfile(d)
        
    def _pick(self, entry):
        d = filedialog.askdirectory()
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)
            
    def _sp_pick_model(self):
        self._pick(self._sp_model_dir)

    def _sp_strip_status(self, line):
        import re
        clean = line.strip()
        for pfx in ("✅ ", "❌ ", "⚠️ ", "⚠ ", "⏳ "):
            if clean.startswith(pfx):
                clean = clean[len(pfx):].strip()
        clean = re.sub(r'\s*\[[^\]]*\]$', '', clean).strip()
        return clean
        
    def _sp_resolve_img(self, img_path):
        if not img_path: return ""
        if img_path.startswith("http"): return img_path
        if os.path.isabs(img_path) and os.path.isfile(img_path): return img_path
        if hasattr(self, '_sp_img_folder') and self._sp_img_folder:
            import os
            full = os.path.join(self._sp_img_folder, img_path)
            if os.path.isfile(full):
                return full
        return os.path.abspath(img_path)
        
    def _sp_log_msg(self, msg):
        ts = time.strftime('%H:%M:%S')
        formatted = f"[{ts}] {msg}"
        try:
            if hasattr(self, '_log_file_path'):
                with open(self._log_file_path, "a", encoding="utf-8") as lf:
                    lf.write(formatted + "\n")
        except Exception:
            pass
        def _do():
            try:
                self._sp_log.configure(state="normal")
                self._sp_log.insert("end", formatted + "\n")
                num_lines = int(self._sp_log.index("end-1c").split(".")[0])
                if num_lines > 1000:
                    self._sp_log.delete("1.0", "150.0")
                self._sp_log.see("end")
                self._sp_log.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _do)
        
    def _shopee_stop(self):
        self._shopee_stop_flag = True
        self._sp_log_msg("⏳ Đang dừng...")

    def _shopee_start(self):
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được."); return
        api_key = self._seed_apikey.get().strip()
        if not api_key:
            messagebox.showwarning("Thiếu API Key", "Vui lòng nhập Seedvis API Key!"); return
            
        text = self._sp_products.get("1.0", "end").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            messagebox.showwarning("Thiếu SP", "Hãy nhập ít nhất 1 sản phẩm."); return
            
        out_dir = self._sp_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục lưu video."); return
            
        if self._sp_no_model.get():
            model_images = []
        else:
            model_dir = self._sp_model_dir.get().strip()
            if model_dir and os.path.isdir(model_dir):
                model_images = SV.list_model_images(model_dir)
            else:
                model_images = []

        products = []
        skipped = 0
        _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}
        for line_idx, line in enumerate(lines):
            clean = self._sp_strip_status(line)
            if line.startswith("✅ "):
                skipped += 1
                continue
            # Nếu dòng là link URL (Shopee hoặc web)
            if clean.startswith("http://") or clean.startswith("https://"):
                products.append({
                    "name": clean,
                    "img": "",
                    "url": clean,
                    "_line_idx": line_idx,
                    "desc": ""
                })
                continue
            if "|" in clean:
                parts = clean.split("|", 1)
                left = parts[0].strip()
                right = parts[1].strip()
                import os
                if os.path.splitext(left)[1].lower() in _img_exts or os.path.isabs(left) or left.startswith("http"):
                    img_path, name = left, right
                else:
                    name, img_path = left, right
            else:
                name = clean.strip()
                img_path = ""
            if name:
                resolved = self._sp_resolve_img(img_path)
                desc_text = ""
                if resolved and __import__('os').path.exists(resolved + ".desc.txt"):
                    try:
                        with open(resolved + ".desc.txt", "r", encoding="utf-8") as df:
                            desc_text = df.read()
                    except: pass
                products.append({"name": name, "img": resolved, "_line_idx": line_idx, "desc": desc_text})
                
        if skipped:
            self._sp_log_msg(f"⏭ Bỏ qua {skipped} SP đã thành công (✅)")
        if not products:
            messagebox.showwarning("Thiếu SP", "Không có SP nào cần xử lý."); return

        for p in products:
            if p.get("url"):
                continue  # Bỏ qua kiểm tra ảnh cho SP dạng link URL, sẽ tự tải khi tới lượt
            if p["img"] and not p["img"].startswith("http") and not os.path.isfile(p["img"]):
                messagebox.showwarning("Ảnh không tồn tại", f"Không tìm thấy ảnh: {p['img']}"); return
            if not p["img"]:
                messagebox.showwarning("Thiếu ảnh SP", f"Sản phẩm '{p['name']}' chưa có ảnh."); return

        self._save_settings_from_ui()
        self._shopee_running = True
        self._shopee_stop_flag = False
        self._sp_btn_start.configure(state="disabled")
        self._sp_btn_stop.configure(state="normal")
        self._shopee_status.configure(text="⏳ Đang xử lý...")
        self._sp_log.configure(state="normal")
        self._sp_log.delete("1.0", "end")
        self._sp_log.configure(state="disabled")
        self._sp_result_card.pack_forget()

        import threading
        threading.Thread(target=self._seed_worker_loop, args=(products, api_key, model_images, out_dir), daemon=True).start()

    def _run_ghep_anh_12s(self, video_path, image_path, output_path):
        """Ghép ảnh outro vào video tạo video 12s bằng ffmpeg."""
        import subprocess
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-loop", "1", "-t", "3.5", "-i", image_path,
                "-filter_complex", "[0:v]setpts=PTS-STARTPTS[v0];[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0[outv]",
                "-map", "[outv]", "-c:v", "libx264", "-preset", "superfast", output_path
            ]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=90)
            return True, ""
        except Exception as ex:
            return False, str(ex)

    def _seed_worker_loop(self, products, api_key, model_images, out_dir):
        try:
            threads = int(self._seed_threads.get().strip() or "3")
        except:
            threads = 3
            
        import concurrent.futures
        self._sp_progress.set(0.0)
        total = len(products)
        completed = 0
        
        def process_product(prod):
            if self._shopee_stop_flag: return False
            line_idx = prod["_line_idx"]
            name = prod.get("name", "Shopee Product")
            img = prod.get("img", "")
            start_prod_ts = time.time()
            
            try:
                # --- 0. Tải thông tin & Ảnh Shopee khi tới lượt ---
                if prod.get("url"):
                    shopee_url = prod["url"]
                    self._update_line_progress(line_idx, "⏳ ", "Cào Shopee...")
                    self._sp_log_msg(f"🌐 Đang lấy thông tin Shopee: {shopee_url[:45]}...")
                    import shopee_scraper
                    info = shopee_scraper.fetch_shopee_product(shopee_url)
                    if not info or not info.get("image_url"):
                        self._sp_log_msg(f"❌ Không lấy được dữ liệu Shopee: {shopee_url}")
                        self._update_line_status(line_idx, False, "Lỗi cào link")
                        return False
                        
                    self._update_line_progress(line_idx, "⏳ ", "Tải ảnh...")
                    temp_dir = os.path.join(APP_DIR, "temp_render")
                    img_path = shopee_scraper.download_image(info["image_url"], temp_dir)
                    if not img_path:
                        self._sp_log_msg(f"❌ Tải ảnh thất bại: {info['image_url']}")
                        self._update_line_status(line_idx, False, "Lỗi tải ảnh")
                        return False
                        
                    name = info["title"] if info.get("title") else "Shopee Product"
                    prod["name"] = name
                    prod["desc"] = info.get("description", "")
                    prod["img"] = img_path
                    img = img_path
                    
                    def _update_ui_line(l_idx=line_idx, title=name):
                        try:
                            cur = self._sp_products.get(f"{l_idx+1}.0", f"{l_idx+1}.end")
                            c_clean = self._sp_strip_status(cur)
                            self._sp_products.delete(f"{l_idx+1}.0", f"{l_idx+1}.end")
                            self._sp_products.insert(f"{l_idx+1}.0", f"⏳ {title} | {c_clean}  [Đang khởi tạo...]")
                        except: pass
                    self.after(0, _update_ui_line)
                    
                self._sp_log_msg(f"🔄 Bắt đầu: {name[:40]}...")
                self._update_line_progress(line_idx, "⏳ ", "Chuẩn bị...")
                
                # --- 1. Chuẩn bị ảnh ---
                final_img = prod.get("img", img)
                if not final_img or not os.path.isfile(final_img):
                    self._sp_log_msg(f"❌ Không tìm thấy ảnh hợp lệ cho {name[:30]}")
                    self._update_line_status(line_idx, False, "Thiếu ảnh")
                    return False
                    
                if self._sp_use_laundering.get():
                    self._update_line_progress(line_idx, "⏳ ", "Rửa ảnh...")
                    try:
                        clean_path = os.path.join(out_dir, f"clean_{uuid.uuid4().hex[:6]}.jpg")
                        from PIL import Image
                        with Image.open(final_img) as im:
                            im.convert("RGB").save(clean_path, "JPEG", quality=95)
                        if final_img != img:
                            try: os.remove(final_img)
                            except: pass
                        final_img = clean_path
                    except Exception as e:
                        self._sp_log_msg(f"⚠️ Lỗi rửa ảnh: {e}")
                        
                # --- 2. Tạo Prompt AI ---
                import shopee_ai
                prompt_type = self._sp_ai_prompt.get()
                scene_choice = self._sp_scene.get()
                scene_en = SV.SCENE_MAP.get(scene_choice, "random modern aesthetic")
                clip_dur = int(SV.parse_duration(self._sp_duration.get()))
                n_segments = len(SV.DURATION_MAP.get(clip_dur, [0, 2]))
                review_style = self._sp_review_style.get()
                
                lang_val = self._sp_lang.get()
                lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
                
                prompts = None
                if "txt" in prompt_type.lower() or "mẫu" in prompt_type.lower():
                    self._update_line_progress(line_idx, "⏳ ", "Lấy prompt TXT...")
                    is_rnd = "random" in review_style.lower()
                    c_prompts = self._sp_get_custom_prompts()
                    if c_prompts:
                        prompts = self._sp_get_prompts_for_job(
                            line_idx, name, scene_en=scene_en, n_segments=n_segments,
                            clip_dur=clip_dur, is_random=is_rnd
                        )
                        p_num = ((line_idx * n_segments) % len(c_prompts)) + 1 if not is_rnd else "random"
                        self._sp_log_msg(f"📄 [Prompt TXT] Áp dụng mẫu #{p_num} cho: {name[:30]}")
                    else:
                        self._sp_log_msg("⚠️ Danh sách prompt mẫu trống! Fallback sang Prompt A + B.")
                elif prompt_type in ("Gemini", "Groq"):
                    self._update_line_progress(line_idx, "⏳ ", f"Sinh prompt ({prompt_type})...")
                    gem_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
                    grq_keys = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]
                    ai_mode_lower = "gemini" if prompt_type == "Gemini" else "groq"
                    prompts = shopee_ai.ai_gen_prompts(
                        name, scene_en, n_segments, clip_dur, lang_code, review_style,
                        mode=ai_mode_lower, gemini_keys=gem_keys, groq_keys=grq_keys,
                        product_desc=prod.get("desc", ""),
                        image_path=final_img,
                        no_model=self._sp_no_model.get(),
                        log_cb=self._sp_log_msg
                    )
                    
                if not prompts:
                    self._sp_log_msg("📝 Dùng prompt template...")
                    prompts = SV.build_video_prompts(
                        name, scene_en, clip_dur, lang=lang_code,
                        review_style=review_style,
                        no_model=self._sp_no_model.get(),
                        image_path=final_img
                    )
                    
                ai_prompt = prompts[0] if prompts else name
                
                # --- 3. Gửi yêu cầu Seedvis ---
                self._update_line_progress(line_idx, "⏳ ", "Gửi Seedvis...")
                with open(final_img, "rb") as f:
                    b64_img = base64.b64encode(f.read()).decode("utf-8")
                    
                model_choice = "Veo-3.1"
                seed_aspect = "9:16" if "9:16" in self._sp_aspect.get() else "16:9"
                payload = {
                    "model": model_choice,
                    "prompt": ai_prompt,
                    "mode": "image-to-video",
                    "image": {"data": b64_img, "file_name": "image.jpg"},
                    "aspect_ratio": seed_aspect,
                    "duration": f"{clip_dur}s" if clip_dur in (4, 6, 8) else "8s",
                    "count": 1,
                    "upscale_video": "none"
                }
                
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": str(uuid.uuid4()),
                    "User-Agent": SEEDVIS_UA,
                }
                
                self._sp_log_msg(f"🚀 Gửi Seedvis: {name[:25]}...")
                job_id = None
                try:
                    req_data = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request("https://seedvis.com/api/v1/developer/generations", data=req_data, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        job_id = res_json.get("data", {}).get("id") or res_json.get("data", {}).get("job_id")
                        next_url = res_json.get("data", {}).get("next", {}).get("url")
                except urllib.error.HTTPError as he:
                    try: err_body = he.read().decode("utf-8")
                    except: err_body = str(he)
                    self._sp_log_msg(f"❌ Seedvis Lỗi ({he.code}): {err_body[:80]}")
                    self._update_line_status(line_idx, False, f"Lỗi Seedvis {he.code}")
                    return False
                except Exception as e:
                    self._sp_log_msg(f"❌ Lỗi mạng Seedvis: {e}")
                    self._update_line_status(line_idx, False, "Lỗi mạng")
                    return False
                    
                if not job_id:
                    self._sp_log_msg(f"❌ Không nhận được job_id từ Seedvis")
                    self._update_line_status(line_idx, False, "Thiếu Job ID")
                    return False
                    
                # --- 4. Poll kết quả Seedvis ---
                self._sp_log_msg(f"⏳ Chờ tạo video (Job: {job_id[:8]}...)...")
                poll_url = next_url if (locals().get("next_url")) else f"https://seedvis.com/api/v1/developer/generations/{job_id}?wait=60"
                video_url = None
                start_ts = time.time()
                while time.time() - start_ts < 600:
                    if self._shopee_stop_flag: return False
                    elapsed = int(time.time() - start_ts)
                    self._update_line_progress(line_idx, "⏳ ", f"Đang tạo ({elapsed}s)...")
                    try:
                        req = urllib.request.Request(poll_url, headers=headers, method="GET")
                        with urllib.request.urlopen(req, timeout=70) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                    except Exception:
                        time.sleep(6)
                        continue
                        
                    job_data = data.get("data", {})
                    next_poll_url = job_data.get("next", {}).get("url")
                    if next_poll_url:
                        poll_url = next_poll_url
                        
                    if job_data.get("is_final", False):
                        status = (job_data.get("status") or "").lower()
                        if status in ("completed", "succeeded"):
                            outputs = job_data.get("outputs", [])
                            if outputs and outputs[0].get("url"):
                                video_url = outputs[0]["url"]
                                break
                        self._sp_log_msg(f"❌ Seedvis báo thất bại (status: {status})")
                        self._update_line_status(line_idx, False, f"Seedvis {status}")
                        return False
                
                if not video_url:
                    self._sp_log_msg("❌ Timeout chờ video từ Seedvis")
                    self._update_line_status(line_idx, False, "Timeout 10p")
                    return False
                    
                # --- 5. Tải & Lưu video ---
                self._update_line_progress(line_idx, "⏳ ", "Đang tải video...")
                # Xác định tên file video theo cài đặt
                naming_mode = self._sp_naming.get() if hasattr(self, "_sp_naming") else "ItemID (mặc định)"
                if "ItemID" in naming_mode:
                    shopee_url = prod.get("url", "") or ""
                    import re
                    m = re.search(r'product/\d+/(\d+)|-i\.\d+\.(\d+)', shopee_url)
                    if m:
                        item_id = m.group(1) or m.group(2)
                        base_name = str(item_id)
                    else:
                        base_name = SV.clean_filename(name)[:20].strip("_- ")
                elif "20" in naming_mode:
                    clean_n = SV.clean_filename(name)
                    base_name = clean_n[:20].strip("_- ")
                else:
                    base_name = SV.clean_filename(name)
                    
                if not base_name:
                    base_name = f"video_{uuid.uuid4().hex[:6]}"

                final_vid = os.path.join(out_dir, f"{base_name}.mp4")
                counter = 1
                while os.path.exists(final_vid):
                    final_vid = os.path.join(out_dir, f"{base_name}_{counter}.mp4")
                    counter += 1
                    
                self._sp_log_msg(f"⬇️ Đang tải video hoàn chỉnh...")
                try:
                    from curl_cffi import requests as cffi_requests
                    dl_headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    }
                    v_resp = cffi_requests.get(video_url, headers=dl_headers, impersonate="chrome124", timeout=120)
                    if v_resp.status_code == 403:
                        dl_headers["Authorization"] = f"Bearer {api_key}"
                        v_resp = cffi_requests.get(video_url, headers=dl_headers, impersonate="chrome124", timeout=120)
                    if v_resp.status_code != 200:
                        raise Exception(f"HTTP {v_resp.status_code} ({v_resp.text[:80]})")
                    with open(final_vid, "wb") as vf:
                        vf.write(v_resp.content)
                except Exception as e:
                    self._sp_log_msg(f"❌ Lỗi tải file video: {e}")
                    self._update_line_status(line_idx, False, "Lỗi tải video")
                    return False
                    
                # Xóa logo nếu có
                if self._sp_remove_wm.get():
                    self._update_line_progress(line_idx, "⏳ ", "Đang xóa logo...")
                    self._sp_log_msg("✨ Đang xóa logo Veo...")
                    try:
                        SV.remove_veo_watermark(final_vid, log=self._sp_log_msg)
                    except Exception as e:
                        self._sp_log_msg(f"⚠️ Lỗi xóa logo: {e}")
                        
                # Ghép ảnh outro 12s nếu có
                if self._sp_ghep_anh.get() and clip_dur == 8:
                    self._update_line_progress(line_idx, "⏳ ", "Ghép ảnh 12s...")
                    self._sp_log_msg("🎬 Ghép ảnh outro 12s...")
                    merged_path = os.path.join(out_dir, f"merged12s_{base_name}.mp4")
                    ok_m, err_m = self._run_ghep_anh_12s(final_vid, final_img, merged_path)
                    if ok_m and os.path.exists(merged_path):
                        try: os.remove(final_vid)
                        except: pass
                        final_vid = merged_path
                        
                total_dur = int(time.time() - start_prod_ts)
                self._sp_log_msg(f"✅ HOÀN THÀNH: {os.path.basename(final_vid)}")
                self._update_line_status(line_idx, True, f"Xong ({total_dur}s)")
                
                if self._sp_del_img.get() and os.path.exists(final_img):
                    try: os.remove(final_img)
                    except: pass
                return True
                
            except Exception as ex:
                self._sp_log_msg(f"❌ Lỗi xử lý {name[:30]}: {ex}")
                self._update_line_status(line_idx, False, "Lỗi ngoại lệ")
                return False

        # Chạy đa luồng
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(process_product, p) for p in products]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self._sp_log_msg(f"❌ Lỗi ngoại lệ: {e}")
                completed += 1
                self.after(0, lambda: self._sp_progress.set(completed / total))

        self.after(0, self._on_finish)

    def _update_line_progress(self, line_idx, status_pfx="⏳ ", step_text=""):
        """Cập nhật trạng thái và tiến trình trực tiếp ở cuối dòng sản phẩm (chữ process màu xanh lá cây)."""
        def _do():
            try:
                tk_line = line_idx + 1
                content = self._sp_products.get(f"{tk_line}.0", f"{tk_line}.end")
                clean = self._sp_strip_status(content)
                
                if step_text:
                    prefix_body = f"{status_pfx}{clean}  "
                    proc_tag_txt = f"[{step_text}]"
                    new_text = prefix_body + proc_tag_txt
                else:
                    prefix_body = f"{status_pfx}{clean}"
                    proc_tag_txt = ""
                    new_text = prefix_body
                    
                self._sp_products.delete(f"{tk_line}.0", f"{tk_line}.end")
                self._sp_products.insert(f"{tk_line}.0", new_text)
                
                tag = "status_success" if "✅" in status_pfx else ("status_error" if "❌" in status_pfx else "status_running")
                for t in ("status_success", "status_error", "status_running", "process_tag"):
                    self._sp_products.tag_remove(t, f"{tk_line}.0", f"{tk_line}.end")
                
                if proc_tag_txt:
                    split_col = len(prefix_body)
                    self._sp_products.tag_add(tag, f"{tk_line}.0", f"{tk_line}.{split_col}")
                    # Màu xanh lá cây cho chữ process
                    self._sp_products.tag_add("process_tag", f"{tk_line}.{split_col}", f"{tk_line}.end")
                else:
                    self._sp_products.tag_add(tag, f"{tk_line}.0", f"{tk_line}.end")
                    
                self._sp_update_count()
            except Exception:
                pass
        self.after(0, _do)

    def _update_line_status(self, line_idx, is_success, note=""):
        pfx = "✅ " if is_success else "❌ "
        msg = note if note else ("Hoàn thành" if is_success else "Thất bại")
        self._update_line_progress(line_idx, pfx, msg)
        
    def _on_finish(self):
        self._shopee_running = False
        self._sp_btn_start.configure(state="normal")
        self._sp_btn_stop.configure(state="disabled")
        self._shopee_status.configure(text="✅ Hoàn tất!")
        self._sp_log_msg("🎉 Đã chạy xong toàn bộ danh sách!")

def import_rnd(lst):
    import random
    return random.choice(lst) if lst else None

if __name__ == "__main__":
    app = AutoSeedvisApp()
    app.mainloop()
