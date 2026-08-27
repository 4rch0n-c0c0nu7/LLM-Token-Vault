import tkinter as tk
import json
import os
import time
import threading
import urllib.request
import urllib.error
from lumi_vault import secure_load_keys, secure_save_keys

KEYS_FILE = os.path.expanduser("~/lumi_keys.json")
ROUTING_FILE = os.path.expanduser("~/lumi_routing.json")
# Use fast RAM disk on Linux, fallback to home directory for Windows/Mac users
CACHE_FILE = '/dev/shm/token_cache.json' if os.path.exists('/dev/shm') else os.path.expanduser('~/.lumi_token_cache.json')

BG_COLOR = "#0A0A10"
PANEL_COLOR = "#14141E"
ACCENT_COLOR = "#00FFAA"
TEXT_MAIN = "#E0E0E0"
TEXT_DIM = "#606070"
WARN_COLOR = "#FF3366"
USED_GREY = "#2A2A36"
FONT_TITLE = ("Consolas", 13, "bold")
FONT_BODY = ("Consolas", 9)
FONT_SMALL = ("Consolas", 8)

class TokenDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Lumi Tactical Multi-Provider Uplink & Token HUD")
        self.root.geometry("640x700")
        self.root.minsize(500, 450)
        self.root.configure(bg=BG_COLOR)
        
        self.routing_mode = tk.StringVar(value="LOCAL")
        self.provider_cards = {}
        
        self.seed_config_files()
        self.init_ui()
        self.update_clock()
        self.poll_token_cache()

    def seed_config_files(self):
        try:
            os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
            if not os.path.exists(KEYS_FILE):
                initial_keys = {
                    "GROQ_API_KEY": "", 
                    "GOOGLE_API_KEY": "", 
                    "OPENROUTER_API_KEY": "", 
                    "OPENAI_API_KEY": "",
                    "CEREBRAS_API_KEY": "",
                    "MISTRAL_API_KEY": ""
                }
                secure_save_keys(initial_keys)
            
            if not os.path.exists(ROUTING_FILE):
                with open(ROUTING_FILE, "w") as f:
                    json.dump({"default_mode": "LOCAL", "strategy": "manual"}, f, indent=4)
            else:
                with open(ROUTING_FILE, "r") as f:
                    data = json.load(f)
                    self.routing_mode.set(data.get("default_mode", "LOCAL"))
        except Exception as e:
            print(f"[!] Config initialization warning: {e}")

    def save_routing(self):
        mode = self.routing_mode.get()
        strategy = "auto" if mode == "AUTO" else "manual"
        try:
            with open(ROUTING_FILE, "w") as f:
                json.dump({"default_mode": mode, "strategy": strategy}, f, indent=4)
            self.log_output(f"Routing updated: {mode}")
        except Exception as e:
            print(f"[!] Failed to save routing: {e}")

    def load_keys(self):
        return secure_load_keys()

    def init_ui(self):
        # Main scrollable canvas container to prevent cutoff on smaller screens
        container = tk.Frame(self.root, bg=BG_COLOR)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        
        self.scrollable_frame = tk.Frame(canvas, bg=BG_COLOR)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scrolling across platforms
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Title Header
        title_frame = tk.Frame(self.scrollable_frame, bg=BG_COLOR)
        title_frame.pack(fill="x", pady=6)
        tk.Label(title_frame, text="LUMI TACTICAL COMMAND & TOKEN HUD", font=FONT_TITLE, bg=BG_COLOR, fg=ACCENT_COLOR).pack()
        self.clock_label = tk.Label(title_frame, text="00:00:00", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_DIM)
        self.clock_label.pack()

        # Primary Routing Frame
        route_frame = tk.LabelFrame(self.scrollable_frame, text=" PRIMARY ROUTING & AI SELECTION ", font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, bd=1)
        route_frame.pack(fill="x", padx=15, pady=3, ipady=2)

        modes = [
            ("LOCAL (Ollama)", "LOCAL"), 
            ("GROQ", "GROQ"), 
            ("GOOGLE", "GOOGLE"), 
            ("OPENROUTER", "OPENROUTER"), 
            ("OPENAI", "OPENAI"),
            ("CEREBRAS", "CEREBRAS"),
            ("MISTRAL", "MISTRAL"),
            ("AUTO ROTATE", "AUTO")
        ]
        
        grid_frame = tk.Frame(route_frame, bg=PANEL_COLOR)
        grid_frame.pack(expand=True, pady=2)
        
        for i, (text, mode) in enumerate(modes):
            tk.Radiobutton(
                grid_frame, text=text, variable=self.routing_mode, value=mode, 
                font=FONT_SMALL, bg=PANEL_COLOR, fg=TEXT_MAIN, 
                selectcolor=BG_COLOR, activebackground=PANEL_COLOR, activeforeground=ACCENT_COLOR,
                command=self.save_routing
            ).grid(row=i//4, column=i%4, sticky="w", padx=8, pady=1)

        # Provider Cards Status Frame
        status_frame = tk.LabelFrame(self.scrollable_frame, text=" LIVE API KEY STATUS & TOKEN METRICS ", font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, bd=1)
        status_frame.pack(fill="x", padx=15, pady=3, ipadx=5, ipady=2)

        self.cards_container = tk.Frame(status_frame, bg=PANEL_COLOR)
        self.cards_container.pack(fill="x", expand=True, padx=8, pady=2)

        self.build_provider_cards()

        # Control Buttons Frame
        btn_frame = tk.Frame(self.scrollable_frame, bg=BG_COLOR)
        btn_frame.pack(fill="x", padx=15, pady=4)
        
        tk.Button(btn_frame, text="Manage API Keys", font=FONT_BODY, bg=PANEL_COLOR, fg=TEXT_MAIN, relief="flat", command=self.open_keys_editor).pack(side="left", padx=4, fill="x", expand=True)
        tk.Button(btn_frame, text="⚡ Ping All Uplinks", font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, relief="flat", command=self.ping_all_providers).pack(side="left", padx=4, fill="x", expand=True)

        # Telemetry Log Section
        log_header_frame = tk.Frame(self.scrollable_frame, bg=BG_COLOR)
        log_header_frame.pack(fill="x", padx=15, pady=(2, 0))
        tk.Label(log_header_frame, text="UPLINK TELEMETRY LOG", font=FONT_SMALL, bg=BG_COLOR, fg=ACCENT_COLOR).pack(side="left")
        tk.Button(log_header_frame, text="📋 Copy Log", font=("Consolas", 7), bg=PANEL_COLOR, fg=TEXT_MAIN, bd=0, relief="flat", command=self.copy_log_text).pack(side="right")

        log_frame = tk.Frame(self.scrollable_frame, bg=PANEL_COLOR, bd=1, relief="solid")
        log_frame.pack(fill="x", padx=15, pady=(2, 10))
        
        self.log_box = tk.Text(log_frame, height=4, bg=BG_COLOR, fg=TEXT_MAIN, font=("Consolas", 8), bd=0, highlightthickness=0, exportselection=True)
        self.log_box.pack(fill="both", expand=True, padx=6, pady=4)
        self.log_box.insert(tk.END, "Dashboard initialized. Vault encryption active.\n")

    def copy_log_text(self):
        try:
            log_content = self.log_box.get("1.0", tk.END).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(log_content)
            self.log_output("Telemetry log copied to clipboard.")
        except Exception as e:
            print(f"[!] Copy error: {e}")

    def log_output(self, message):
        self.log_box.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_box.see(tk.END)

    def build_provider_cards(self):
        for widget in self.cards_container.winfo_children():
            widget.destroy()

        providers = [
            ("Groq", "GROQ_API_KEY"),
            ("Google Gemini", "GOOGLE_API_KEY"),
            ("OpenRouter", "OPENROUTER_API_KEY"),
            ("OpenAI", "OPENAI_API_KEY"),
            ("Cerebras", "CEREBRAS_API_KEY"),
            ("Mistral AI", "MISTRAL_API_KEY")
        ]

        keys = self.load_keys()

        for name, key_id in providers:
            has_key = bool(keys.get(key_id, "").strip())
            
            card = tk.Frame(self.cards_container, bg=BG_COLOR, bd=1, relief="solid")
            card.pack(fill="x", pady=1, ipady=1, ipadx=3)

            top_row = tk.Frame(card, bg=BG_COLOR)
            top_row.pack(fill="x", padx=5, pady=1)

            lbl_name = tk.Label(top_row, text=f"■ {name}", font=FONT_SMALL, bg=BG_COLOR, fg=ACCENT_COLOR if has_key else TEXT_DIM)
            lbl_name.pack(side="left")

            lbl_state = tk.Label(top_row, text="CONFIGURED" if has_key else "NO KEY FOUND", font=FONT_SMALL, bg=BG_COLOR, fg=ACCENT_COLOR if has_key else WARN_COLOR)
            lbl_state.pack(side="right")

            canvas = tk.Canvas(card, height=8, bg=PANEL_COLOR, highlightthickness=0)
            canvas.pack(fill="x", padx=5, pady=1)

            metrics_row = tk.Frame(card, bg=BG_COLOR)
            metrics_row.pack(fill="x", padx=5, pady=1)

            lbl_metrics = tk.Label(metrics_row, text="Used: 0 / Limit: 0 | Left: 0 | Renews in: --", font=("Consolas", 7), bg=BG_COLOR, fg=TEXT_MAIN)
            lbl_metrics.pack(side="left")

            self.provider_cards[key_id] = {
                "canvas": canvas,
                "metrics": lbl_metrics,
                "state": lbl_state
            }
            self.draw_progress_bar(canvas, 0, 15000, active=False)

    def draw_progress_bar(self, canvas, used, limit, active=True):
        canvas.delete("all")
        w = canvas.winfo_width()
        if w <= 1: 
            w = 550
        h = 8
        
        if not active:
            canvas.create_rectangle(0, 0, w, h, fill=USED_GREY, outline="")
            for x_pos in range(-h, w + h, 8):
                canvas.create_line(x_pos, h, x_pos + h, 0, fill=TEXT_DIM, width=1)
            return

        if limit <= 0:
            limit = 1
        
        used_clamped = max(0, min(used, limit))
        used_width = int(w * (used_clamped / limit))
        
        canvas.create_rectangle(0, 0, w, h, fill=ACCENT_COLOR, outline="")
        if used_width > 0:
            canvas.create_rectangle(0, 0, used_width, h, fill=USED_GREY, outline="")
            for x_pos in range(-h, used_width + h, 8):
                canvas.create_line(x_pos, h, x_pos + h, 0, fill=TEXT_DIM, width=1)

    def update_clock(self):
        t = time.strftime("%Y-%m-%d %H:%M:%S")
        self.clock_label.config(text=f"SYS TIME: {t}")
        self.root.after(1000, self.update_clock)

    def poll_token_cache(self):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    rem = data.get("remaining")
                    lim = data.get("limit")
                    if rem is not None and lim is not None:
                        self.update_provider_ui("GROQ_API_KEY", rem, lim, "Live")
        except Exception:
            pass
        self.root.after(5000, self.poll_token_cache)

    def ping_all_providers(self):
        def _ping_worker():
            keys = self.load_keys()
            
            self.root.after(0, lambda: self.log_output("--- Starting Ping Cycle for All 6 Active Uplinks ---"))
            success_count = 0

            # 1. Groq Ping 
            groq_key = keys.get("GROQ_API_KEY", "").strip()
            if groq_key:
                ping_success = False
                last_err = ""
                for gmodel in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "groq/compound"]:
                    try:
                        req_data = json.dumps({"model": gmodel, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode('utf-8')
                        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {groq_key}', 'User-Agent': 'Mozilla/5.0'}, method='POST')
                        with urllib.request.urlopen(req, timeout=8) as res:
                            rem = int(res.headers.get('x-ratelimit-remaining-tokens') or 14500)
                            lim = int(res.headers.get('x-ratelimit-limit-tokens') or 15000)
                            self.root.after(0, lambda r=rem, l=lim: self.update_provider_ui("GROQ_API_KEY", r, l, "Live"))
                            self.root.after(0, lambda m=gmodel: self.log_output(f"[Groq] SUCCESS ({m})"))
                            success_count += 1
                            ping_success = True
                            break
                    except urllib.error.HTTPError as he:
                        try:
                            err_data = json.loads(he.read().decode('utf-8'))
                            err_msg = err_data.get('error', {}).get('message', 'Unknown Error')
                            last_err = f"HTTP {he.code}: {err_msg[:45]}..."
                        except:
                            last_err = f"HTTP {he.code}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
                if not ping_success:
                    self.root.after(0, lambda: self.mark_provider_error("GROQ_API_KEY"))
                    self.root.after(0, lambda err=last_err: self.log_output(f"[Groq] Ping FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[Groq] Skipped (No key)"))

            # 2. Google Gemini Ping
            google_key = keys.get("GOOGLE_API_KEY", "").strip()
            if google_key:
                ping_success = False
                last_err = ""
                for gmodel in ["gemini-2.0-flash-exp", "gemini-2.0-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-1.5-flash"]:
                    try:
                        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                        req_data = json.dumps({"model": gmodel, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode('utf-8')
                        req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {google_key}', 'User-Agent': 'Mozilla/5.0'}, method='POST')
                        with urllib.request.urlopen(req, timeout=8) as res:
                            self.root.after(0, lambda: self.update_provider_ui("GOOGLE_API_KEY", 14500, 15000, "Active"))
                            self.root.after(0, lambda m=gmodel: self.log_output(f"[Google] SUCCESS ({m})"))
                            success_count += 1
                            ping_success = True
                            break
                    except urllib.error.HTTPError as he:
                        try:
                            raw_err = he.read().decode('utf-8')
                            err_json = json.loads(raw_err)
                            if isinstance(err_json, list):
                                last_err = f"HTTP {he.code}: {err_json[0]['error']['message'][:45]}..."
                            else:
                                last_err = f"HTTP {he.code}: {err_json['error']['message'][:45]}..."
                        except:
                            last_err = f"HTTP {he.code}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
                if not ping_success:
                    self.root.after(0, lambda: self.mark_provider_error("GOOGLE_API_KEY"))
                    self.root.after(0, lambda err=last_err: self.log_output(f"[Google] Ping FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[Google] Skipped (No key)"))

            # 3. OpenRouter Ping
            or_key = keys.get("OPENROUTER_API_KEY", "").strip()
            if or_key:
                try:
                    req_data = json.dumps({"model": "openrouter/auto", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode('utf-8')
                    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {or_key}', 'User-Agent': 'Mozilla/5.0'}, method='POST')
                    with urllib.request.urlopen(req, timeout=8) as res:
                        self.root.after(0, lambda: self.update_provider_ui("OPENROUTER_API_KEY", 14500, 15000, "60s"))
                        self.root.after(0, lambda: self.log_output("[OpenRouter] SUCCESS"))
                        success_count += 1
                except Exception as e:
                    self.root.after(0, lambda: self.mark_provider_error("OPENROUTER_API_KEY"))
                    self.root.after(0, lambda err=str(e): self.log_output(f"[OpenRouter] Ping FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[OpenRouter] Skipped (No key)"))

            # 4. OpenAI Ping
            openai_key = keys.get("OPENAI_API_KEY", "").strip()
            if openai_key:
                try:
                    req_data = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode('utf-8')
                    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {openai_key}', 'User-Agent': 'Mozilla/5.0'}, method='POST')
                    with urllib.request.urlopen(req, timeout=8) as res:
                        self.root.after(0, lambda: self.update_provider_ui("OPENAI_API_KEY", 14500, 15000, "Live"))
                        self.root.after(0, lambda: self.log_output("[OpenAI] SUCCESS"))
                        success_count += 1
                except urllib.error.HTTPError as he:
                    err_msg = f"HTTP {he.code}"
                    if he.code == 429:
                        err_msg += " (Quota/Billing)"
                    self.root.after(0, lambda: self.mark_provider_error("OPENAI_API_KEY"))
                    self.root.after(0, lambda err=err_msg: self.log_output(f"[OpenAI] Ping FAILED: {err}"))
                except Exception as e:
                    self.root.after(0, lambda: self.mark_provider_error("OPENAI_API_KEY"))
                    self.root.after(0, lambda err=str(e): self.log_output(f"[OpenAI] Ping FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[OpenAI] Skipped (No key)"))

            # 5. Cerebras Ping
            cerebras_key = keys.get("CEREBRAS_API_KEY", "").strip()
            if cerebras_key:
                try:
                    url = "https://api.cerebras.ai/v1/models"
                    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {cerebras_key}', 'User-Agent': 'Mozilla/5.0'}, method='GET')
                    with urllib.request.urlopen(req, timeout=8) as res:
                        self.root.after(0, lambda: self.update_provider_ui("CEREBRAS_API_KEY", 995000, 1000000, "Daily"))
                        self.root.after(0, lambda: self.log_output("[Cerebras] SUCCESS (Native Auth)"))
                        success_count += 1
                except urllib.error.HTTPError as he:
                    err_msg = f"HTTP {he.code}"
                    self.root.after(0, lambda: self.mark_provider_error("CEREBRAS_API_KEY"))
                    self.root.after(0, lambda err=err_msg: self.log_output(f"[Cerebras] FAILED: {err}"))
                except Exception as e:
                    self.root.after(0, lambda: self.mark_provider_error("CEREBRAS_API_KEY"))
                    self.root.after(0, lambda err=str(e): self.log_output(f"[Cerebras] FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[Cerebras] Skipped (No key)"))

            # 6. Mistral AI Ping 
            mistral_key = keys.get("MISTRAL_API_KEY", "").strip()
            if mistral_key:
                try:
                    req_data = json.dumps({"model": "mistral-small-latest", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode('utf-8')
                    req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=req_data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {mistral_key}', 'User-Agent': 'Mozilla/5.0'}, method='POST')
                    with urllib.request.urlopen(req, timeout=8) as res:
                        self.root.after(0, lambda: self.update_provider_ui("MISTRAL_API_KEY", 14500, 15000, "Active"))
                        self.root.after(0, lambda: self.log_output("[Mistral] SUCCESS"))
                        success_count += 1
                except urllib.error.HTTPError as he:
                    err_msg = f"HTTP {he.code}"
                    self.root.after(0, lambda: self.mark_provider_error("MISTRAL_API_KEY"))
                    self.root.after(0, lambda err=err_msg: self.log_output(f"[Mistral] FAILED: {err}"))
                except Exception as e:
                    self.root.after(0, lambda: self.mark_provider_error("MISTRAL_API_KEY"))
                    self.root.after(0, lambda err=str(e): self.log_output(f"[Mistral] FAILED: {err}"))
            else:
                self.root.after(0, lambda: self.log_output("[Mistral] Skipped (No key)"))

            self.root.after(0, lambda: self.log_output(f"Ping cycle finished. {success_count}/6 uplink(s) active."))

        threading.Thread(target=_ping_worker, daemon=True).start()

    def update_provider_ui(self, key_id, rem, lim, reset_str):
        if key_id not in self.provider_cards:
            return
        card = self.provider_cards[key_id]
        used = lim - rem
        
        self.draw_progress_bar(card["canvas"], used, lim, active=True)
        card["metrics"].config(text=f"Used: {used:,} / Limit: {lim:,} | Left: {rem:,} | Renews: {reset_str}")
        card["state"].config(text="ACTIVE", fg=ACCENT_COLOR)

    def mark_provider_error(self, key_id):
        if key_id not in self.provider_cards:
            return
        card = self.provider_cards[key_id]
        self.draw_progress_bar(card["canvas"], 0, 15000, active=False)
        card["metrics"].config(text="Status: OFFLINE / ERROR")
        card["state"].config(text="ERROR", fg=WARN_COLOR)

    def open_keys_editor(self):
        popup = tk.Toplevel(self.root)
        popup.title("API Key Configuration")
        popup.geometry("500x440")
        popup.configure(bg=BG_COLOR)
        popup.resizable(False, False)
        
        tk.Label(popup, text="UPLINK CREDENTIALS", font=FONT_TITLE, bg=BG_COLOR, fg=ACCENT_COLOR).pack(pady=8)
        
        current_keys = self.load_keys()
                
        entries = {}
        providers = [
            ("GROQ_API_KEY", "Groq Key:"), 
            ("GOOGLE_API_KEY", "Google Gemini:"), 
            ("OPENROUTER_API_KEY", "OpenRouter:"),
            ("OPENAI_API_KEY", "OpenAI Key:"),
            ("CEREBRAS_API_KEY", "Cerebras Key:"),
            ("MISTRAL_API_KEY", "Mistral Key:")
        ]
                     
        form_frame = tk.Frame(popup, bg=BG_COLOR)
        form_frame.pack(fill="x", padx=15, pady=3)
        
        for k_id, label in providers:
            row = tk.Frame(form_frame, bg=BG_COLOR)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=15, anchor="e", font=FONT_BODY, bg=BG_COLOR, fg=TEXT_MAIN).pack(side="left")
            ent = tk.Entry(row, font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, insertbackground=TEXT_MAIN, show="*")
            ent.pack(side="left", fill="x", expand=True, padx=4)
            ent.insert(0, current_keys.get(k_id, ""))
            entries[k_id] = ent
            
        def save_keys():
            for k_id, ent in entries.items():
                current_keys[k_id] = ent.get().strip()
            try:
                success = secure_save_keys(current_keys)
                if success:
                    self.log_output("Encrypted API Credentials saved successfully.")
                    self.build_provider_cards()
                    popup.destroy()
                else:
                    self.log_output("[!] Vault encryption save failed.")
            except Exception as e:
                self.log_output(f"[!] Failed to save keys: {e}")
                
        tk.Button(popup, text="SAVE SECURE CREDENTIALS", font=FONT_BODY, bg=PANEL_COLOR, fg=TEXT_MAIN, relief="flat", command=save_keys).pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    app = TokenDashboard(root)
    root.mainloop()
