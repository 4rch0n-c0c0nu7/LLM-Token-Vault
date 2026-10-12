"""
Lumi Token Dashboard v2 — routing, API keys, and *real* uplink health/usage.

What's real now:
  - Status comes from actual chat calls on the configured model (Lumi's own calls, or TEST ALL),
    so a retired model shows up as FAILING instead of "SUCCESS".
  - Usage = tokens/requests Lumi actually spent today (~/.lumi_usage.json) plus the provider's
    own rate-limit headers when it sends them (Groq, Cerebras, Mistral). Gemini sends none.
  - Model per provider is selectable from the provider's live model list.
  - Keys can be exported/imported with a passphrase (the vault itself only opens on this machine).
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, simpledialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lumi_vault import secure_load_keys, secure_save_keys  # noqa: E402
import lumi_uplinks as up  # noqa: E402

BG_COLOR = "#0A0A10"
PANEL_COLOR = "#14141E"
ACCENT_COLOR = "#00FFAA"
TEXT_MAIN = "#E0E0E0"
TEXT_DIM = "#8A8A9C"
WARN_COLOR = "#FF3366"
CAUTION_COLOR = "#FFB020"
USED_GREY = "#2A2A36"
MONO = "DejaVu Sans Mono"  # Consolas isn't on Linux; Tk was substituting a tiny fallback
FONT_TITLE = (MONO, 17, "bold")
FONT_BODY = (MONO, 13)
FONT_SMALL = (MONO, 12)
FONT_TINY = (MONO, 11)

ROUTE_LABELS = [("LOCAL (Ollama)", "LOCAL"), ("GROQ", "GROQ"), ("GOOGLE", "GOOGLE"), ("CEREBRAS", "CEREBRAS"),
                ("OPENROUTER", "OPENROUTER"), ("MISTRAL", "MISTRAL"), ("OPENAI", "OPENAI"), ("AUTO ROTATE", "AUTO")]


def key_for(keys, p):
    k = keys.get(p["key_env"], "").strip()
    if not k and p["id"] == "GOOGLE":
        k = keys.get("GEMINI_API_KEY", "").strip()
    return k


def ago(ts):
    if not ts:
        return "never"
    s = int(time.time() - ts)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return time.strftime("%b %d", time.localtime(ts))


class TokenDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Lumi Uplink & Token HUD")
        self.root.geometry("900x940")
        self.root.minsize(640, 520)
        self.root.configure(bg=BG_COLOR)

        self.routing_mode = tk.StringVar(value=up.get_route())
        self.cards = {}
        self.or_credit = None
        self.busy = False
        self.ui_q = queue.Queue()  # worker threads hand UI updates to the Tk thread through this

        self.seed_config_files()
        self.init_ui()
        self.update_clock()
        self.refresh_cards()
        self.drain_ui_queue()

    # ---------- setup ----------

    def seed_config_files(self):
        try:
            if not os.path.exists(up.ROUTING_FILE):
                up.set_route("LOCAL")
            if not secure_load_keys() and not os.path.exists(os.path.expanduser("~/lumi_keys.json")):
                secure_save_keys({p["key_env"]: "" for p in up.DEFAULT_PROVIDERS})
        except Exception as e:
            print(f"[!] Config initialization warning: {e}")

    def save_routing(self):
        mode = self.routing_mode.get()
        try:
            up.set_route(mode)
            self.log_output(f"Routing set to {mode}. Lumi picks this up on her next message.")
        except Exception as e:
            self.log_output(f"[!] Failed to save routing: {e}")
        self.refresh_cards(reschedule=False)

    # ---------- layout ----------

    def init_ui(self):
        container = tk.Frame(self.root, bg=BG_COLOR)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg=BG_COLOR)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel: Linux/X11 sends Button-4/5, Windows/macOS send <MouseWheel>.
        def wheel(event):
            if event.num == 4:
                canvas.yview_scroll(-2, "units")
            elif event.num == 5:
                canvas.yview_scroll(2, "units")
            elif event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_wheel(_):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.bind_all(seq, wheel)

        def unbind_wheel(_):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.unbind_all(seq)

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)

        sf = self.scrollable_frame
        title = tk.Frame(sf, bg=BG_COLOR)
        title.pack(fill="x", pady=6)
        tk.Label(title, text="LUMI UPLINK & TOKEN HUD", font=FONT_TITLE, bg=BG_COLOR, fg=ACCENT_COLOR).pack()
        self.clock_label = tk.Label(title, text="", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_DIM)
        self.clock_label.pack()

        route = tk.LabelFrame(sf, text=" PRIMARY ROUTING ", font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, bd=1)
        route.pack(fill="x", padx=15, pady=3, ipady=2)
        grid = tk.Frame(route, bg=PANEL_COLOR)
        grid.pack(expand=True, pady=2)
        for i, (text, mode) in enumerate(ROUTE_LABELS):
            tk.Radiobutton(grid, text=text, variable=self.routing_mode, value=mode, font=FONT_SMALL,
                           bg=PANEL_COLOR, fg=TEXT_MAIN, selectcolor=BG_COLOR, activebackground=PANEL_COLOR,
                           activeforeground=ACCENT_COLOR, command=self.save_routing
                           ).grid(row=i // 4, column=i % 4, sticky="w", padx=8, pady=1)
        self.route_hint = tk.Label(route, text="", font=FONT_TINY, bg=PANEL_COLOR, fg=TEXT_DIM, justify="left")
        self.route_hint.pack(anchor="w", padx=8)
        self.last_answer = tk.Label(route, text="", font=FONT_TINY, bg=PANEL_COLOR, fg=TEXT_MAIN)
        self.last_answer.pack(anchor="w", padx=8, pady=(0, 2))

        status = tk.LabelFrame(sf, text=" UPLINKS · HEALTH · USAGE TODAY ", font=FONT_BODY, bg=PANEL_COLOR,
                               fg=ACCENT_COLOR, bd=1)
        status.pack(fill="x", padx=15, pady=3, ipadx=5, ipady=2)
        self.cards_container = tk.Frame(status, bg=PANEL_COLOR)
        self.cards_container.pack(fill="x", expand=True, padx=8, pady=2)
        self.build_provider_cards()

        btns = tk.Frame(sf, bg=BG_COLOR)
        btns.pack(fill="x", padx=15, pady=4)
        for text, fg, cmd in [("Manage API Keys", TEXT_MAIN, self.open_keys_editor),
                              ("⚡ Test All Uplinks", ACCENT_COLOR, self.test_all),
                              ("Export Keys…", TEXT_MAIN, self.export_keys),
                              ("Import Keys…", TEXT_MAIN, self.import_keys)]:
            tk.Button(btns, text=text, font=FONT_BODY, bg=PANEL_COLOR, fg=fg, relief="flat",
                      command=cmd).pack(side="left", padx=3, fill="x", expand=True)

        lh = tk.Frame(sf, bg=BG_COLOR)
        lh.pack(fill="x", padx=15, pady=(2, 0))
        tk.Label(lh, text="UPLINK TELEMETRY LOG", font=FONT_SMALL, bg=BG_COLOR, fg=ACCENT_COLOR).pack(side="left")
        tk.Button(lh, text="📋 Copy Log", font=FONT_TINY, bg=PANEL_COLOR, fg=TEXT_MAIN, bd=0, relief="flat",
                  command=self.copy_log_text).pack(side="right")
        lf = tk.Frame(sf, bg=PANEL_COLOR, bd=1, relief="solid")
        lf.pack(fill="x", padx=15, pady=(2, 10))
        self.log_box = tk.Text(lf, height=7, bg=BG_COLOR, fg=TEXT_MAIN, font=FONT_TINY, bd=0,
                               highlightthickness=0, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=4)
        self.log_output("Dashboard v2 ready. Status shows real calls; press TEST ALL for a fresh check.")

    def build_provider_cards(self):
        for w in self.cards_container.winfo_children():
            w.destroy()
        self.cards = {}
        for p in up.load_providers():
            card = tk.Frame(self.cards_container, bg=BG_COLOR, bd=1, relief="solid")
            card.pack(fill="x", pady=2, ipady=1, ipadx=3)

            top = tk.Frame(card, bg=BG_COLOR)
            top.pack(fill="x", padx=5, pady=1)
            name = tk.Label(top, text=f"■ {p['name']}", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_DIM)
            name.pack(side="left")
            state = tk.Label(top, text="", font=FONT_SMALL, bg=BG_COLOR, fg=TEXT_DIM)
            state.pack(side="right")

            mrow = tk.Frame(card, bg=BG_COLOR)
            mrow.pack(fill="x", padx=5)
            model = tk.Label(mrow, text="", font=FONT_TINY, bg=BG_COLOR, fg=TEXT_MAIN)
            model.pack(side="left")
            tk.Button(mrow, text="change model", font=FONT_TINY, bg=PANEL_COLOR, fg=TEXT_MAIN, bd=0,
                      relief="flat", command=lambda pid=p["id"]: self.open_model_picker(pid)).pack(side="right")
            tk.Button(mrow, text="test", font=FONT_TINY, bg=PANEL_COLOR, fg=ACCENT_COLOR, bd=0,
                      relief="flat", command=lambda pid=p["id"]: self.test_some([pid])).pack(side="right", padx=4)

            meters = tk.Frame(card, bg=BG_COLOR)
            meters.pack(fill="x", padx=5, pady=1)
            usage = tk.Label(card, text="", font=FONT_TINY, bg=BG_COLOR, fg=TEXT_MAIN, anchor="w", justify="left")
            usage.pack(fill="x", padx=5)
            err = tk.Label(card, text="", font=FONT_TINY, bg=BG_COLOR, fg=WARN_COLOR, anchor="w", justify="left",
                           wraplength=780)
            err.pack(fill="x", padx=5)
            self.cards[p["id"]] = {"name": name, "state": state, "model": model, "meters": meters,
                                   "usage": usage, "err": err, "meter_sig": None}

    # ---------- live refresh ----------

    def refresh_cards(self, reschedule=True):
        try:
            keys = secure_load_keys()
            usage = up.load_usage()
            route = up.get_route()
            if self.routing_mode.get() != route:
                self.routing_mode.set(route)
            for p in up.load_providers():
                c = self.cards.get(p["id"])
                if c:
                    self._paint_card(c, p, bool(key_for(keys, p)), usage.get(p["id"], {}), route)
            self._paint_routing(route, usage)
        except Exception as e:
            self.log_output(f"[!] Refresh error: {e}")
        if reschedule:
            self.root.after(5000, self.refresh_cards)

    def _paint_routing(self, route, usage):
        if route == "LOCAL":
            hint = "Lumi stays on local Ollama (offline, private, slower)."
        elif route == "AUTO":
            hint = "Lumi starts with whichever uplink answered last, rotates on failure, then local Ollama."
        else:
            hint = f"Lumi tries {route} first, then the other uplinks, then local Ollama."
        self.route_hint.config(text=hint)
        last = up.get_last_active()
        oks = [(e.get("last_ok", 0), pid) for pid, e in usage.items() if e.get("last_ok")]
        when = ago(max(oks)[0]) if oks else "—"
        self.last_answer.config(text=f"Last cloud answer: {last or '—'} ({when})")

    def _paint_card(self, c, p, has_key, e, route):
        last_ok, last_err = e.get("last_ok", 0), e.get("last_error", 0)
        msg = e.get("last_error_msg", "")
        if not has_key:
            state, color = "NO KEY", WARN_COLOR
        elif last_err and last_err > last_ok:
            retired = any(w in msg.lower() for w in ("decommission", "does not exist", "not found", "no longer"))
            state, color = ("MODEL RETIRED?" if retired else "FAILING"), WARN_COLOR
        elif last_ok:
            state, color = "READY", ACCENT_COLOR
        else:
            state, color = "UNTESTED", CAUTION_COLOR
        if route == p["id"]:
            state = "▶ PRIMARY · " + state
        c["state"].config(text=state, fg=color)
        c["name"].config(fg=ACCENT_COLOR if has_key else TEXT_DIM)
        c["model"].config(text=f"model: {p['model']}")

        line = (f"Today: {e.get('requests_today', 0)} calls · {e.get('tokens_today', 0):,} tokens"
                f" · {e.get('errors_today', 0)} errors   |   last OK {ago(last_ok)}")
        if p["id"] == "OPENROUTER" and self.or_credit:
            cr = self.or_credit
            line += f"\nAccount spend: ${float(cr.get('usage') or 0):.2f}"
            if cr.get("limit") is not None:
                line += f" of ${float(cr['limit']):.2f}"
            if cr.get("is_free_tier"):
                line += " (free tier)"
        if p["id"] == "GOOGLE":
            line += "\nGemini reports no quota headers; counts above are Lumi's own."
        c["usage"].config(text=line)
        c["err"].config(text=f"last error ({ago(last_err)}): {msg}" if last_err and last_err > last_ok else "")

        meters = up.ratelimit_meters(e.get("ratelimits", {}), p["id"])
        sig = (tuple(meters), int(e.get("ratelimits_at", 0)) // 60)
        if sig != c["meter_sig"]:
            c["meter_sig"] = sig
            for w in c["meters"].winfo_children():
                w.destroy()
            for label, rem, lim in meters:
                self._meter(c["meters"], label, rem, lim, e.get("ratelimits_at"))

    def _meter(self, parent, label, rem, lim, at):
        row = tk.Frame(parent, bg=BG_COLOR)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=f"{label}: {rem:,} / {lim:,} left  ({ago(at)})", font=FONT_TINY, bg=BG_COLOR,
                 fg=TEXT_MAIN, width=46, anchor="w").pack(side="left")
        bar = tk.Canvas(row, height=12, bg=PANEL_COLOR, highlightthickness=0)
        bar.pack(side="left", fill="x", expand=True, padx=(4, 0))
        frac = max(0.0, min(1.0, rem / lim)) if lim > 0 else 0.0
        color = ACCENT_COLOR if frac > 0.25 else (CAUTION_COLOR if frac > 0.05 else WARN_COLOR)

        def draw(_=None):
            bar.delete("all")
            w = max(bar.winfo_width(), 10)
            bar.create_rectangle(0, 0, w, 12, fill=USED_GREY, outline="")
            bar.create_rectangle(0, 0, int(w * frac), 12, fill=color, outline="")
        bar.bind("<Configure>", draw)

    # ---------- actions ----------

    def test_all(self):
        self.test_some([p["id"] for p in up.load_providers()])

    def test_some(self, pids):
        if self.busy:
            self.log_output("A test is already running…")
            return
        self.busy = True

        def worker():
            keys = secure_load_keys()
            ok_count, tried = 0, 0
            for p in up.load_providers():
                if p["id"] not in pids:
                    continue
                k = key_for(keys, p)
                if not k:
                    self.ui(lambda n=p["name"]: self.log_output(f"[{n}] skipped (no key)"))
                    continue
                tried += 1
                ok, msg = up.test_provider(p, k)
                ok_count += ok
                self.ui(lambda n=p["name"], ok=ok, msg=msg:
                                self.log_output(f"[{n}] {'OK' if ok else 'FAILED'} — {msg}"))
                if p["id"] == "OPENROUTER":
                    try:
                        self.or_credit = up.openrouter_credit(k)
                    except Exception:
                        pass
                time.sleep(1.0)
            self.ui(lambda: self.log_output(f"Test finished: {ok_count}/{tried} uplinks answering."))
            self.ui(lambda: self.refresh_cards(reschedule=False))
            self.busy = False

        self.log_output("Testing with a tiny real chat call on each configured model…")
        threading.Thread(target=worker, daemon=True).start()

    def open_model_picker(self, pid):
        p = next(x for x in up.load_providers() if x["id"] == pid)
        k = key_for(secure_load_keys(), p)
        if not k:
            self.log_output(f"[{p['name']}] add a key first.")
            return
        pop = tk.Toplevel(self.root)
        pop.title(f"{p['name']} models")
        pop.geometry("620x640")
        pop.configure(bg=BG_COLOR)
        tk.Label(pop, text=f"{p['name'].upper()} — PICK A MODEL", font=FONT_BODY, bg=BG_COLOR,
                 fg=ACCENT_COLOR).pack(pady=6)
        tk.Label(pop, text=f"current: {p['model']}", font=FONT_TINY, bg=BG_COLOR, fg=TEXT_MAIN).pack()
        flt = tk.Entry(pop, font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, insertbackground=TEXT_MAIN)
        flt.pack(fill="x", padx=10, pady=4)
        lb = tk.Listbox(pop, font=FONT_SMALL, bg=PANEL_COLOR, fg=TEXT_MAIN, selectbackground=USED_GREY,
                        selectforeground=ACCENT_COLOR, highlightthickness=0, bd=0)
        lb.pack(fill="both", expand=True, padx=10, pady=4)
        models = []

        def fill(*_):
            q = flt.get().strip().lower()
            lb.delete(0, tk.END)
            for m in models:
                if q in m.lower():
                    lb.insert(tk.END, m)
                    if m == p["model"]:
                        lb.itemconfig(tk.END, fg=ACCENT_COLOR)

        def loaded(result):
            lb.delete(0, tk.END)
            if isinstance(result, Exception):
                lb.insert(tk.END, f"[could not list models: {result}]")
                return
            models[:] = result
            fill()

        def fetch():
            try:
                res = up.list_models(p, k)
            except Exception as ex:
                res = ex
            self.ui(lambda: loaded(res) if pop.winfo_exists() else None)

        def choose(*_):
            sel = lb.curselection()
            if not sel:
                return
            m = lb.get(sel[0])
            if m.startswith("["):
                return
            up.set_model(pid, m)
            self.log_output(f"[{p['name']}] model set to {m}. Testing it…")
            pop.destroy()
            self.refresh_cards(reschedule=False)
            self.test_some([pid])

        flt.bind("<KeyRelease>", fill)
        lb.bind("<Double-Button-1>", choose)
        tk.Button(pop, text="USE THIS MODEL", font=FONT_BODY, bg=PANEL_COLOR, fg=TEXT_MAIN, relief="flat",
                  command=choose).pack(pady=6)
        lb.insert(tk.END, "[loading…]")
        threading.Thread(target=fetch, daemon=True).start()

    def open_keys_editor(self):
        pop = tk.Toplevel(self.root)
        pop.title("API Key Configuration")
        pop.geometry("700x440")
        pop.configure(bg=BG_COLOR)
        pop.resizable(False, False)
        tk.Label(pop, text="UPLINK CREDENTIALS", font=FONT_TITLE, bg=BG_COLOR, fg=ACCENT_COLOR).pack(pady=8)
        current = secure_load_keys()
        entries = {}
        form = tk.Frame(pop, bg=BG_COLOR)
        form.pack(fill="x", padx=15, pady=3)
        for p in up.DEFAULT_PROVIDERS:
            row = tk.Frame(form, bg=BG_COLOR)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=p["name"] + ":", width=14, anchor="e", font=FONT_BODY, bg=BG_COLOR,
                     fg=TEXT_MAIN).pack(side="left")
            ent = tk.Entry(row, font=FONT_BODY, bg=PANEL_COLOR, fg=ACCENT_COLOR, insertbackground=TEXT_MAIN, show="*")
            ent.pack(side="left", fill="x", expand=True, padx=4)
            ent.insert(0, key_for(current, p))
            entries[p["key_env"]] = ent

        def save():
            for k_id, ent in entries.items():
                current[k_id] = ent.get().strip()
            if current.get("GOOGLE_API_KEY"):
                current["GEMINI_API_KEY"] = current["GOOGLE_API_KEY"]
            if secure_save_keys(current):
                self.log_output("Encrypted API credentials saved. Restart Lumi to load new keys.")
                pop.destroy()
                self.refresh_cards(reschedule=False)
            else:
                self.log_output("[!] Vault encryption save failed.")

        tk.Button(pop, text="SAVE SECURE CREDENTIALS", font=FONT_BODY, bg=PANEL_COLOR, fg=TEXT_MAIN, relief="flat",
                  command=save).pack(pady=10)

    def export_keys(self):
        keys = {k: v for k, v in secure_load_keys().items() if v}
        if not keys:
            self.log_output("[!] No keys to export.")
            return
        pw = simpledialog.askstring("Export keys", "Passphrase for the export file:", show="*", parent=self.root)
        if not pw:
            return
        if pw != simpledialog.askstring("Export keys", "Repeat passphrase:", show="*", parent=self.root):
            self.log_output("[!] Passphrases didn't match. Nothing exported.")
            return
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=os.path.expanduser("~"),
                                            initialfile="lumi_keys_export.lumikeys", defaultextension=".lumikeys")
        if not path:
            return
        try:
            up.export_keys(keys, pw, path)
            self.log_output(f"Exported {len(keys)} keys to {path} (passphrase-locked). Move it to the new "
                            f"machine, then Import Keys there and delete the file.")
        except Exception as e:
            self.log_output(f"[!] Export failed: {e}")

    def import_keys(self):
        path = filedialog.askopenfilename(parent=self.root, initialdir=os.path.expanduser("~"),
                                          filetypes=[("Lumi key export", "*.lumikeys"), ("All files", "*")])
        if not path:
            return
        pw = simpledialog.askstring("Import keys", "Passphrase:", show="*", parent=self.root)
        if not pw:
            return
        try:
            incoming = up.import_keys(path, pw)
        except Exception:
            self.log_output("[!] Import failed: wrong passphrase or not a Lumi export file.")
            return
        keys = secure_load_keys()
        keys.update({k: v for k, v in incoming.items() if v})
        if secure_save_keys(keys):
            self.log_output(f"Imported {len(incoming)} keys into this machine's vault. You can delete {path}.")
            self.refresh_cards(reschedule=False)
        else:
            self.log_output("[!] Could not save imported keys.")

    # ---------- misc ----------

    def copy_log_text(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_box.get("1.0", tk.END).strip())
        self.log_output("Telemetry log copied to clipboard.")

    def log_output(self, message):
        self.log_box.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_box.see(tk.END)

    def ui(self, fn):
        self.ui_q.put(fn)

    def drain_ui_queue(self):
        while True:
            try:
                fn = self.ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                print(f"[!] UI update error: {e}")
        self.root.after(100, self.drain_ui_queue)

    def update_clock(self):
        self.clock_label.config(text=f"SYS TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.root.after(1000, self.update_clock)


if __name__ == "__main__":
    root = tk.Tk()
    TokenDashboard(root)
    root.mainloop()
