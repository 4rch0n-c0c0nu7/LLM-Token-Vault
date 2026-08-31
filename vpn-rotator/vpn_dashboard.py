#!/usr/bin/env python3
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import subprocess
import threading
import json
import os

HOME_DIR = "/home/dano"
CONFIG_DIR = os.path.join(HOME_DIR, "vpn_configs")
STATE_FILE = os.path.join(CONFIG_DIR, "rotator_state.json")
ROTATOR_SCRIPT = os.path.join(HOME_DIR, "vpn_rotator.py")

# --- 1990s WINDOWS SYSTEM PALETTE ---
WIN_GRAY = "#C0C0C0"          # Standard Win95 Dialog Background
WIN_DARK_SHADOW = "#808080"   # Bevel Dark Shadow
WIN_LIGHT_SHADOW = "#FFFFFF"  # Bevel Highlight
TITLE_BAR_BG = "#000080"      # Classic Active Window Navy Blue
TITLE_BAR_FG = "#FFFFFF"      # Active Window Title Text
WINDOW_BG = "#ECE9D8"         # Classic dialog surface fallback
TEXT_DARK = "#000000"         # Standard text black
TERM_BG = "#FFFFFF"           # Classic text editor white
TERM_FG = "#000000"           # Classic terminal text black

FONT_TITLE = ("Arial", 10, "bold")
FONT_MAIN = ("MS Sans Serif", 9)
FONT_TERM = ("Courier New", 9)

class VPNDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Tactical VPN Telemetry & Rotator")
        self.root.geometry("640x700")
        self.root.configure(bg=WIN_GRAY)
        self.root.resizable(False, False)

        # Autopilot & Timer State
        self.auto_active = False
        self.interval_options = [5, 15, 30, 60]
        self.current_interval_idx = 1
        self.remaining_seconds = 0
        self.clock_job = None
        self.is_rotating = False
        self.node_buttons = {}

        self._build_ui()
        self.refresh_telemetry()
        self._start_clock_loop()

    def _build_ui(self):
        # Top Title Bar Simulation Frame (Classic Win95 style header banner)
        title_bar = tk.Frame(self.root, bg=TITLE_BAR_BG, height=24)
        title_bar.pack(fill="x", padx=2, pady=2)
        tk.Label(
            title_bar, 
            text=" 🖥️ Global Network Rotator - vpn_dashboard.py", 
            bg=TITLE_BAR_BG, 
            fg=TITLE_BAR_FG, 
            font=FONT_TITLE
        ).pack(side="left", padx=4, pady=2)

        # Main Content Container Frame with sunken bevel
        main_container = tk.Frame(self.root, bg=WIN_GRAY, bd=2, relief="sunken")
        main_container.pack(fill="both", expand=True, padx=6, pady=6)

        # Telemetry Display Frame (LabelFrame with classic raised border)
        telemetry_frame = tk.LabelFrame(
            main_container, 
            text=" Active Telemetry Status ", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            font=FONT_MAIN,
            bd=2,
            relief="groove"
        )
        telemetry_frame.pack(fill="x", padx=10, pady=8)

        tk.Label(telemetry_frame, text="Active Node:", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.lbl_node = tk.Label(telemetry_frame, text="Fetching...", bg=WIN_GRAY, fg="#000080", font=("MS Sans Serif", 9, "bold"))
        self.lbl_node.grid(row=0, column=1, sticky="w", padx=10, pady=2)

        tk.Label(telemetry_frame, text="Public IP:", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.lbl_ip = tk.Label(telemetry_frame, text="Fetching...", bg=WIN_GRAY, fg="#000080", font=("MS Sans Serif", 9, "bold"))
        self.lbl_ip.grid(row=1, column=1, sticky="w", padx=10, pady=2)

        # Autopilot Controls Frame
        control_frame = tk.LabelFrame(
            main_container, 
            text=" Autopilot & Timing Controls ", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            font=FONT_MAIN, 
            bd=2,
            relief="groove",
            padx=8, 
            pady=8
        )
        control_frame.pack(fill="x", padx=10, pady=6)

        tk.Label(control_frame, text="MODE", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=0, column=0, padx=8, pady=(0, 2))
        tk.Label(control_frame, text="TIMER", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=0, column=1, padx=8, pady=(0, 2))
        tk.Label(control_frame, text="EXTEND", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=0, column=2, padx=8, pady=(0, 2))
        tk.Label(control_frame, text="ABORT", bg=WIN_GRAY, fg=TEXT_DARK, font=FONT_MAIN).grid(row=0, column=3, padx=8, pady=(0, 2))

        # AUTO Toggle Button (Raised Win32 style button)
        self.btn_auto = tk.Button(
            control_frame, 
            text="AUTO: OFF", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            width=10, 
            font=FONT_MAIN, 
            command=self.toggle_auto,
            relief="raised",
            bd=2
        )
        self.btn_auto.grid(row=1, column=0, padx=6)

        # Live Countdown / Interval Switcher Button
        mins = self.interval_options[self.current_interval_idx]
        self.btn_interval = tk.Button(
            control_frame, 
            text=f"⏱️ {mins}M", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            width=12, 
            font=FONT_MAIN, 
            command=self.cycle_interval,
            relief="raised",
            bd=2
        )
        self.btn_interval.grid(row=1, column=1, padx=6)

        # +5 MINS Extension Override Button
        self.btn_add_time = tk.Button(
            control_frame, 
            text="+5 MINS", 
            bg=WIN_GRAY, 
            fg="#707070", 
            width=10, 
            font=FONT_MAIN, 
            state=tk.DISABLED, 
            command=self.add_time,
            relief="raised",
            bd=2
        )
        self.btn_add_time.grid(row=1, column=2, padx=6)

        # Emergency Kill Switch Button
        self.btn_kill = tk.Button(
            control_frame, 
            text="KILL SWITCH", 
            bg=WIN_GRAY, 
            fg="#800000", 
            width=12, 
            font=("MS Sans Serif", 9, "bold"), 
            command=self.start_kill,
            relief="raised",
            bd=2
        )
        self.btn_kill.grid(row=1, column=3, padx=6)

        # Manual Override Grid Frame
        self.manual_frame = tk.LabelFrame(
            main_container, 
            text=" Manual Override (Select Node) ", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            font=FONT_MAIN,
            bd=2,
            relief="groove",
            padx=8,
            pady=8
        )
        self.manual_frame.pack(fill="x", padx=10, pady=6)

        configs = []
        if os.path.exists(CONFIG_DIR):
            configs = sorted([f for f in os.listdir(CONFIG_DIR) if f.endswith('.conf')])

        if not configs:
            tk.Label(
                self.manual_frame, 
                text="No .conf files discovered in ~/vpn_configs/", 
                bg=WIN_GRAY, 
                fg="red", 
                font=FONT_MAIN
            ).pack(pady=8)
        else:
            col_count = 0
            row_count = 0
            for conf in configs:
                display_name = conf.replace('.conf', '').upper().replace('PROTON_', '')
                btn = tk.Button(
                    self.manual_frame, 
                    text=display_name, 
                    bg=WIN_GRAY, 
                    fg=TEXT_DARK, 
                    width=11, 
                    font=FONT_MAIN,
                    relief="raised",
                    bd=2,
                    command=lambda c=conf: self.start_rotation(target_config=c)
                )
                btn.grid(row=row_count, column=col_count, padx=4, pady=4, sticky="ew")
                self.node_buttons[conf] = btn

                col_count += 1
                if col_count > 4:
                    col_count = 0
                    row_count += 1

        # Terminal Log Section Header
        log_header_frame = tk.Frame(main_container, bg=WIN_GRAY)
        log_header_frame.pack(fill="x", padx=10, pady=(6, 2))

        tk.Label(
            log_header_frame, 
            text="System Output Log:", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            font=FONT_MAIN
        ).pack(side="left")

        self.btn_copy = tk.Button(
            log_header_frame, 
            text="Copy Log", 
            bg=WIN_GRAY, 
            fg=TEXT_DARK, 
            font=FONT_MAIN, 
            bd=2, 
            relief="raised",
            command=self.copy_logs, 
            cursor="hand2"
        )
        self.btn_copy.pack(side="right")

        # Classic White Editor-style Scrolled Terminal Box (Sunken border)
        term_wrapper = tk.Frame(main_container, bg=WIN_GRAY, bd=2, relief="sunken")
        term_wrapper.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        self.term = ScrolledText(
            term_wrapper, 
            height=9, 
            bg=TERM_BG, 
            fg=TERM_FG, 
            font=FONT_TERM, 
            insertbackground=TERM_FG, 
            bd=0, 
            highlightthickness=0
        )
        self.term.pack(fill="both", expand=True, padx=2, pady=2)
        self.term.insert(tk.END, "[*] Win32 Tactical Subsystem Initialized. Ready...\n")
        self.term.config(state=tk.DISABLED)

    def _start_clock_loop(self):
        """Ticks every 1000ms to calculate countdowns and warning states."""
        if self.auto_active:
            if self.is_rotating:
                self.btn_interval.config(text="[ SYNCING ]", fg="blue")
            else:
                if self.remaining_seconds > 0:
                    self.remaining_seconds -= 1
                    mins, secs = divmod(self.remaining_seconds, 60)
                    
                    if self.remaining_seconds <= 60:
                        time_str = f"⏱️ {mins:02d}:{secs:02d}"
                        alert_color = "red"
                    elif self.remaining_seconds <= 180:
                        time_str = f"⏱️ {mins:02d}:{secs:02d}"
                        alert_color = "#B8860B"  # Dark goldenrod/orange
                    else:
                        time_str = f"⏱️ {mins:02d}:{secs:02d}"
                        alert_color = TEXT_DARK

                    self.btn_interval.config(text=time_str, fg=alert_color)

                if self.remaining_seconds == 0:
                    self.btn_interval.config(text="[ ROTATING ]", fg="red")
                    self.log("\n[⏱️] Countdown elapsed. Initiating scheduled rotation...")
                    mins = self.interval_options[self.current_interval_idx]
                    self.remaining_seconds = mins * 60
                    self.start_rotation()

        self.clock_job = self.root.after(1000, self._start_clock_loop)

    def add_time(self):
        """Adds 300 seconds (5 mins) to the active countdown clock."""
        if self.auto_active:
            self.remaining_seconds += 300
            mins, secs = divmod(self.remaining_seconds, 60)
            self.log(f"[+] Added 5 minutes. Next rotation in: {mins}m {secs}s")

    def toggle_auto(self):
        """Toggles automated interval rotation state and updates button availability."""
        self.auto_active = not self.auto_active
        if self.auto_active:
            mins = self.interval_options[self.current_interval_idx]
            self.remaining_seconds = mins * 60

            self.btn_auto.config(text="AUTO: ON", fg="white", bg="#000080", relief="sunken")
            self.btn_add_time.config(state=tk.NORMAL, fg=TEXT_DARK)
            
            self.btn_interval.config(text=f"⏱️ {mins:02d}:00", fg=TEXT_DARK)
            self.log(f"\n[⚡] Autopilot ENGAGED. Frequency: {mins} minutes.")
            
            self.start_rotation()
        else:
            self.btn_auto.config(text="AUTO: OFF", fg=TEXT_DARK, bg=WIN_GRAY, relief="raised")
            self.btn_add_time.config(state=tk.DISABLED, fg="#707070")
            mins = self.interval_options[self.current_interval_idx]
            self.btn_interval.config(text=f"⏱️ {mins}M", fg=TEXT_DARK)
            self.log("\n[*] Autopilot DISENGAGED. Manual mode active.")

    def cycle_interval(self):
        """Cycles through preset time intervals (only when AUTO is OFF)."""
        if not self.auto_active:
            self.current_interval_idx = (self.current_interval_idx + 1) % len(self.interval_options)
            mins = self.interval_options[self.current_interval_idx]
            self.btn_interval.config(text=f"⏱️ {mins}M")

    def start_rotation(self, target_config=None):
        """Triggers sequential or direct target VPN rotation."""
        if target_config and self.auto_active:
            self.log("[!] Manual override selected. Disengaging Autopilot.")
            self.toggle_auto()

        if self.is_rotating:
            self.log("[!] Operation already in progress.")
            return

        self.is_rotating = True
        self.btn_kill.config(state=tk.DISABLED)

        if target_config:
            self.log(f"\n[⚡] Overriding link -> Handshaking with {target_config}...")
        else:
            self.log("\n[⚡] Executing scheduled node rotation...")

        threading.Thread(target=self._run_rotator, args=(target_config,), daemon=True).start()

    def _run_rotator(self, target_config):
        cmd = ["sudo", "python3", ROTATOR_SCRIPT]
        if target_config:
            cmd.append(target_config)

        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True
            )
            for line in process.stdout:
                self.safe_ui_update(self.log, line.strip())
            process.wait()
        except Exception as e:
            self.safe_ui_update(self.log, f"[ERROR] Execution failed: {str(e)}")

        self.is_rotating = False
        self.safe_ui_update(self.refresh_telemetry)
        self.safe_ui_update(lambda: self.btn_kill.config(state=tk.NORMAL))

    def refresh_telemetry(self):
        """Reads persisted rotator state, highlights active node button, and fetches public IP."""
        active_config = None
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                    active_config = state.get("last_config", None)
                    if active_config:
                        self.lbl_node.config(text=active_config.replace(".conf", "").upper())
                    else:
                        self.lbl_node.config(text="Unknown")
            except Exception:
                self.lbl_node.config(text="ERROR")
        else:
            self.lbl_node.config(text="NONE")

        for conf, btn in self.node_buttons.items():
            if conf == active_config:
                btn.config(bg="#E0E0E0", relief="sunken", font=("MS Sans Serif", 9, "bold"))
            else:
                btn.config(bg=WIN_GRAY, relief="raised", font=FONT_MAIN)

        threading.Thread(target=self._fetch_ip, daemon=True).start()

    def _fetch_ip(self):
        try:
            result = subprocess.run(
                ["curl", "-4", "-s", "--max-time", "5", "https://ifconfig.me"], 
                capture_output=True, 
                text=True
            )
            ip = result.stdout.strip()
            ip = ip if ip else "OFFLINE"
        except Exception:
            ip = "OFFLINE"

        self.safe_ui_update(lambda: self.lbl_ip.config(text=ip))

    def start_kill(self):
        """Terminates WireGuard/VPN interface immediately and restores local routing."""
        self.log("\n[!] EMERGENCY KILL SWITCH ACTIVATED")
        
        # 1. Bring down WireGuard and delete interface
        subprocess.run(["sudo", "wg-quick", "down", "wg0"], stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "ip", "link", "delete", "dev", "wg0"], stderr=subprocess.DEVNULL)

        # 2. Restart NetworkManager to restore default gateway routing and internet
        self.log("[*] Restoring local network routing...")
        subprocess.run(["sudo", "nmcli", "networking", "off"], stderr=subprocess.DEVNULL)
        time.sleep(1)
        subprocess.run(["sudo", "nmcli", "networking", "on"], stderr=subprocess.DEVNULL)

        if self.auto_active:
            self.toggle_auto()

        self.log("[*] Network tunnel destroyed. Local routing restored.")
        self.lbl_node.config(text="DISCONNECTED")
        self.lbl_ip.config(text="OFFLINE")
        
        for btn in self.node_buttons.values():
            btn.config(bg=WIN_GRAY, relief="raised", font=FONT_MAIN)

        self.refresh_telemetry()

    def copy_logs(self):
        """Copies all terminal text to the system clipboard with feedback."""
        logs = self.term.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(logs)
        self.root.update()

        self.btn_copy.config(text="Copied!")
        self.root.after(2000, lambda: self.btn_copy.config(text="Copy Log"))

    def log(self, message):
        """Appends a timestamped line to the scrolled terminal widget."""
        self.term.config(state=tk.NORMAL)
        self.term.insert(tk.END, message + "\n")
        self.term.see(tk.END)
        self.term.config(state=tk.DISABLED)

    def safe_ui_update(self, func, *args):
        """Schedules thread-safe UI updates on Tkinter's main loop."""
        try:
            if self.root.winfo_exists():
                self.root.after(0, func, *args)
        except Exception:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = VPNDashboard(root)
    root.mainloop()
