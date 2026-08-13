import sys

file_path = r'e:\ThinAptm0707\thin_aptm.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip_until = -1

for i, line in enumerate(lines):
    if skip_until > i:
        continue
    
    new_lines.append(line)
    
    # Change 1
    if i == 466 and 'self.proxy_pool =' in line:
        new_lines.append('        # Auto HomeProxy\n')
        new_lines.append('        self._auto_homeproxy = ctk.BooleanVar(value=self.settings.get("auto_homeproxy", False))\n')
        new_lines.append('        self._homeproxy_token = ctk.StringVar(value=self.settings.get("homeproxy_token", ""))\n')
    
    # Change 2
    if i == 583 and 'self._update_proxy_stats()' in line:
        new_lines.append('        # --- Auto HomeProxy ---\n')
        new_lines.append('        hp_frame = ctk.CTkFrame(pxcard, fg_color="transparent")\n')
        new_lines.append('        hp_frame.pack(fill="x", padx=12, pady=(4, 0))\n')
        new_lines.append('        self.chk_auto_hp = ctk.CTkCheckBox(hp_frame, text="\\U0001f3e0 Auto HomeProxy",\n')
        new_lines.append('            variable=self._auto_homeproxy, font=("", 11), checkbox_width=16, checkbox_height=16)\n')
        new_lines.append('        self.chk_auto_hp.pack(side="left")\n')
        new_lines.append('        ctk.CTkButton(hp_frame, text="\\U0001f504 T\\u1ea3i Proxy", command=self._fetch_homeproxy_manual,\n')
        new_lines.append('            fg_color="#5C6BC0", hover_color="#3F51B5", height=26, width=90, font=("", 10)).pack(side="right")\n')
        new_lines.append('        self.lbl_hp_status = ctk.CTkLabel(hp_frame, text="", font=("", 10), text_color="#9e9e9e")\n')
        new_lines.append('        self.lbl_hp_status.pack(side="right", padx=(0, 6))\n')
        new_lines.append('        hp_token_row = ctk.CTkFrame(pxcard, fg_color="transparent")\n')
        new_lines.append('        hp_token_row.pack(fill="x", padx=12, pady=(2, 4))\n')
        new_lines.append('        ctk.CTkLabel(hp_token_row, text="Token:", font=("Consolas", 10), text_color="#9e9e9e").pack(side="left")\n')
        new_lines.append('        self.ent_hp_token = ctk.CTkEntry(hp_token_row, textvariable=self._homeproxy_token,\n')
        new_lines.append('            font=("Consolas", 10), height=24, placeholder_text="homepx..._xxx")\n')
        new_lines.append('        self.ent_hp_token.pack(side="left", fill="x", expand=True, padx=(4, 0))\n')
        
    # Change 3
    if i == 690 and 'def _on_recaptcha_mode_change' in line:
        fetch_method = """    def _fetch_homeproxy_manual(self):
        \"\"\"N\\u00fat b\\u1ea5m th\\u1ee7 c\\u00f4ng: T\\u1ea3i proxy t\\u1eeb HomeProxy API.\"\"\"
        threading.Thread(target=self._fetch_homeproxy, daemon=True).start()

    def _fetch_homeproxy(self):
        \"\"\"G\\u1ecdi HomeProxy API \\u0111\\u1ec3 l\\u1ea5y danh s\\u00e1ch proxy \\u0111ang ch\\u1ea1y.\"\"\"
        token = self._homeproxy_token.get().strip()
        if not token:
            self.after(0, lambda: self.lbl_hp_status.configure(text="\\u274c Ch\\u01b0a nh\\u1eadp token", text_color="#E57373"))
            return
        self.after(0, lambda: self.lbl_hp_status.configure(text="\\u23f3 \\u0110ang t\\u1ea3i...", text_color="#FFB74D"))
        self._log("[HomeProxy] \\u0110ang t\\u1ea3i proxy t\\u1eeb HomeProxy...")
        import requests as _rq
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        proxy_lines = []
        try:
            # First get merchant ID from /orders
            merchant_id = ""
            try:
                r0 = _rq.get("https://api.homeproxy.vn/api/v1/orders?page=1&limit=1",
                             headers=headers, timeout=15)
                if r0.status_code == 200:
                    orders_data = r0.json().get("data", [])
                    if orders_data:
                        merchant_id = str(orders_data[0].get("user", {}).get("merchant", {}).get("id", ""))
            except:
                pass
            if merchant_id:
                headers["x-merchant-id"] = merchant_id

            # Th\\u1eed endpoint ch\\u00ednh: /user-proxies
            r = _rq.get("https://api.homeproxy.vn/api/v1/user-proxies?page=1&limit=500",
                        headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
                for item in items:
                    host = item.get("host") or item.get("ip") or item.get("proxyHost", "")
                    port = item.get("port") or item.get("proxyPort", "")
                    user = item.get("username") or item.get("user") or item.get("proxyUser", "")
                    pwd = item.get("password") or item.get("pass") or item.get("proxyPass", "")
                    if host and port:
                        line = f"{host}:{port}"
                        if user: line += f":{user}:{pwd}"
                        proxy_lines.append(line)
                self._log(f"[HomeProxy] /user-proxies: {len(proxy_lines)} proxy")
            elif r.status_code == 401:
                self._log("[HomeProxy] /user-proxies tr\\u1ea3 401 \\u2014 th\\u1eed /orders...")
                # Fallback: l\\u1ea5y t\\u1eeb /orders
                r2 = _rq.get("https://api.homeproxy.vn/api/v1/orders?page=1&limit=100",
                             headers=headers, timeout=15)
                if r2.status_code == 200:
                    orders = r2.json().get("data", [])
                    for order in orders:
                        if order.get("status", {}).get("name") != "Completed":
                            continue
                        for prod in order.get("products", []):
                            user = prod.get("user", "")
                            pwd = prod.get("password", "")
                            proto = prod.get("protocolType", "HTTP")
                            if user and pwd:
                                proxy_lines.append(f"# HomeProxy order {order.get('code')} ({proto}): user={user} pass={pwd}")
                    if not proxy_lines:
                        self._log("[HomeProxy] Kh\\u00f4ng t\\u00ecm th\\u1ea5y proxy t\\u1eeb orders (thi\\u1ebfu IP:port).")
                        self._log("[HomeProxy] H\\u00e3y k\\u00edch ho\\u1ea1t quy\\u1ec1n API proxy tr\\u00ean dashboard HomeProxy.")
                else:
                    self._log(f"[HomeProxy] /orders c\\u0169ng l\\u1ed7i: {r2.status_code}")
            else:
                self._log(f"[HomeProxy] L\\u1ed7i API: {r.status_code} - {r.text[:200]}")
        except Exception as e:
            self._log(f"[HomeProxy] L\\u1ed7i k\\u1ebft n\\u1ed1i: {e}")
            self.after(0, lambda: self.lbl_hp_status.configure(text=f"\\u274c L\\u1ed7i: {e}", text_color="#E57373"))
            return
        if proxy_lines and not proxy_lines[0].startswith("#"):
            # C\\u00f3 proxy th\\u1eadt \\u2014 \\u0111i\\u1ec1n v\\u00e0o textbox
            def _update_ui():
                self.txt_proxy.delete("1.0", "end")
                self.txt_proxy.insert("1.0", "\\n".join(proxy_lines))
                self.proxy_pool.load(proxy_lines)
                self._update_proxy_stats()
                self.lbl_hp_status.configure(
                    text=f"\\u2705 {len(proxy_lines)} proxy", text_color="#66BB6A")
            self.after(0, _update_ui)
            self._log(f"[HomeProxy] \\u0110\\u00e3 t\\u1ea3i {len(proxy_lines)} proxy th\\u00e0nh c\\u00f4ng.")
        else:
            msg = f"\\u26a0\\ufe0f 0 proxy (c\\u1ea7n k\\u00edch ho\\u1ea1t API)" if not proxy_lines else f"\\u26a0\\ufe0f Kh\\u00f4ng c\\u00f3 IP:port"
            self.after(0, lambda: self.lbl_hp_status.configure(text=msg, text_color="#FFB74D"))

"""
        new_lines.insert(-1, fetch_method) # Insert before the current line
        
    # Change 4
    if i == 2489 and 'try:' in line:
        new_lines.pop()
        fetch_run = """            # Auto HomeProxy: t\\u1ea3i proxy t\\u1ef1 \\u0111\\u1ed9ng n\\u1ebfu b\\u1eadt
            if self._auto_homeproxy.get() and self._homeproxy_token.get().strip():
                self._fetch_homeproxy()
            else:
                try:
                    if self._cached_px_lines:
                        self.proxy_pool.load(self._cached_px_lines)
                except Exception:
                    pass
"""
        new_lines.append(fetch_run)
        skip_until = 2495 # skip up to except Exception: pass
        
    # Change 5
    if i == 6461 and '"disable_proxy"' in line:
        new_lines.append('                "auto_homeproxy": self._auto_homeproxy.get(),\n')
        new_lines.append('                "homeproxy_token": self._homeproxy_token.get().strip(),\n')
        
    # Change 6
    if i == 5963 and 'try:' in line:
        new_lines.pop()
        fetch_run_sv = """            # Auto HomeProxy
            if self._auto_homeproxy.get() and self._homeproxy_token.get().strip():
                self._fetch_homeproxy()
            else:
                try:
                    if _cached_px_lines: self.proxy_pool.load(_cached_px_lines)
                except Exception: pass
"""
        new_lines.append(fetch_run_sv)
        skip_until = 5967 # skip up to except Exception: pass

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
    
print("Patch applied successfully.")
