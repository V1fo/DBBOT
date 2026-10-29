import os
import json
import time
import threading
import queue
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import keyboard

import config
from bot_controller import BotController, BotState
from replayer import is_hardware_esc_pressed
from recording_overlay import RecordingOverlay, AutomatOverlay

# Set visual theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class KeybindDialog(ctk.CTkToplevel):
    def __init__(self, master, action_name: str, current_key: str, callback):
        super().__init__(master)
        self.title("Configure Keybind")
        self.geometry("420x210")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.callback = callback
        self._hook = None
        self._handled = False

        self.card = ctk.CTkFrame(self, fg_color="#181a20", corner_radius=12)
        self.card.pack(fill="both", expand=True, padx=12, pady=12)

        lbl_title = ctk.CTkLabel(
            self.card,
            text=f"Assign key for:\n{action_name}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8f9fa",
            justify="center"
        )
        lbl_title.pack(pady=(12, 6))

        curr_text = f"Current: [{current_key.upper()}]" if current_key else "Current: [Not set]"
        self.lbl_curr = ctk.CTkLabel(
            self.card,
            text=curr_text,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        self.lbl_curr.pack(pady=(0, 6))

        self.lbl_box = ctk.CTkLabel(
            self.card,
            text="[ Press a new key on your keyboard... ]",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2b303c",
            text_color="#60a5fa",
            corner_radius=8,
            padx=16,
            pady=8
        )
        self.lbl_box.pack(pady=4)

        lbl_hint = ctk.CTkLabel(
            self.card,
            text="Press ESC to cancel or close this window",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        lbl_hint.pack(pady=(4, 8))

        self.focus_force()
        self.bind("<Key>", self._on_tk_key)

        try:
            self._hook = keyboard.hook(self._on_global_key)
        except Exception:
            pass

    def _format_key_name(self, raw_key: str) -> str:
        k = raw_key.lower().strip()
        if k == "escape": return "esc"
        if k == "return": return "enter"
        return k

    def _on_tk_key(self, event):
        raw = event.keysym.lower()
        if raw == "escape":
            self._close()
            return
        self._handle_selected_key(self._format_key_name(raw))

    def _on_global_key(self, event):
        if event.event_type == "down":
            k = event.name.lower()
            if k == "esc":
                if hasattr(self.master, "queue_action"):
                    self.master.queue_action(self._close)
                else:
                    self.master.after(0, self._close)
                return
            formatted = self._format_key_name(k)
            if hasattr(self.master, "queue_action"):
                self.master.queue_action(lambda: self._handle_selected_key(formatted))
            else:
                self.master.after(0, lambda: self._handle_selected_key(formatted))

    def _handle_selected_key(self, key_name: str):
        if self._handled:
            return
        self._handled = True
        self.callback(key_name)
        self._close()

    def _close(self):
        if self._hook:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
        try:
            self.destroy()
        except Exception:
            pass


class DungeonBlitzBotGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Dungeon Blitz - Auto Run & Recovery Bot")
        self.geometry("900x940")
        self.minsize(820, 860)

        # Load configuration
        self.cfg = config.load_config()

        # Thread-safe event queue for background threads (bot loop, watchdog, hotkeys)
        self._event_queue = queue.Queue()
        self._last_hw_esc_time = 0.0

        # Currently selected slot for F7 recording: 'main', 'revive', 'reconnect'
        self.active_slot = "main"

        # Initialize Bot Controller
        self.bot = BotController(
            config_dict=self.cfg,
            on_state_change=self._on_bot_state_change,
            on_log=self._on_bot_log
        )

        # Overlay: Recording HUD (only active during F1/F7 recording) & Automat HUD (active whenever Automat is ON)
        self.overlay = RecordingOverlay(self)
        self.automat_overlay = AutomatOverlay(self)
        self._prev_automat_hud_active = False

        self.keybind_rows = {}
        self._secondary_tabs_built = False

        self._build_ui()
        self._refresh_all_run_infos()
        self.register_hotkeys()
        self._poll_event_queue()
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.after(25, self._build_secondary_tabs)

    def _build_ui(self):
        # Main scrollable container
        self.main_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=16, pady=12)

        # --- HEADER ---
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="#181a20", corner_radius=12)
        header_frame.pack(fill="x", pady=(0, 10), ipady=6)

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="⚔️ DUNGEON BLITZ AUTO-BOT",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#4dabf7"
        )
        title_lbl.pack(pady=(4, 2))

        sub_lbl = ctk.CTkLabel(
            header_frame,
            text="Autonomous Combat Loop + Modular Puzzle Builder + Recovery System",
            font=ctk.CTkFont(size=12),
            text_color="#a0aec0"
        )
        sub_lbl.pack(pady=(0, 6))

        # Status Badge
        self.status_badge = ctk.CTkLabel(
            header_frame,
            text="STATUS: READY (IDLE)",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2b303c",
            text_color="#69db7c",
            corner_radius=8,
            padx=16,
            pady=6
        )
        self.status_badge.pack(pady=(0, 6))

        # --- TAB VIEW FOR RUNS, SETTINGS & KEYBINDS ---
        self.tabview = ctk.CTkTabview(
            self.main_frame,
            fg_color="#1f232c",
            corner_radius=12,
            command=self._on_tab_changed
        )
        self.tabview.pack(fill="x", pady=6)

        self.tab_main = self.tabview.add("Combat")
        self.tab_automat = self.tabview.add("Auto-Mob")
        self.tab_heal = self.tabview.add("Heal")
        self.tab_revive = self.tabview.add("Revive")
        self.tab_reconnect = self.tabview.add("Reconnect")
        self.tab_server_reconnect = self.tabview.add("Server")
        self.tab_lobby = self.tabview.add("Lobby")
        self.tab_exit = self.tabview.add("Exit")
        self.tab_keybinds = self.tabview.add("Keybinds")

        # -------------------------------------------------------------
        # TAB 1: MAIN COMBAT RUN (WITH PROFILE MANAGEMENT)
        # -------------------------------------------------------------
        t1_desc = ctk.CTkLabel(
            self.tab_main,
            text="This run executes in an infinite loop. You can save multiple run profiles and select the active one.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        t1_desc.pack(anchor="w", padx=8, pady=(4, 6))

        # Profile selection & management box
        profile_frame = ctk.CTkFrame(self.tab_main, fg_color="#181a20", corner_radius=10)
        profile_frame.pack(fill="x", padx=8, pady=(0, 10), ipady=6)

        row_prof_select = ctk.CTkFrame(profile_frame, fg_color="transparent")
        row_prof_select.pack(fill="x", padx=12, pady=(6, 4))

        lbl_prof = ctk.CTkLabel(
            row_prof_select,
            text="📁 Selected Combat Run:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8f9fa"
        )
        lbl_prof.pack(side="left", padx=(0, 10))

        available_runs = config.list_combat_runs()
        curr_selected = self.cfg.get("selected_combat_run", available_runs[0])

        self.opt_combat_runs = ctk.CTkOptionMenu(
            row_prof_select,
            values=available_runs,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1971c2",
            button_color="#1864ab",
            button_hover_color="#15538e",
            width=180,
            command=self._on_combat_run_selected
        )
        self.opt_combat_runs.set(curr_selected)
        self.opt_combat_runs.pack(side="left", padx=(0, 10))

        btn_new_run = ctk.CTkButton(
            row_prof_select,
            text="➕ New Run",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2b8a3e",
            hover_color="#237032",
            width=90,
            height=30,
            command=self._create_new_run_dialog
        )
        btn_new_run.pack(side="left", padx=(0, 6))

        btn_del_run = ctk.CTkButton(
            row_prof_select,
            text="🗑 Delete",
            font=ctk.CTkFont(size=12),
            fg_color="#c92a2a",
            hover_color="#a61e1e",
            width=75,
            height=30,
            command=self._delete_current_run
        )
        btn_del_run.pack(side="left", padx=(0, 6))

        btn_open_folder = ctk.CTkButton(
            row_prof_select,
            text="📂 Folder",
            font=ctk.CTkFont(size=12),
            fg_color="#495057",
            hover_color="#343a40",
            width=85,
            height=30,
            command=self._open_runs_folder
        )
        btn_open_folder.pack(side="left")

        # Run file info
        self.run_info_main = ctk.CTkLabel(
            self.tab_main,
            text="📁 Run File: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#38d9a9"
        )
        self.run_info_main.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_main = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        btn_row_main.pack(fill="x", padx=8, pady=4)

        hk_rec = self.cfg.get("hotkeys", {}).get("record_active", "f7").upper()
        self.btn_rec_main = ctk.CTkButton(
            btn_row_main,
            text=f"🔴 Record Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#e03131",
            hover_color="#c92a2a",
            height=38,
            command=lambda: self.toggle_recording("main")
        )
        self.btn_rec_main.pack(fill="x", expand=True)

        # --- PUZZLE SEGMENTS SECTION (MODULAR RUN) ---
        self.puzzle_frame = ctk.CTkFrame(self.tab_main, fg_color="#181a20", corner_radius=10, border_color="#2563eb", border_width=1)
        self.puzzle_frame.pack(fill="x", padx=8, pady=(10, 8), ipady=6)

        puzzle_hdr = ctk.CTkFrame(self.puzzle_frame, fg_color="transparent")
        puzzle_hdr.pack(fill="x", padx=12, pady=(6, 2))

        lbl_puzzle_title = ctk.CTkLabel(
            puzzle_hdr,
            text="🧩 COMBAT RUN PUZZLE BUILDER (MODULAR STEPS)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#60a5fa"
        )
        lbl_puzzle_title.pack(side="left")

        lbl_puzzle_desc = ctk.CTkLabel(
            self.puzzle_frame,
            text="Break down your dungeon run into modular steps. If you make a mistake (e.g. miss a door),\njust re-record that single step instead of repeating the entire 5-minute dungeon from scratch!",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        )
        lbl_puzzle_desc.pack(anchor="w", padx=12, pady=(0, 6))

        # Dynamic container for segment cards
        self.puzzle_list_container = ctk.CTkFrame(self.puzzle_frame, fg_color="transparent")
        self.puzzle_list_container.pack(fill="x", padx=12, pady=(2, 6))

        # Puzzle toolbar
        puzzle_toolbar = ctk.CTkFrame(self.puzzle_frame, fg_color="transparent")
        puzzle_toolbar.pack(fill="x", padx=12, pady=(4, 4))

        self.btn_puzzle_add_automat = ctk.CTkButton(
            puzzle_toolbar,
            text="➕ Add Step: 🤖 AUTO-MOB",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=30,
            command=self._puzzle_add_automat_step
        )
        self.btn_puzzle_add_automat.pack(side="left", padx=(0, 8))

        self.btn_puzzle_split = ctk.CTkButton(
            puzzle_toolbar,
            text="✂️ Slice Entire Run by Seconds",
            font=ctk.CTkFont(size=12),
            fg_color="#0891b2",
            hover_color="#0e7490",
            height=30,
            command=self._puzzle_split_dialog
        )
        self.btn_puzzle_split.pack(side="left", padx=(0, 8))

        self.btn_puzzle_merge = ctk.CTkButton(
            puzzle_toolbar,
            text="🔄 Merge Puzzle into Flat Run",
            font=ctk.CTkFont(size=12),
            fg_color="#475569",
            hover_color="#334155",
            height=30,
            command=self._puzzle_merge_action
        )
        self.btn_puzzle_merge.pack(side="left", padx=(0, 10))

        lbl_f7_hint = ctk.CTkLabel(
            self.puzzle_frame,
            text="💡 Live In-Game Building: [F1] = Record Movement Step  |  [F2] = Save Movement, Add 🤖 AUTO-MOB & Clear Room (with Return to Origin)!",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_f7_hint.pack(anchor="w", padx=12, pady=(0, 6))

        # Timing inputs
        timing_subframe = ctk.CTkFrame(self.tab_main, fg_color="#181a20", corner_radius=8)
        timing_subframe.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_delay = ctk.CTkFrame(timing_subframe, fg_color="transparent")
        row_delay.pack(fill="x", padx=12, pady=4)

        lbl_delay = ctk.CTkLabel(
            row_delay,
            text="⏳ Initial Start Countdown Delay [seconds]:",
            font=ctk.CTkFont(size=13),
            text_color="#cbd5e1"
        )
        lbl_delay.pack(side="left")

        curr_delay = str(self.cfg.get("start_delay", 3.0))
        self.entry_delay = ctk.CTkEntry(
            row_delay, width=100, height=32, font=ctk.CTkFont(size=14), justify="center"
        )
        self.entry_delay.insert(0, curr_delay)
        self.entry_delay.pack(side="right")
        self.entry_delay.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_delay.bind("<Return>", self._save_timing_inputs)

        # --- CONSTANT ATTACK (HOLD PRIMARY ATTACK ON CHARACTER) ---
        ca_frame = ctk.CTkFrame(self.tab_main, fg_color="#181a20", corner_radius=8, border_color="#eab308", border_width=1)
        ca_frame.pack(fill="x", padx=8, pady=(6, 6), ipady=6)

        row_ca_top = ctk.CTkFrame(ca_frame, fg_color="transparent")
        row_ca_top.pack(fill="x", padx=12, pady=(6, 4))

        ca_enabled = bool(self.cfg.get("enable_constant_attack", True))
        self.btn_constant_attack = ctk.CTkButton(
            row_ca_top,
            text="🗡️ CONSTANT ATTACK (Hold LMB on character): ON" if ca_enabled else "🗡️ CONSTANT ATTACK (Hold LMB on character): OFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#ca8a04" if ca_enabled else "#475569",
            hover_color="#a16207" if ca_enabled else "#334155",
            height=36,
            command=self._toggle_constant_attack
        )
        self.btn_constant_attack.pack(fill="x", expand=True)

        row_ca_delay = ctk.CTkFrame(ca_frame, fg_color="transparent")
        row_ca_delay.pack(fill="x", padx=12, pady=(4, 4))

        lbl_ca_delay = ctk.CTkLabel(
            row_ca_delay,
            text="⏱️ Delay before auto-attacking [seconds] (then constantly holds LMB):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fde047"
        )
        lbl_ca_delay.pack(side="left")

        curr_ca_delay = str(self.cfg.get("constant_attack_delay", 5.0))
        self.entry_constant_attack_delay = ctk.CTkEntry(
            row_ca_delay, width=100, height=30, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_constant_attack_delay.insert(0, curr_ca_delay)
        self.entry_constant_attack_delay.pack(side="right")
        self.entry_constant_attack_delay.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_constant_attack_delay.bind("<Return>", self._save_timing_inputs)

        # --- RECORDED RUN COOPERATION WITH AUTO-MOB (DOORS / PARKOUR + COMBAT) ---
        assist_frame = ctk.CTkFrame(self.tab_main, fg_color="#181a20", corner_radius=8, border_color="#10b981", border_width=1)
        assist_frame.pack(fill="x", padx=8, pady=(2, 6), ipady=6)

        self.chk_main_automat_assist = ctk.CTkCheckBox(
            assist_frame,
            text="🤖 Auto-Mob Assist: When mobs appear during a run, pause on spot, kill them, then resume run (doors / parkour)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#6ee7b7",
            command=lambda: self._on_automat_assist_change(source="main")
        )
        if self.cfg.get("enable_automat_assist", False):
            self.chk_main_automat_assist.select()
        else:
            self.chk_main_automat_assist.deselect()
        self.chk_main_automat_assist.pack(anchor="w", padx=12, pady=(6, 6))

        # --- BOTTOM ACTION PANEL (ALWAYS VISIBLE - LOADED FIRST FOR FAST UI DISPLAY) ---
        bot_card = ctk.CTkFrame(self.main_frame, fg_color="#21252d", corner_radius=12)
        bot_card.pack(fill="x", pady=8, padx=4, ipady=6)

        bot_action_row = ctk.CTkFrame(bot_card, fg_color="transparent")
        bot_action_row.pack(fill="x", padx=14, pady=4)

        hk_bot = self.cfg.get("hotkeys", {}).get("bot_toggle", "f8").upper()
        hk_stop = self.cfg.get("hotkeys", {}).get("emergency_stop", "f9").upper()

        self.btn_start_bot = ctk.CTkButton(
            bot_action_row,
            text=f"⚡ START AUTOMATIC BOT ({hk_bot})",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2b8a3e",
            hover_color="#237032",
            height=46,
            command=self.toggle_bot_loop
        )
        self.btn_start_bot.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_emergency_stop = ctk.CTkButton(
            bot_action_row,
            text=f"🛑 EMERGENCY STOP ({hk_stop})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#c92a2a",
            hover_color="#a61e1e",
            height=46,
            width=170,
            command=self.emergency_stop
        )
        self.btn_emergency_stop.pack(side="left")

        # Global Checkboxes
        chk_row = ctk.CTkFrame(bot_card, fg_color="transparent")
        chk_row.pack(fill="x", padx=14, pady=(6, 4))

        self.chk_mouse = ctk.CTkCheckBox(
            chk_row,
            text="Record smooth mouse movement",
            font=ctk.CTkFont(size=12),
            command=self._on_settings_checkbox
        )
        if self.cfg.get("record_mouse_move", True):
            self.chk_mouse.select()
        else:
            self.chk_mouse.deselect()
        self.chk_mouse.pack(side="left", padx=(0, 20))

        self.chk_sound = ctk.CTkCheckBox(
            chk_row,
            text="Sound alerts (Beeps & Warning Chimes)",
            font=ctk.CTkFont(size=12),
            command=self._on_settings_checkbox
        )
        if self.cfg.get("sound_enabled", True):
            self.chk_sound.select()
        else:
            self.chk_sound.deselect()
        self.chk_sound.pack(side="left")

        # --- SECTION 4: LOG CONSOLE ---
        log_card = ctk.CTkFrame(self.main_frame, fg_color="#181a20", corner_radius=12)
        log_card.pack(fill="both", expand=True, pady=8, padx=4, ipady=6)

        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(4, 4))

        log_title = ctk.CTkLabel(
            log_header,
            text="📋 Activity Log",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#e2e8f0"
        )
        log_title.pack(side="left")

        btn_clear_log = ctk.CTkButton(
            log_header,
            text="Clear",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#1e293b",
            height=24,
            width=65,
            command=self._clear_log
        )
        btn_clear_log.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            log_card,
            height=120,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0f1117",
            text_color="#cbd5e1",
            activate_scrollbars=True
        )
        self.log_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.log_textbox.configure(state="disabled")

        self._log("Dungeon Blitz Bot ready.")
        self._log("Hotkeys: [F1] Movement Step | [F2] Auto-Mob Step | [F7] Record Active | [F8] Start/Pause | [F9 / ESC] Stop")

    def _build_secondary_tabs(self):
        """Builds tabs 2 through 9 asynchronously after main UI has rendered for instant startup."""
        if getattr(self, "_secondary_tabs_built", False):
            return
        self._secondary_tabs_built = True

        hk_rec = self.cfg.get("hotkeys", {}).get("record_active", "f7").upper()

        # -------------------------------------------------------------
        # TAB 1.5: AUTO-MOB (AUTONOMOUS COMBAT & MOVEMENT)
        # -------------------------------------------------------------
        t_auto_desc = ctk.CTkLabel(
            self.tab_automat,
            text="🤖 Autonomous AUTO-MOB Mode (or live assist for recorded dungeon runs with doors/parkour):\n"
                 "• ADVANCE: When no mobs are visible, character walks forward (D / A) and shoots ahead with configured angle and spread.\n"
                 "• COMBAT & SKILLS: Fires Skills 4 & 5 whenever available. When multiple mobs appear (>= threshold), saves mana\n"
                 "  exclusively for AoE Skill 3; against single targets, spams Skill 1. Continues attacking for linger duration after mobs die.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        )
        t_auto_desc.pack(anchor="w", padx=8, pady=(4, 6))

        auto_action_frame = ctk.CTkFrame(self.tab_automat, fg_color="#181a20", corner_radius=10, border_color="#10b981", border_width=1)
        auto_action_frame.pack(fill="x", padx=8, pady=(2, 8), ipady=6)

        self.btn_toggle_automat = ctk.CTkButton(
            auto_action_frame,
            text="🤖 START AUTO-MOB MODE",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=42,
            command=self.toggle_automat_mode
        )
        self.btn_toggle_automat.pack(fill="x", padx=12, pady=(8, 6))

        self.chk_automat_f8 = ctk.CTkCheckBox(
            auto_action_frame,
            text="Trigger pure AUTO-MOB mode with primary key F8 (instead of recorded run)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#6ee7b7",
            command=self._on_automat_settings_change
        )
        if self.cfg.get("automat_use_on_f8", False):
            self.chk_automat_f8.select()
        else:
            self.chk_automat_f8.deselect()
        self.chk_automat_f8.pack(anchor="w", padx=12, pady=(2, 4))

        self.chk_tab_automat_assist = ctk.CTkCheckBox(
            auto_action_frame,
            text="🤝 Recorded Run Assist (F8 runs recorded dungeon; Auto-Mob engages only when mobs are spotted)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fde047",
            command=lambda: self._on_automat_assist_change(source="automat")
        )
        if self.cfg.get("enable_automat_assist", False):
            self.chk_tab_automat_assist.select()
        else:
            self.chk_tab_automat_assist.deselect()
        self.chk_tab_automat_assist.pack(anchor="w", padx=12, pady=(2, 6))

        auto_cfg_frame = ctk.CTkFrame(self.tab_automat, fg_color="#181a20", corner_radius=10)
        auto_cfg_frame.pack(fill="x", padx=8, pady=4, ipady=6)

        # Row 1: Direction D / A / Stand
        row_auto_dir = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_dir.pack(fill="x", padx=12, pady=4)
        lbl_auto_dir = ctk.CTkLabel(
            row_auto_dir,
            text="🏃 Advance Direction (D=Right / A=Left / Stand=Hold Position):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        lbl_auto_dir.pack(side="left")

        curr_move_key = str(self.cfg.get("automat_move_key", "d")).lower().strip()
        if curr_move_key == "stand":
            dir_label = "Stand (Hold Position)"
        elif curr_move_key == "a":
            dir_label = "A (Left)"
        else:
            dir_label = "D (Right)"
        self.opt_automat_dir = ctk.CTkOptionMenu(
            row_auto_dir,
            values=["D (Right)", "A (Left)", "Stand (Hold Position)"],
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1971c2",
            button_color="#1864ab",
            width=190,
            command=self._on_automat_dir_selected
        )
        self.opt_automat_dir.set(dir_label)
        self.opt_automat_dir.pack(side="right")

        # Row 2: Linger delay after mobs disappear (default 3.0s)
        row_auto_linger = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_linger.pack(fill="x", padx=12, pady=4)
        lbl_auto_linger = ctk.CTkLabel(
            row_auto_linger,
            text="⏱️ Attack linger after mobs disappear [seconds, e.g. 3.0]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fde047"
        )
        lbl_auto_linger.pack(side="left")

        self.entry_automat_linger = ctk.CTkEntry(
            row_auto_linger, width=80, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_automat_linger.insert(0, str(self.cfg.get("automat_combat_linger_seconds", 3.0)))
        self.entry_automat_linger.pack(side="right")
        self.entry_automat_linger.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_linger.bind("<Return>", self._save_automat_inputs)

        # Row 2.5: Periodic Jump (W) interval during advance (default 10.0s)
        row_auto_jump = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_jump.pack(fill="x", padx=12, pady=4)
        lbl_auto_jump = ctk.CTkLabel(
            row_auto_jump,
            text="🦘 Periodic jump (Key W) during advance every [seconds] (0 = disabled):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#93c5fd"
        )
        lbl_auto_jump.pack(side="left")

        self.entry_automat_jump = ctk.CTkEntry(
            row_auto_jump, width=80, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_automat_jump.insert(0, str(self.cfg.get("automat_jump_interval", 10.0)))
        self.entry_automat_jump.pack(side="right")
        self.entry_automat_jump.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_jump.bind("<Return>", self._save_automat_inputs)

        # Row 2.6: AoE Mob Threshold & Pack Memory Duration (Skill 3 vs Skill 1)
        row_auto_aoe = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_aoe.pack(fill="x", padx=12, pady=4)
        lbl_auto_aoe = ctk.CTkLabel(
            row_auto_aoe,
            text="💥 AoE Mob Threshold (saves mana for Skill 3) & Pack Memory Duration [s]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f472b6"
        )
        lbl_auto_aoe.pack(side="left")

        aoe_box = ctk.CTkFrame(row_auto_aoe, fg_color="transparent")
        aoe_box.pack(side="right")

        lbl_aoe_cnt = ctk.CTkLabel(aoe_box, text="Mobs >=", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1")
        lbl_aoe_cnt.pack(side="left", padx=(0, 4))

        self.entry_automat_aoe = ctk.CTkEntry(
            aoe_box, width=55, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_automat_aoe.insert(0, str(self.cfg.get("automat_aoe_mob_threshold", 3)))
        self.entry_automat_aoe.pack(side="left", padx=(0, 10))
        self.entry_automat_aoe.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_aoe.bind("<Return>", self._save_automat_inputs)

        lbl_aoe_mem = ctk.CTkLabel(aoe_box, text="Memory [s]:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1")
        lbl_aoe_mem.pack(side="left", padx=(0, 4))

        self.entry_automat_aoe_mem = ctk.CTkEntry(
            aoe_box, width=65, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_automat_aoe_mem.insert(0, str(self.cfg.get("automat_aoe_memory_seconds", 20.0)))
        self.entry_automat_aoe_mem.pack(side="left")
        self.entry_automat_aoe_mem.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_aoe_mem.bind("<Return>", self._save_automat_inputs)

        # Row 2.7: Shoot Angle & Spread during forward run
        row_auto_angle = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_angle.pack(fill="x", padx=12, pady=4)
        lbl_auto_angle = ctk.CTkLabel(
            row_auto_angle,
            text="🎯 Shoot angle during forward run [°] (+up / -down / 0=level) & Oscillation spread [±°]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a7f3d0"
        )
        lbl_auto_angle.pack(side="left")

        angle_box = ctk.CTkFrame(row_auto_angle, fg_color="transparent")
        angle_box.pack(side="right")

        ctk.CTkLabel(angle_box, text="Angle°:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_automat_angle = ctk.CTkEntry(
            angle_box, width=55, height=28, font=ctk.CTkFont(size=12, weight="bold"), justify="center"
        )
        self.entry_automat_angle.insert(0, str(self.cfg.get("automat_shoot_angle", 0.0)))
        self.entry_automat_angle.pack(side="left", padx=(0, 8))
        self.entry_automat_angle.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_angle.bind("<Return>", self._save_automat_inputs)

        ctk.CTkLabel(angle_box, text="Spread±°:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_automat_spread = ctk.CTkEntry(
            angle_box, width=55, height=28, font=ctk.CTkFont(size=12, weight="bold"), justify="center"
        )
        self.entry_automat_spread.insert(0, str(self.cfg.get("automat_shoot_spread", 12.0)))
        self.entry_automat_spread.pack(side="left")
        self.entry_automat_spread.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_spread.bind("<Return>", self._save_automat_inputs)

        # Row 3: Skill keys 1, 3, 4, 5
        row_auto_skills = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_skills.pack(fill="x", padx=12, pady=(6, 4))
        lbl_auto_skills = ctk.CTkLabel(
            row_auto_skills,
            text="🔥 Combat skill keybinds (1 & 3 based on mana | 4 & 5 whenever available):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1"
        )
        lbl_auto_skills.pack(side="left")

        skills_box = ctk.CTkFrame(row_auto_skills, fg_color="transparent")
        skills_box.pack(side="right")

        ctk.CTkLabel(skills_box, text="S1:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_auto_s1 = ctk.CTkEntry(skills_box, width=36, height=26, font=ctk.CTkFont(size=12, weight="bold"), justify="center")
        self.entry_auto_s1.insert(0, str(self.cfg.get("automat_skill_1_key", "1")))
        self.entry_auto_s1.pack(side="left", padx=(0, 6))
        self.entry_auto_s1.bind("<FocusOut>", self._save_automat_inputs)

        ctk.CTkLabel(skills_box, text="S3:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_auto_s3 = ctk.CTkEntry(skills_box, width=36, height=26, font=ctk.CTkFont(size=12, weight="bold"), justify="center")
        self.entry_auto_s3.insert(0, str(self.cfg.get("automat_skill_3_key", "3")))
        self.entry_auto_s3.pack(side="left", padx=(0, 6))
        self.entry_auto_s3.bind("<FocusOut>", self._save_automat_inputs)

        ctk.CTkLabel(skills_box, text="S4:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_auto_s4 = ctk.CTkEntry(skills_box, width=36, height=26, font=ctk.CTkFont(size=12, weight="bold"), justify="center")
        self.entry_auto_s4.insert(0, str(self.cfg.get("automat_skill_4_key", "4")))
        self.entry_auto_s4.pack(side="left", padx=(0, 6))
        self.entry_auto_s4.bind("<FocusOut>", self._save_automat_inputs)

        ctk.CTkLabel(skills_box, text="S5:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(2, 2))
        self.entry_auto_s5 = ctk.CTkEntry(skills_box, width=36, height=26, font=ctk.CTkFont(size=12, weight="bold"), justify="center")
        self.entry_auto_s5.insert(0, str(self.cfg.get("automat_skill_5_key", "5")))
        self.entry_auto_s5.pack(side="left")
        self.entry_auto_s5.bind("<FocusOut>", self._save_automat_inputs)

        # Row 4: Skill 5 (Shield) minimum interval so 2nd activation doesn't cancel shield
        row_auto_s5_cd = ctk.CTkFrame(auto_cfg_frame, fg_color="transparent")
        row_auto_s5_cd.pack(fill="x", padx=12, pady=4)
        lbl_auto_s5_cd = ctk.CTkLabel(
            row_auto_s5_cd,
            text="🛡️ Min interval for Skill 5 (Shield) to prevent accidental cancellation [seconds]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_auto_s5_cd.pack(side="left")

        self.entry_automat_s5_cd = ctk.CTkEntry(
            row_auto_s5_cd, width=80, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_automat_s5_cd.insert(0, str(self.cfg.get("automat_skill_5_min_interval", 15.0)))
        self.entry_automat_s5_cd.pack(side="right")
        self.entry_automat_s5_cd.bind("<FocusOut>", self._save_automat_inputs)
        self.entry_automat_s5_cd.bind("<Return>", self._save_automat_inputs)

        # Diagnostic Box for Automat
        auto_diag_frame = ctk.CTkFrame(self.tab_automat, fg_color="#181a20", corner_radius=10)
        auto_diag_frame.pack(fill="x", padx=8, pady=(6, 4), ipady=6)

        self.btn_test_automat = ctk.CTkButton(
            auto_diag_frame,
            text="🔍 Test Mob HP Bars, Mana & Skills 1-5 Detection on Screen",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=34,
            command=self._test_automat_detection
        )
        self.btn_test_automat.pack(fill="x", padx=12, pady=(6, 4))

        self.lbl_automat_test_result = ctk.CTkLabel(
            auto_diag_frame,
            text="Click button above to verify how many mob HP bars, Mana %, and Skills 1-5 the bot detects on screen.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        )
        self.lbl_automat_test_result.pack(anchor="w", padx=12, pady=(2, 6))

        # -------------------------------------------------------------
        # TAB 2: AUTO-HEAL (HEALING / AUTO POTION)
        # -------------------------------------------------------------
        t_heal_desc = ctk.CTkLabel(
            self.tab_heal,
            text="Real-time automatic healing during active combat:\n"
                 "• Continuously monitors the red HP globe potion level in the bottom-left corner.\n"
                 "• When HP drops below threshold, verifies if Skill 2 is COLORED (ready to cast).\n"
                 "• Instantly triggers the heal without interrupting the combat run or losing rhythm!",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t_heal_desc.pack(anchor="w", padx=8, pady=(4, 6))

        heal_frame = ctk.CTkFrame(self.tab_heal, fg_color="#181a20", corner_radius=10)
        heal_frame.pack(fill="x", padx=8, pady=6, ipady=6)

        # Checkbox: Enable Auto-Heal
        row_chk_heal = ctk.CTkFrame(heal_frame, fg_color="transparent")
        row_chk_heal.pack(fill="x", padx=12, pady=(6, 8))

        self.chk_auto_heal = ctk.CTkCheckBox(
            row_chk_heal,
            text="Enable Auto-Heal (automatically triggers healing skill at low HP)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#34d399",
            command=self._on_heal_settings_change
        )
        if self.cfg.get("enable_auto_heal", True):
            self.chk_auto_heal.select()
        else:
            self.chk_auto_heal.deselect()
        self.chk_auto_heal.pack(side="left")

        # Row: Heal Keybind
        row_h_key = ctk.CTkFrame(heal_frame, fg_color="transparent")
        row_h_key.pack(fill="x", padx=12, pady=4)
        lbl_h_key = ctk.CTkLabel(row_h_key, text="Key for healing skill (default 2):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1")
        lbl_h_key.pack(side="left")
        self.entry_heal_key = ctk.CTkEntry(row_h_key, width=70, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center")
        self.entry_heal_key.insert(0, str(self.cfg.get("heal_key", "2")))
        self.entry_heal_key.pack(side="right")
        self.entry_heal_key.bind("<FocusOut>", self._save_heal_inputs)
        self.entry_heal_key.bind("<Return>", self._save_heal_inputs)

        # Row: HP Threshold %
        row_h_pct = ctk.CTkFrame(heal_frame, fg_color="transparent")
        row_h_pct.pack(fill="x", padx=12, pady=4)
        lbl_h_pct = ctk.CTkLabel(row_h_pct, text="Trigger heal when Health (HP) drops below [%]:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f87171")
        lbl_h_pct.pack(side="left")
        self.entry_heal_thresh = ctk.CTkEntry(row_h_pct, width=70, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center")
        self.entry_heal_thresh.insert(0, str(self.cfg.get("heal_hp_threshold", 40.0)))
        self.entry_heal_thresh.pack(side="right")
        self.entry_heal_thresh.bind("<FocusOut>", self._save_heal_inputs)
        self.entry_heal_thresh.bind("<Return>", self._save_heal_inputs)

        # Row: Cooldown
        row_h_cd = ctk.CTkFrame(heal_frame, fg_color="transparent")
        row_h_cd.pack(fill="x", padx=12, pady=4)
        lbl_h_cd = ctk.CTkLabel(row_h_cd, text="Minimum cooldown between heals [seconds]:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fcd34d")
        lbl_h_cd.pack(side="left")
        self.entry_heal_cooldown = ctk.CTkEntry(row_h_cd, width=70, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center")
        self.entry_heal_cooldown.insert(0, str(self.cfg.get("heal_cooldown_seconds", 2.0)))
        self.entry_heal_cooldown.pack(side="right")
        self.entry_heal_cooldown.bind("<FocusOut>", self._save_heal_inputs)
        self.entry_heal_cooldown.bind("<Return>", self._save_heal_inputs)

        # Row: Save Mana for Heal (Skill 2) instead of spending on Skill 1 when HP < 50%
        row_h_save_mana = ctk.CTkFrame(heal_frame, fg_color="transparent")
        row_h_save_mana.pack(fill="x", padx=12, pady=(8, 4))

        self.chk_heal_save_mana = ctk.CTkCheckBox(
            row_h_save_mana,
            text="💧 Conserve mana for Heal (Skill 2) instead of spending on Skill 1 when HP is below [%]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#60a5fa",
            command=self._on_heal_settings_change
        )
        if self.cfg.get("heal_save_mana_enabled", True):
            self.chk_heal_save_mana.select()
        else:
            self.chk_heal_save_mana.deselect()
        self.chk_heal_save_mana.pack(side="left")

        self.entry_heal_save_mana_thresh = ctk.CTkEntry(
            row_h_save_mana, width=70, height=28, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_heal_save_mana_thresh.insert(0, str(self.cfg.get("heal_save_mana_hp_threshold", 50.0)))
        self.entry_heal_save_mana_thresh.pack(side="right")
        self.entry_heal_save_mana_thresh.bind("<FocusOut>", self._save_heal_inputs)
        self.entry_heal_save_mana_thresh.bind("<Return>", self._save_heal_inputs)

        # Diagnostic Box
        diag_frame = ctk.CTkFrame(self.tab_heal, fg_color="#181a20", corner_radius=10)
        diag_frame.pack(fill="x", padx=8, pady=(8, 4), ipady=6)

        lbl_diag_title = ctk.CTkLabel(diag_frame, text="🔍 Live Screen Diagnostics (Test HP & Skill 2 Detection)", font=ctk.CTkFont(size=12, weight="bold"), text_color="#60a5fa")
        lbl_diag_title.pack(anchor="w", padx=12, pady=(4, 6))

        self.btn_test_heal = ctk.CTkButton(
            diag_frame,
            text="🔍 Test Current HP Level and Skill 2 Status on Screen",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=34,
            command=self._test_heal_detection
        )
        self.btn_test_heal.pack(fill="x", padx=12, pady=4)

        self.lbl_heal_test_result = ctk.CTkLabel(
            diag_frame,
            text="Click button above to verify detected HP percentage and Skill 2 readiness.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        )
        self.lbl_heal_test_result.pack(anchor="w", padx=12, pady=(4, 6))

        # -------------------------------------------------------------
        # TAB 3: DEATH RECOVERY (ANGEL REVIVE)
        # -------------------------------------------------------------
        t2_desc = ctk.CTkLabel(
            self.tab_revive,
            text="When your character dies and the Angel appears with the REVIVE button, the combat run is PAUSED,\nthis recovery run executes, and combat resumes right where it left off.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t2_desc.pack(anchor="w", padx=8, pady=(4, 6))

        self.run_info_revive = ctk.CTkLabel(
            self.tab_revive,
            text="📁 Revive Run: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#ffd43b"
        )
        self.run_info_revive.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_revive = ctk.CTkFrame(self.tab_revive, fg_color="transparent")
        btn_row_revive.pack(fill="x", padx=8, pady=4)

        self.btn_rec_revive = ctk.CTkButton(
            btn_row_revive,
            text=f"🔴 Record Revive Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#f08c00",
            hover_color="#d97706",
            height=38,
            command=lambda: self.toggle_recording("revive")
        )
        self.btn_rec_revive.pack(fill="x", expand=True)

        revive_detect_frame = ctk.CTkFrame(self.tab_revive, fg_color="#181a20", corner_radius=8)
        revive_detect_frame.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_death_opts = ctk.CTkFrame(revive_detect_frame, fg_color="transparent")
        row_death_opts.pack(fill="x", padx=12, pady=(6, 2))

        self.chk_death = ctk.CTkCheckBox(
            row_death_opts,
            text="Enable automatic death recovery (Angel Revive)",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_recovery_settings_change
        )
        if self.cfg.get("enable_death_recovery", True):
            self.chk_death.select()
        else:
            self.chk_death.deselect()
        self.chk_death.pack(side="left")

        curr_d_thresh = int(self.cfg.get("death_threshold", 0.75) * 100)
        self.lbl_death_thresh = ctk.CTkLabel(
            row_death_opts,
            text=f"Sensitivity: {curr_d_thresh}%",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_death_thresh.pack(side="right", padx=(0, 6))

        # Rewind seconds after revive
        row_death_rewind = ctk.CTkFrame(revive_detect_frame, fg_color="transparent")
        row_death_rewind.pack(fill="x", padx=12, pady=(4, 6))

        lbl_d_rewind = ctk.CTkLabel(
            row_death_rewind,
            text="⏪ Rewind combat run after revive by [seconds]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fcd34d"
        )
        lbl_d_rewind.pack(side="left")

        curr_d_rewind = str(self.cfg.get("death_rewind_seconds", 3.0))
        self.entry_death_rewind = ctk.CTkEntry(
            row_death_rewind, width=80, height=30, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_death_rewind.insert(0, curr_d_rewind)
        self.entry_death_rewind.pack(side="right")
        self.entry_death_rewind.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_death_rewind.bind("<Return>", self._save_timing_inputs)

        # -------------------------------------------------------------
        # TAB 4: CONNECTION RECOVERY (LOST CONNECTION)
        # -------------------------------------------------------------
        t3_desc = ctk.CTkLabel(
            self.tab_reconnect,
            text="When a Lost Connection popup appears, combat is PAUSED (just like Angel Revive),\nthis reconnect run executes, and combat seamlessly resumes right where it was interrupted.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t3_desc.pack(anchor="w", padx=8, pady=(4, 6))

        self.run_info_reconnect = ctk.CTkLabel(
            self.tab_reconnect,
            text="📁 Reconnect Run: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#da77f2"
        )
        self.run_info_reconnect.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_reconnect = ctk.CTkFrame(self.tab_reconnect, fg_color="transparent")
        btn_row_reconnect.pack(fill="x", padx=8, pady=4)

        self.btn_rec_reconnect = ctk.CTkButton(
            btn_row_reconnect,
            text=f"🔴 Record Reconnect Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#ae3ec9",
            hover_color="#9c36b5",
            height=38,
            command=lambda: self.toggle_recording("reconnect")
        )
        self.btn_rec_reconnect.pack(fill="x", expand=True)

        reconnect_detect_frame = ctk.CTkFrame(self.tab_reconnect, fg_color="#181a20", corner_radius=8)
        reconnect_detect_frame.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_disc_opts = ctk.CTkFrame(reconnect_detect_frame, fg_color="transparent")
        row_disc_opts.pack(fill="x", padx=12, pady=(6, 2))

        self.chk_disc = ctk.CTkCheckBox(
            row_disc_opts,
            text="Enable automatic reconnect on lost connection",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_recovery_settings_change
        )
        if self.cfg.get("enable_disconnect_recovery", True):
            self.chk_disc.select()
        else:
            self.chk_disc.deselect()
        self.chk_disc.pack(side="left")

        curr_dc_thresh = int(self.cfg.get("disconnect_threshold", 0.75) * 100)
        self.lbl_disc_thresh = ctk.CTkLabel(
            row_disc_opts,
            text=f"Sensitivity: {curr_dc_thresh}%",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_disc_thresh.pack(side="right", padx=(0, 6))

        # Rewind seconds after reconnect
        row_disc_rewind = ctk.CTkFrame(reconnect_detect_frame, fg_color="transparent")
        row_disc_rewind.pack(fill="x", padx=12, pady=(4, 6))

        lbl_dc_rewind = ctk.CTkLabel(
            row_disc_rewind,
            text="⏪ Rewind combat run after reconnect by [seconds]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbcfe8"
        )
        lbl_dc_rewind.pack(side="left")

        curr_dc_rewind = str(self.cfg.get("disconnect_rewind_seconds", 3.0))
        self.entry_disconnect_rewind = ctk.CTkEntry(
            row_disc_rewind, width=80, height=30, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_disconnect_rewind.insert(0, curr_dc_rewind)
        self.entry_disconnect_rewind.pack(side="right")
        self.entry_disconnect_rewind.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_disconnect_rewind.bind("<Return>", self._save_timing_inputs)

        # -------------------------------------------------------------
        # TAB 5: SERVER RECONNECT (PLAY AGAIN)
        # -------------------------------------------------------------
        t_sr_desc = ctk.CTkLabel(
            self.tab_server_reconnect,
            text="When disconnected to the server screen with 'Play Again', combat is PAUSED,\n"
                 "this recovery run executes (clicks 'Play Again' and re-enters), resuming combat at the exact point of interruption.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t_sr_desc.pack(anchor="w", padx=8, pady=(4, 6))

        self.run_info_server_reconnect = ctk.CTkLabel(
            self.tab_server_reconnect,
            text="📁 Server Reconnect Run: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#38bdf8"
        )
        self.run_info_server_reconnect.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_server_reconnect = ctk.CTkFrame(self.tab_server_reconnect, fg_color="transparent")
        btn_row_server_reconnect.pack(fill="x", padx=8, pady=4)

        self.btn_rec_server_reconnect = ctk.CTkButton(
            btn_row_server_reconnect,
            text=f"🔴 Record Server Reconnect Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=38,
            command=lambda: self.toggle_recording("server_reconnect")
        )
        self.btn_rec_server_reconnect.pack(fill="x", expand=True)

        sr_detect_frame = ctk.CTkFrame(self.tab_server_reconnect, fg_color="#181a20", corner_radius=8)
        sr_detect_frame.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_sr_opts = ctk.CTkFrame(sr_detect_frame, fg_color="transparent")
        row_sr_opts.pack(fill="x", padx=12, pady=(6, 2))

        self.chk_server_reconnect = ctk.CTkCheckBox(
            row_sr_opts,
            text="Enable automatic Server Reconnect (Play Again)",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_recovery_settings_change
        )
        if self.cfg.get("enable_server_reconnect_recovery", True):
            self.chk_server_reconnect.select()
        else:
            self.chk_server_reconnect.deselect()
        self.chk_server_reconnect.pack(side="left")

        curr_sr_thresh = int(self.cfg.get("server_reconnect_threshold", 0.75) * 100)
        self.lbl_server_reconnect_thresh = ctk.CTkLabel(
            row_sr_opts,
            text=f"Sensitivity: {curr_sr_thresh}%",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_server_reconnect_thresh.pack(side="right", padx=(0, 6))

        # Rewind seconds after server reconnect
        row_sr_rewind = ctk.CTkFrame(sr_detect_frame, fg_color="transparent")
        row_sr_rewind.pack(fill="x", padx=12, pady=(4, 6))

        lbl_sr_rewind = ctk.CTkLabel(
            row_sr_rewind,
            text="⏪ Rewind combat run after reconnect by [seconds]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#bae6fd"
        )
        lbl_sr_rewind.pack(side="left")

        curr_sr_rewind = str(self.cfg.get("server_reconnect_rewind_seconds", 3.0))
        self.entry_server_reconnect_rewind = ctk.CTkEntry(
            row_sr_rewind, width=80, height=30, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_server_reconnect_rewind.insert(0, curr_sr_rewind)
        self.entry_server_reconnect_rewind.pack(side="right")
        self.entry_server_reconnect_rewind.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_server_reconnect_rewind.bind("<Return>", self._save_timing_inputs)

        # -------------------------------------------------------------
        # TAB 6: TOWN / LOBBY RECOVERY
        # -------------------------------------------------------------
        t_lobby_desc = ctk.CTkLabel(
            self.tab_lobby,
            text="When the character unexpectedly lands in Town / Lobby ('Enter Dungeon' screen), combat is PAUSED,\n"
                 "this recovery run executes (returns to dungeon), resuming combat from where it left off.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t_lobby_desc.pack(anchor="w", padx=8, pady=(4, 6))

        self.run_info_lobby = ctk.CTkLabel(
            self.tab_lobby,
            text="📁 Lobby Run: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#34d399"
        )
        self.run_info_lobby.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_lobby = ctk.CTkFrame(self.tab_lobby, fg_color="transparent")
        btn_row_lobby.pack(fill="x", padx=8, pady=4)

        self.btn_rec_lobby = ctk.CTkButton(
            btn_row_lobby,
            text=f"🔴 Record Lobby Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=38,
            command=lambda: self.toggle_recording("lobby")
        )
        self.btn_rec_lobby.pack(fill="x", expand=True)

        lobby_detect_frame = ctk.CTkFrame(self.tab_lobby, fg_color="#181a20", corner_radius=8)
        lobby_detect_frame.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_lobby_opts = ctk.CTkFrame(lobby_detect_frame, fg_color="transparent")
        row_lobby_opts.pack(fill="x", padx=12, pady=(6, 2))

        self.chk_lobby = ctk.CTkCheckBox(
            row_lobby_opts,
            text="Enable automatic recovery in Lobby (Town)",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_recovery_settings_change
        )
        if self.cfg.get("enable_lobby_recovery", True):
            self.chk_lobby.select()
        else:
            self.chk_lobby.deselect()
        self.chk_lobby.pack(side="left")

        curr_lobby_thresh = int(self.cfg.get("lobby_threshold", 0.75) * 100)
        self.lbl_lobby_thresh = ctk.CTkLabel(
            row_lobby_opts,
            text=f"Sensitivity: {curr_lobby_thresh}%",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_lobby_thresh.pack(side="right", padx=(0, 6))

        # Rewind seconds after lobby run (default 0.0s)
        row_lobby_rewind = ctk.CTkFrame(lobby_detect_frame, fg_color="transparent")
        row_lobby_rewind.pack(fill="x", padx=12, pady=(4, 6))

        lbl_lobby_rewind = ctk.CTkLabel(
            row_lobby_rewind,
            text="⏪ Rewind combat run after returning from Lobby by [seconds]:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a7f3d0"
        )
        lbl_lobby_rewind.pack(side="left")

        curr_lobby_rewind = str(self.cfg.get("lobby_rewind_seconds", 0.0))
        self.entry_lobby_rewind = ctk.CTkEntry(
            row_lobby_rewind, width=80, height=30, font=ctk.CTkFont(size=13, weight="bold"), justify="center"
        )
        self.entry_lobby_rewind.insert(0, curr_lobby_rewind)
        self.entry_lobby_rewind.pack(side="right")
        self.entry_lobby_rewind.bind("<FocusOut>", self._save_timing_inputs)
        self.entry_lobby_rewind.bind("<Return>", self._save_timing_inputs)

        # -------------------------------------------------------------
        # TAB 7: DUNGEON COMPLETION (EXIT RUN)
        # -------------------------------------------------------------
        t4_desc = ctk.CTkLabel(
            self.tab_exit,
            text="When the dungeon is cleared and the results screen appears with 'Exit Dungeon',\nthe bot immediately pauses combat, executes your recorded Exit Run (clicks Exit and re-enters), and starts a fresh loop.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t4_desc.pack(anchor="w", padx=8, pady=(4, 6))

        self.run_info_exit = ctk.CTkLabel(
            self.tab_exit,
            text="📁 Exit Run: Not loaded",
            font=ctk.CTkFont(size=13),
            text_color="#38bdf8"
        )
        self.run_info_exit.pack(anchor="w", padx=8, pady=(0, 8))

        btn_row_exit = ctk.CTkFrame(self.tab_exit, fg_color="transparent")
        btn_row_exit.pack(fill="x", padx=8, pady=4)

        self.btn_rec_exit = ctk.CTkButton(
            btn_row_exit,
            text=f"🔴 Record Exit Run ({hk_rec})",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0891b2",
            hover_color="#0e7490",
            height=38,
            command=lambda: self.toggle_recording("exit")
        )
        self.btn_rec_exit.pack(fill="x", expand=True)

        exit_detect_frame = ctk.CTkFrame(self.tab_exit, fg_color="#181a20", corner_radius=8)
        exit_detect_frame.pack(fill="x", padx=8, pady=(12, 6), ipady=4)

        row_exit_opts = ctk.CTkFrame(exit_detect_frame, fg_color="transparent")
        row_exit_opts.pack(fill="x", padx=12, pady=(6, 6))

        self.chk_exit = ctk.CTkCheckBox(
            row_exit_opts,
            text="Enable automatic Exit Run on dungeon completion",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_recovery_settings_change
        )
        if self.cfg.get("enable_dungeon_complete_recovery", True):
            self.chk_exit.select()
        else:
            self.chk_exit.deselect()
        self.chk_exit.pack(side="left")

        curr_exit_thresh = int(self.cfg.get("dungeon_complete_threshold", 0.75) * 100)
        self.lbl_exit_thresh = ctk.CTkLabel(
            row_exit_opts,
            text=f"Sensitivity: {curr_exit_thresh}%",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_exit_thresh.pack(side="right", padx=(0, 6))

        # -------------------------------------------------------------
        # TAB 8: KEYBIND SETTINGS (HOTKEYS)
        # -------------------------------------------------------------
        t5_desc = ctk.CTkLabel(
            self.tab_keybinds,
            text="Click [Change Key] and press any key on your keyboard.\nAll hotkeys function globally in real-time during Dungeon Blitz gameplay.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        t5_desc.pack(anchor="w", padx=8, pady=(4, 8))

        keybind_card = ctk.CTkFrame(self.tab_keybinds, fg_color="#181a20", corner_radius=10)
        keybind_card.pack(fill="x", padx=8, pady=4, ipady=6)

        # Build list of keybinding rows
        self._build_keybind_row(keybind_card, "puzzle_record_step", "🧩 In-Game Builder [F1]: Record Movement Step (Start/Stop):")
        self._build_keybind_row(keybind_card, "puzzle_automat_step", "🤖 In-Game Builder [F2]: Add & Trigger AUTO-MOB Step:")
        self._build_keybind_row(keybind_card, "record_active", "Start / Stop Recording (Active Tab):")
        self._build_keybind_row(keybind_card, "bot_toggle", "Start / Pause Bot Loop:")
        self._build_keybind_row(keybind_card, "emergency_stop", "🛑 Emergency Stop Bot (Emergency Stop + ESC):")
        self._build_keybind_row(keybind_card, "record_main", "Direct Key: Record Main Combat Run:")
        self._build_keybind_row(keybind_card, "record_revive", "Direct Key: Record Revive Run (Angel):", allow_clear=True)
        self._build_keybind_row(keybind_card, "record_reconnect", "Direct Key: Record Reconnect Run (Lost Conn):", allow_clear=True)
        self._build_keybind_row(keybind_card, "record_server_reconnect", "Direct Key: Record Server Reconnect (Play Again):", allow_clear=True)
        self._build_keybind_row(keybind_card, "record_lobby", "Direct Key: Record Lobby Run (Town):", allow_clear=True)
        self._build_keybind_row(keybind_card, "record_exit", "Direct Key: Record Exit Run (Dungeon Exit):", allow_clear=True)

        btn_reset_keys = ctk.CTkButton(
            self.tab_keybinds,
            text="🔄 Reset Default Hotkeys (F1, F2, F7, F8, F9)",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#1e293b",
            height=32,
            command=self._reset_default_hotkeys
        )
        btn_reset_keys.pack(pady=10)

        # Update summary labels for the newly created secondary tab cards
        if "run_info_revive" in self.__dict__:
            self.run_info_revive.configure(text=self._get_run_summary(self.bot.get_run_filepath("revive")))
        if "run_info_reconnect" in self.__dict__:
            self.run_info_reconnect.configure(text=self._get_run_summary(self.bot.get_run_filepath("reconnect")))
        if "run_info_server_reconnect" in self.__dict__:
            self.run_info_server_reconnect.configure(text=self._get_run_summary(self.bot.get_run_filepath("server_reconnect")))
        if "run_info_lobby" in self.__dict__:
            self.run_info_lobby.configure(text=self._get_run_summary(self.bot.get_run_filepath("lobby")))
        if "run_info_exit" in self.__dict__:
            self.run_info_exit.configure(text=self._get_run_summary(self.bot.get_run_filepath("exit")))

    def _build_keybind_row(self, parent, action_id: str, label_text: str, allow_clear: bool = False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)

        lbl = ctk.CTkLabel(
            row,
            text=label_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        lbl.pack(side="left")

        curr_key = self.cfg.get("hotkeys", {}).get(action_id, "")
        key_display = f"[{curr_key.upper()}]" if curr_key else "[ Not set ]"

        lbl_badge = ctk.CTkLabel(
            row,
            text=key_display,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            fg_color="#2b303c",
            text_color="#60a5fa" if curr_key else "#64748b",
            corner_radius=6,
            width=90,
            pady=4
        )
        lbl_badge.pack(side="right", padx=(8, 0))

        btn_change = ctk.CTkButton(
            row,
            text="✏️ Change",
            font=ctk.CTkFont(size=11),
            width=70,
            height=28,
            fg_color="#1971c2",
            hover_color="#1864ab",
            command=lambda: self._open_keybind_dialog(action_id, label_text)
        )
        btn_change.pack(side="right", padx=(8, 0))

        if allow_clear:
            btn_clear = ctk.CTkButton(
                row,
                text="✕ Clear",
                font=ctk.CTkFont(size=11),
                width=65,
                height=28,
                fg_color="#334155",
                hover_color="#475569",
                command=lambda: self._clear_keybind(action_id)
            )
            btn_clear.pack(side="right")

        self.keybind_rows[action_id] = {
            "badge": lbl_badge,
            "label_text": label_text
        }

    def _open_keybind_dialog(self, action_id: str, label_text: str):
        curr_key = self.cfg.get("hotkeys", {}).get(action_id, "")
        def on_key_captured(new_key):
            self.cfg.setdefault("hotkeys", {})[action_id] = new_key
            config.save_config(self.cfg)
            self._update_keybind_ui()
            self.register_hotkeys()
            self._log(f"🔑 Hotkey for '{label_text}' set to: [{new_key.upper()}]")

        KeybindDialog(self, label_text, curr_key, on_key_captured)

    def _clear_keybind(self, action_id: str):
        self.cfg.setdefault("hotkeys", {})[action_id] = ""
        config.save_config(self.cfg)
        self._update_keybind_ui()
        self.register_hotkeys()
        self._log(f"🔑 Hotkey for '{self.keybind_rows[action_id]['label_text']}' cleared.")

    def _reset_default_hotkeys(self):
        self.cfg["hotkeys"] = config.DEFAULT_HOTKEYS.copy()
        config.save_config(self.cfg)
        self._update_keybind_ui()
        self.register_hotkeys()
        self._log("🔄 Hotkeys reset to defaults (F1, F2, F7, F8, F9).")

    def _update_keybind_ui(self):
        hotkeys = self.cfg.get("hotkeys", {})
        for aid, data in self.keybind_rows.items():
            k = hotkeys.get(aid, "")
            data["badge"].configure(
                text=f"[{k.upper()}]" if k else "[ Not set ]",
                text_color="#60a5fa" if k else "#64748b"
            )

        hk_rec = hotkeys.get("record_active", "f7").upper()
        hk_bot = hotkeys.get("bot_toggle", "f8").upper()
        hk_stop = hotkeys.get("emergency_stop", "f9").upper()

        self.btn_rec_main.configure(text=f"🔴 Record Run ({hk_rec})")
        self.btn_rec_revive.configure(text=f"🔴 Record Revive Run ({hk_rec})")
        self.btn_rec_reconnect.configure(text=f"🔴 Record Reconnect Run ({hk_rec})")
        self.btn_rec_server_reconnect.configure(text=f"🔴 Record Server Reconnect Run ({hk_rec})")
        self.btn_rec_lobby.configure(text=f"🔴 Record Lobby Run ({hk_rec})")
        self.btn_rec_exit.configure(text=f"🔴 Record Exit Run ({hk_rec})")
        self.btn_start_bot.configure(text=f"⚡ START AUTOMATIC BOT ({hk_bot})")
        self.btn_emergency_stop.configure(text=f"🛑 EMERGENCY STOP ({hk_stop})")

    # --- DYNAMIC GLOBAL HOTKEY REGISTRATION ---
    def queue_action(self, func):
        """Thread-safe dispatch of a callable to the Tkinter main thread."""
        self._event_queue.put(("action", func))

    def register_hotkeys(self):
        """Re-registers all global Windows hotkeys based on current settings."""
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        hotkeys = self.cfg.get("hotkeys", {})
        hk_rec = hotkeys.get("record_active", "f7")
        hk_bot = hotkeys.get("bot_toggle", "f8")
        hk_stop = hotkeys.get("emergency_stop", "f9")
        hk_puz_rec = hotkeys.get("puzzle_record_step", "f1")
        hk_puz_auto = hotkeys.get("puzzle_automat_step", "f2")
        hk_rec_main = hotkeys.get("record_main", "")
        hk_rec_revive = hotkeys.get("record_revive", "")
        hk_rec_reconnect = hotkeys.get("record_reconnect", "")
        hk_rec_sr = hotkeys.get("record_server_reconnect", "")
        hk_rec_lobby = hotkeys.get("record_lobby", "")
        hk_rec_exit = hotkeys.get("record_exit", "")

        # 0. In-game Puzzle building hotkeys: [F1] Record movement step | [F2] Add & run 🤖 AUTOMAT step
        if hk_puz_rec:
            try:
                keyboard.add_hotkey(hk_puz_rec, lambda: self.queue_action(self.handle_f1_puzzle_record), suppress=False)
            except Exception as e:
                self._log(f"⚠️ Failed to register hotkey [{hk_puz_rec}]: {e}")

        if hk_puz_auto:
            try:
                keyboard.add_hotkey(hk_puz_auto, lambda: self.queue_action(self.handle_f2_puzzle_automat), suppress=False)
            except Exception as e:
                self._log(f"⚠️ Failed to register hotkey [{hk_puz_auto}]: {e}")

        # 1. Active record hotkey
        if hk_rec:
            try:
                keyboard.add_hotkey(hk_rec, lambda: self.queue_action(self.toggle_recording_active_slot), suppress=False)
            except Exception as e:
                self._log(f"⚠️ Failed to register hotkey [{hk_rec}]: {e}")

        # 2. Bot toggle hotkey
        if hk_bot:
            try:
                keyboard.add_hotkey(hk_bot, lambda: self.queue_action(self.toggle_bot_loop), suppress=False)
            except Exception as e:
                self._log(f"⚠️ Failed to register hotkey [{hk_bot}]: {e}")

        # 3. Emergency stop hotkey
        if hk_stop:
            try:
                keyboard.add_hotkey(hk_stop, lambda: self.queue_action(self.emergency_stop), suppress=False)
            except Exception as e:
                self._log(f"⚠️ Failed to register hotkey [{hk_stop}]: {e}")

        # Always register ESC as emergency stop for maximum safety
        try:
            keyboard.add_hotkey("esc", lambda: self.queue_action(self.emergency_stop), suppress=False)
        except Exception:
            pass

        # 4. Optional direct record hotkeys
        if hk_rec_main and hk_rec_main != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_main, lambda: self.queue_action(lambda: self.toggle_recording("main")), suppress=False)
            except Exception:
                pass

        if hk_rec_revive and hk_rec_revive != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_revive, lambda: self.queue_action(lambda: self.toggle_recording("revive")), suppress=False)
            except Exception:
                pass

        if hk_rec_reconnect and hk_rec_reconnect != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_reconnect, lambda: self.queue_action(lambda: self.toggle_recording("reconnect")), suppress=False)
            except Exception:
                pass

        if hk_rec_sr and hk_rec_sr != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_sr, lambda: self.queue_action(lambda: self.toggle_recording("server_reconnect")), suppress=False)
            except Exception:
                pass

        if hk_rec_lobby and hk_rec_lobby != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_lobby, lambda: self.queue_action(lambda: self.toggle_recording("lobby")), suppress=False)
            except Exception:
                pass

        if hk_rec_exit and hk_rec_exit != hk_rec:
            try:
                keyboard.add_hotkey(hk_rec_exit, lambda: self.queue_action(lambda: self.toggle_recording("exit")), suppress=False)
            except Exception:
                pass

    def _on_tab_changed(self):
        """Switches the active recording slot based on the currently selected tab."""
        if not getattr(self, "_secondary_tabs_built", False):
            self._build_secondary_tabs()

        curr = self.tabview.get()
        if curr in ("Auto-Mob", "Automat"):
            self.active_slot = "main"
            self._log("📌 Selected tab: Auto-Mob (Autonomous mob search, movement, and skills 1,3,4,5).")
        elif curr == "Heal":
            self.active_slot = "main"
            self._log("📌 Selected tab: Heal (Automatic healing / Potion).")
        elif curr == "Revive":
            self.active_slot = "revive"
            self._log("📌 Selected tab: Revive (Death Recovery). Recording targets Revive Run.")
        elif curr == "Server":
            self.active_slot = "server_reconnect"
            self._log("📌 Selected tab: Server (Server Reconnect). Recording targets Server Reconnect Run.")
        elif curr == "Reconnect":
            self.active_slot = "reconnect"
            self._log("📌 Selected tab: Reconnect (Lost Connection). Recording targets Reconnect Run.")
        elif curr == "Lobby":
            self.active_slot = "lobby"
            self._log("📌 Selected tab: Lobby (Town Recovery). Recording targets Lobby Run.")
        elif curr == "Exit":
            self.active_slot = "exit"
            self._log("📌 Selected tab: Exit (Dungeon Complete). Recording targets Exit Run.")
        elif curr in ("Keybinds", "Hotkeys"):
            self._log("📌 Selected tab: Keybinds (Hotkey configurations).")
        else:
            self.active_slot = "main"
            run_name = self.cfg.get("selected_combat_run", "default_run")
            self._log(f"📌 Selected tab: Combat [{run_name}].")

    # --- PROFILE MANAGEMENT ---
    def _on_combat_run_selected(self, choice: str):
        self.cfg["selected_combat_run"] = choice
        self.bot.config["selected_combat_run"] = choice
        config.save_config(self.cfg)
        self._refresh_all_run_infos()

        self._log(f"📁 Active combat run profile selected: [{choice}]")

    def _create_new_run_dialog(self):
        dialog = ctk.CTkInputDialog(
            text="Enter name for new combat run (e.g. boss_farm, glades_2):",
            title="New Combat Run"
        )
        name = dialog.get_input()
        if name and name.strip():
            clean = config.create_combat_run(name.strip())
            all_runs = config.list_combat_runs()
            self.opt_combat_runs.configure(values=all_runs)
            self.opt_combat_runs.set(clean)
            self._on_combat_run_selected(clean)

    def _delete_current_run(self):
        curr = self.cfg.get("selected_combat_run", "default_run")
        all_runs = config.list_combat_runs()
        if len(all_runs) <= 1:
            self._log("⚠️ You cannot delete the only remaining combat run.")
            return

        success = config.delete_combat_run(curr)
        if success:
            self._log(f"🗑 Run '{curr}' was deleted.")
            remaining = config.list_combat_runs()
            self.opt_combat_runs.configure(values=remaining)
            self.opt_combat_runs.set(remaining[0])
            self._on_combat_run_selected(remaining[0])

    def _open_runs_folder(self):
        try:
            os.startfile(os.path.abspath(config.RUNS_DIR))
        except Exception as e:
            self._log(f"Error opening folder: {e}")

    # --- UI HELPERS ---
    def _log(self, text: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _poll_event_queue(self):
        try:
            # Direct hardware ESC polling (works even when low-level keyboard hook is congested)
            if hasattr(self, "bot") and self.bot.state != BotState.IDLE and is_hardware_esc_pressed():
                now_esc = time.perf_counter()
                if now_esc - getattr(self, "_last_hw_esc_time", 0.0) > 0.45:
                    self._last_hw_esc_time = now_esc
                    self.emergency_stop()

            # Sync Automat HUD Overlay above the game (shows when Automat turns ON and when it turns OFF)
            if hasattr(self, "bot") and hasattr(self, "automat_overlay"):
                curr_auto = bool(getattr(self.bot, "automat_hud_active", False))
                prev_auto = getattr(self, "_prev_automat_hud_active", False)
                if curr_auto and not prev_auto:
                    self._prev_automat_hud_active = True
                    self.automat_overlay.show(
                        get_info_func=lambda: {
                            "title": self.bot.automat_hud_title,
                            "status": self.bot.automat_hud_status,
                            "hint": self.bot.automat_hud_hint
                        }
                    )
                elif not curr_auto and prev_auto:
                    self._prev_automat_hud_active = False
                    fin = getattr(self.bot, "automat_hud_last_finish", None) or {}
                    self.automat_overlay.finish(
                        duration=fin.get("duration", 0.0),
                        title_text=fin.get("title", "🤖 AUTO-MOB OFF"),
                        status_text=fin.get("status", "Auto-Mob finished"),
                        hint_text=fin.get("hint", "")
                    )

            while not self._event_queue.empty():
                item = self._event_queue.get_nowait()
                itype = item[0]
                if itype == "log":
                    self._log(item[1])
                elif itype == "state":
                    st, dt = item[1]
                    self._apply_state(st, dt)
                elif itype == "action":
                    item[1]()
        except Exception:
            pass
        finally:
            try:
                poll_delay = 25 if (hasattr(self, "bot") and self.bot.state != BotState.IDLE) else 45
                self.after(poll_delay, self._poll_event_queue)
            except Exception:
                pass

    def _on_bot_log(self, formatted_message: str):
        self._event_queue.put(("log", formatted_message))

    def _on_bot_state_change(self, state: str, details: str):
        self._event_queue.put(("state", (state, details)))

    def _apply_state(self, state: str, details: str):
        combat_name = self.cfg.get("selected_combat_run", "default_run")
        hk_rec = self.cfg.get("hotkeys", {}).get("record_active", "f7").upper()

        if state == BotState.IDLE:
            self.status_badge.configure(
                text=f"STATUS: READY (IDLE) - {details}",
                fg_color="#2b303c",
                text_color="#69db7c"
            )
            self.btn_rec_main.configure(text=f"🔴 Record Run ({hk_rec})", fg_color="#e03131", hover_color="#c92a2a")
            self.btn_rec_revive.configure(text=f"🔴 Record Revive Run ({hk_rec})", fg_color="#f08c00", hover_color="#d97706")
            self.btn_rec_reconnect.configure(text=f"🔴 Record Reconnect Run ({hk_rec})", fg_color="#ae3ec9", hover_color="#9c36b5")
            self.btn_rec_server_reconnect.configure(text=f"🔴 Record Server Reconnect Run ({hk_rec})", fg_color="#0284c7", hover_color="#0369a1")
            self.btn_rec_lobby.configure(text=f"🔴 Record Lobby Run ({hk_rec})", fg_color="#059669", hover_color="#047857")
            self.btn_rec_exit.configure(text=f"🔴 Record Exit Run ({hk_rec})", fg_color="#0891b2", hover_color="#0e7490")
            self.btn_start_bot.configure(text=f"⚡ START AUTOMATIC BOT ({self.cfg.get('hotkeys', {}).get('bot_toggle', 'f8').upper()})", fg_color="#2b8a3e", hover_color="#237032")
            if hasattr(self, "btn_toggle_automat"):
                self.btn_toggle_automat.configure(text="🤖 START AUTO-MOB MODE", fg_color="#059669", hover_color="#047857")
        elif state == BotState.RECORDING:
            self.status_badge.configure(
                text=f"STATUS: 🔴 RECORDING RUN - {details}",
                fg_color="#491217",
                text_color="#ff8787"
            )
            slot = self.bot.current_recording_slot
            if slot == "main":
                self.btn_rec_main.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
            elif slot == "revive":
                self.btn_rec_revive.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
            elif slot == "reconnect":
                self.btn_rec_reconnect.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
            elif slot == "server_reconnect":
                self.btn_rec_server_reconnect.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
            elif slot == "lobby":
                self.btn_rec_lobby.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
            elif slot == "exit":
                self.btn_rec_exit.configure(text=f"⏹ STOP RECORDING ({hk_rec})", fg_color="#c92a2a", hover_color="#a61e1e")
        elif state == BotState.COUNTDOWN:
            self.status_badge.configure(
                text=f"STATUS: ⏳ {details}",
                fg_color="#402d08",
                text_color="#ffd43b"
            )
            self.btn_start_bot.configure(text=f"⏸ PAUSE BOT ({self.cfg.get('hotkeys', {}).get('bot_toggle', 'f8').upper()})", fg_color="#d97706", hover_color="#b45309")
            if hasattr(self, "btn_toggle_automat"):
                self.btn_toggle_automat.configure(text="⏹ STOP AUTO-MOB MODE", fg_color="#d97706", hover_color="#b45309")
        elif state == BotState.EXECUTING_RUN:
            self.status_badge.configure(
                text=f"STATUS: ⚔️ {details}",
                fg_color="#183e20",
                text_color="#8ce99a"
            )
            self.btn_start_bot.configure(text=f"⏸ PAUSE BOT ({self.cfg.get('hotkeys', {}).get('bot_toggle', 'f8').upper()})", fg_color="#d97706", hover_color="#b45309")
            if hasattr(self, "btn_toggle_automat"):
                self.btn_toggle_automat.configure(text="⏹ STOP AUTO-MOB MODE", fg_color="#d97706", hover_color="#b45309")
        elif state == BotState.WAITING_FOR_SPAWN:
            self.status_badge.configure(
                text=f"STATUS: ⏳ {details}",
                fg_color="#301c42",
                text_color="#da77f2"
            )
            self.btn_start_bot.configure(text=f"⏸ PAUSE BOT ({self.cfg.get('hotkeys', {}).get('bot_toggle', 'f8').upper()})", fg_color="#d97706", hover_color="#b45309")
        elif state == BotState.RECOVERING_DEATH:
            self.status_badge.configure(
                text=f"STATUS: 👼 {details}",
                fg_color="#663c00",
                text_color="#ffd43b"
            )
        elif state == BotState.RECOVERING_DISCONNECT:
            self.status_badge.configure(
                text=f"STATUS: 🔌 {details}",
                fg_color="#4a0f4a",
                text_color="#f08cff"
            )
        elif state == BotState.RECOVERING_SERVER_RECONNECT:
            self.status_badge.configure(
                text=f"STATUS: 🌐 {details}",
                fg_color="#034977",
                text_color="#7dd3fc"
            )
        elif state == BotState.RECOVERING_LOBBY:
            self.status_badge.configure(
                text=f"STATUS: 🏰 {details}",
                fg_color="#064e3b",
                text_color="#6ee7b7"
            )
        elif state == BotState.RECOVERING_EXIT:
            self.status_badge.configure(
                text=f"STATUS: 🚪 {details}",
                fg_color="#0b3838",
                text_color="#67e8f9"
            )

    def _get_run_summary(self, filepath: str) -> str:
        if not hasattr(self, "_run_summary_cache"):
            self._run_summary_cache = {}

        if os.path.exists(filepath):
            try:
                mtime = os.path.getmtime(filepath)
                cached = self._run_summary_cache.get(filepath)
                if cached and cached[0] == mtime:
                    return cached[1]

                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                dur = data.get("duration", 0)
                cnt = data.get("event_count", len(data.get("events", [])))
                created = data.get("created_at", "")
                name = os.path.basename(filepath)
                is_seg = bool(data.get("is_segmented") and data.get("segments"))
                if is_seg:
                    segs = data.get("segments", [])
                    total_dur = round(sum(s.get("duration", 0.0) for s in segs), 1)
                    total_cnt = sum(s.get("event_count", len(s.get("events", []))) for s in segs)
                    summary = f"📁 {name} [🧩 Puzzle: {len(segs)} steps | Duration: {total_dur}s | Actions: {total_cnt}]"
                else:
                    summary = f"📁 {name} (Duration: {dur}s, Actions: {cnt}) [{created}]"
                self._run_summary_cache[filepath] = (mtime, summary)
                return summary
            except Exception:
                return f"📁 {filepath} (Error reading file)"
        return f"⚠️ File '{os.path.basename(filepath)}' does not exist yet (click record)."

    def _refresh_all_run_infos(self):
        if "run_info_main" in self.__dict__:
            self.run_info_main.configure(text=self._get_run_summary(self.bot.get_run_filepath("main")))
        if "run_info_revive" in self.__dict__:
            self.run_info_revive.configure(text=self._get_run_summary(self.bot.get_run_filepath("revive")))
        if "run_info_reconnect" in self.__dict__:
            self.run_info_reconnect.configure(text=self._get_run_summary(self.bot.get_run_filepath("reconnect")))
        if "run_info_server_reconnect" in self.__dict__:
            self.run_info_server_reconnect.configure(text=self._get_run_summary(self.bot.get_run_filepath("server_reconnect")))
        if "run_info_lobby" in self.__dict__:
            self.run_info_lobby.configure(text=self._get_run_summary(self.bot.get_run_filepath("lobby")))
        if "run_info_exit" in self.__dict__:
            self.run_info_exit.configure(text=self._get_run_summary(self.bot.get_run_filepath("exit")))
        self._refresh_puzzle_ui()

    # --- PUZZLE SEGMENTS UI & MANAGEMENT ---
    def _refresh_puzzle_ui(self):
        if not hasattr(self, "puzzle_list_container"):
            return

        for w in self.puzzle_list_container.winfo_children():
            w.destroy()

        current_run = self.cfg.get("selected_combat_run", "default_run")
        data = config.load_combat_run_data(current_run)
        is_segmented = bool(data.get("is_segmented") and data.get("segments"))
        segments = data.get("segments", []) if is_segmented else []
        all_events = data.get("events", [])

        if not is_segmented or not segments:
            empty_box = ctk.CTkFrame(self.puzzle_list_container, fg_color="#141824", corner_radius=8)
            empty_box.pack(fill="x", pady=4, ipady=6)

            if all_events:
                dur = data.get("duration", 0)
                cnt = len(all_events)
                msg = f"ℹ️ Profile [{current_run}] has a flat run (Duration: {dur}s, Actions: {cnt}). You can slice it or convert it to puzzle:"
                lbl = ctk.CTkLabel(empty_box, text=msg, font=ctk.CTkFont(size=12), text_color="#cbd5e1")
                lbl.pack(anchor="w", padx=10, pady=(4, 6))

                row_actions = ctk.CTkFrame(empty_box, fg_color="transparent")
                row_actions.pack(fill="x", padx=10, pady=2)

                btn_convert = ctk.CTkButton(
                    row_actions,
                    text="🧩 Convert to Step 1 (Enables adding more modular steps)",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#1d4ed8",
                    hover_color="#1e40af",
                    height=28,
                    command=self._puzzle_convert_flat
                )
                btn_convert.pack(side="left", padx=(0, 8))

                btn_split_now = ctk.CTkButton(
                    row_actions,
                    text="✂️ Slice into Seconds (e.g. 30, 60)",
                    font=ctk.CTkFont(size=11),
                    fg_color="#0891b2",
                    hover_color="#0e7490",
                    height=28,
                    command=self._puzzle_split_dialog
                )
                btn_split_now.pack(side="left")
            else:
                msg = (
                    f"ℹ️ No run recorded yet for profile [{current_run}].\n"
                    f"💡 In-game: press [F1] to record movement to mobs -> at mobs press [F2] (saves movement, adds 🤖 AUTO-MOB & clears room) -> after clearing press [F1] again!"
                )
                lbl = ctk.CTkLabel(empty_box, text=msg, font=ctk.CTkFont(size=12), text_color="#38bdf8", justify="left")
                lbl.pack(anchor="w", padx=10, pady=(6, 8))
            return

        total_time = round(sum(s.get("duration", 0.0) for s in segments), 1)
        total_actions = sum(s.get("event_count", len(s.get("events", []))) for s in segments)
        auto_cnt = sum(1 for s in segments if s.get("type") == "automat")
        summary_lbl = ctk.CTkLabel(
            self.puzzle_list_container,
            text=f"Puzzle contains {len(segments)} steps ({auto_cnt}x 🤖 AUTO-MOB | Recorded movement: {total_time}s, {total_actions} actions) — ✋ Drag and drop steps to reorder:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#93c5fd"
        )
        summary_lbl.pack(anchor="w", pady=(0, 4))

        self._close_puzzle_drag_ghost()
        self._drag_puzzle_state = None
        self._puzzle_cards = []

        for idx, seg in enumerate(segments):
            is_auto_seg = (seg.get("type") == "automat")
            base_fg = "#092e26" if is_auto_seg else "#1e2330"
            card = ctk.CTkFrame(
                self.puzzle_list_container,
                fg_color=base_fg,
                corner_radius=6,
                border_width=1,
                border_color="#10b981" if is_auto_seg else "#2b303c",
                cursor="hand2"
            )
            card.pack(fill="x", pady=2, ipady=2)

            left_frame = ctk.CTkFrame(card, fg_color="transparent", cursor="hand2")
            left_frame.pack(side="left", padx=8, pady=4, fill="x", expand=True)

            drag_lbl = ctk.CTkLabel(
                left_frame,
                text="⠿",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#64748b",
                cursor="hand2"
            )
            drag_lbl.pack(side="left", padx=(0, 6))

            badge = ctk.CTkLabel(
                left_frame,
                text=f" 🤖 #{idx + 1} " if is_auto_seg else f" #{idx + 1} ",
                fg_color="#059669" if is_auto_seg else "#2563eb",
                text_color="#ffffff",
                corner_radius=4,
                font=ctk.CTkFont(size=11, weight="bold"),
                cursor="hand2"
            )
            badge.pack(side="left", padx=(0, 8))

            seg_title = seg.get("name", f"Step {idx + 1}")
            name_lbl = ctk.CTkLabel(
                left_frame,
                text=seg_title,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#6ee7b7" if is_auto_seg else "#f8f9fa",
                cursor="hand2"
            )
            name_lbl.pack(side="left", padx=(0, 10))

            is_stand = (str(self.cfg.get("automat_move_key", "d")).lower().strip() == "stand")
            info_text = (
                "🤖 Clear room (Stand: holds position, resumes run after kill)"
                if (is_auto_seg and is_stand)
                else "🤖 Clear room (advances to mobs + returns to start position)"
                if is_auto_seg
                else f"⏱ {seg.get('duration', 0.0)}s  •  {seg.get('event_count', len(seg.get('events', [])))} actions"
            )
            info_lbl = ctk.CTkLabel(
                left_frame,
                text=info_text,
                font=ctk.CTkFont(size=11),
                text_color="#a7f3d0" if is_auto_seg else "#94a3b8",
                cursor="hand2"
            )
            info_lbl.pack(side="left")

            card_item = {
                "card": card,
                "badge_lbl": badge,
                "index": idx,
                "seg": seg,
                "title": seg_title,
                "is_auto": is_auto_seg,
                "base_fg": base_fg,
                "base_border": "#10b981" if is_auto_seg else "#2b303c",
                "cy": 0.0
            }

            right_frame = ctk.CTkFrame(card, fg_color="transparent")
            right_frame.pack(side="right", padx=6, pady=4)

            if not is_auto_seg:
                btn_rec = ctk.CTkButton(
                    right_frame,
                    text="🔴 Record",
                    width=65,
                    height=26,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#e03131",
                    hover_color="#c92a2a",
                    command=lambda it=card_item: self._record_puzzle_segment(it["index"], it["seg"].get("name"))
                )
                btn_rec.pack(side="left", padx=2)

                btn_trim = ctk.CTkButton(
                    right_frame,
                    text="✂",
                    width=28,
                    height=26,
                    font=ctk.CTkFont(size=11),
                    fg_color="#0891b2",
                    hover_color="#0e7490",
                    command=lambda it=card_item: self._trim_puzzle_segment_dialog(it["index"], it["seg"].get("name"), it["seg"].get("duration", 0.0))
                )
                btn_trim.pack(side="left", padx=2)

            btn_rename = ctk.CTkButton(
                right_frame,
                text="✏",
                width=28,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#475569",
                hover_color="#334155",
                command=lambda it=card_item: self._rename_puzzle_segment_dialog(it["index"], it["seg"].get("name"))
            )
            btn_rename.pack(side="left", padx=2)

            btn_del = ctk.CTkButton(
                right_frame,
                text="🗑",
                width=26,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#991b1b",
                hover_color="#7f1d1d",
                command=lambda it=card_item: self._delete_puzzle_segment(it["index"])
            )
            btn_del.pack(side="left", padx=(2, 0))

            # Bind drag-and-drop events using dynamic card_item['index'] so reordered cards always use their updated slot
            for drag_w in (card, left_frame, drag_lbl, badge, name_lbl, info_lbl):
                drag_w.bind("<ButtonPress-1>", lambda e, it=card_item: self._on_puzzle_drag_start(e, it["index"], it["title"], it["is_auto"]))
                drag_w.bind("<B1-Motion>", self._on_puzzle_drag_motion)
                drag_w.bind("<ButtonRelease-1>", self._on_puzzle_drag_release)

            self._puzzle_cards.append(card_item)

    def _on_puzzle_drag_start(self, event, index: int, seg_title: str, is_auto: bool):
        """Initiates high-performance drag-and-drop of a Puzzle step card."""
        cards = self.__dict__.get("_puzzle_cards")
        if not cards or len(cards) <= 1:
            self._drag_puzzle_state = None
            return

        self._close_puzzle_drag_ghost()

        # Precompute Y center positions of all cards in memory once to eliminate blocking winfo queries during drag
        for item in cards:
            c = item["card"]
            try:
                item["cy"] = c.winfo_rooty() + (c.winfo_height() / 2.0)
            except Exception:
                item["cy"] = 0.0

        ghost = ctk.CTkToplevel(self)
        ghost.overrideredirect(True)
        ghost.attributes("-topmost", True)
        try:
            ghost.attributes("-alpha", 0.90)
        except Exception:
            pass

        if "_puzzle_ghost_list" not in self.__dict__:
            self._puzzle_ghost_list = []
        self._puzzle_ghost_list.append(ghost)

        w = 340
        h = 36
        gx = event.x_root + 18
        gy = event.y_root + 14
        ghost.geometry(f"{w}x{h}+{gx}+{gy}")

        g_frame = ctk.CTkFrame(
            ghost,
            fg_color="#065f46" if is_auto else "#1e3a8a",
            border_color="#38bdf8",
            border_width=2,
            corner_radius=8
        )
        g_frame.pack(fill="both", expand=True)

        g_lbl = ctk.CTkLabel(
            g_frame,
            text=f"✋ Moving #{index + 1}: {seg_title}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff"
        )
        g_lbl.pack(padx=12, pady=6, anchor="w")

        for gw in (ghost, g_frame, g_lbl):
            gw.bind("<ButtonRelease-1>", self._on_puzzle_drag_release)

        self._drag_puzzle_state = {
            "from_index": index,
            "target_index": index,
            "title": seg_title,
            "ghost": ghost,
            "g_lbl": g_lbl,
            "last_gx": gx,
            "last_gy": gy
        }

        # Highlight dragged source card
        if 0 <= index < len(cards):
            cards[index]["card"].configure(border_width=2, border_color="#38bdf8")

    def _on_puzzle_drag_motion(self, event):
        """High-performance drag motion: dirty-checked, throttled, and zero blocking Win32/Tk queries."""
        st = self.__dict__.get("_drag_puzzle_state")
        cards = self.__dict__.get("_puzzle_cards")
        if not st or not cards:
            return

        # Update ghost position only if cursor moved by at least 2px (avoids flooding DWM compositor)
        ghost = st.get("ghost")
        if ghost:
            gx = event.x_root + 18
            gy = event.y_root + 14
            if abs(gx - st.get("last_gx", 0)) >= 2 or abs(gy - st.get("last_gy", 0)) >= 2:
                st["last_gx"] = gx
                st["last_gy"] = gy
                try:
                    ghost.geometry(f"+{gx}+{gy}")
                except Exception:
                    pass

        # Find closest card slot using precomputed in-memory Y centers (pure math in microseconds)
        mouse_y = event.y_root
        best_idx = st["from_index"]
        min_dist = float("inf")

        for item in cards:
            dist = abs(mouse_y - item.get("cy", mouse_y))
            if dist < min_dist:
                min_dist = dist
                best_idx = item["index"]

        prev_target = st.get("target_index", st["from_index"])
        if best_idx == prev_target:
            return # ZERO UI overhead as long as cursor hovers within the same card!

        # Slot changed: update state and re-render only the affected cards
        st["target_index"] = best_idx
        g_lbl = st.get("g_lbl")
        if g_lbl:
            try:
                if best_idx != st["from_index"]:
                    g_lbl.configure(text=f"✋ Move #{st['from_index'] + 1} ➔ to position #{best_idx + 1} ({st['title']})")
                else:
                    g_lbl.configure(text=f"✋ Moving #{st['from_index'] + 1}: {st['title']}")
            except Exception:
                pass

        # Restore previous target card (if not the dragged source card)
        if 0 <= prev_target < len(cards) and prev_target != st["from_index"]:
            p_item = cards[prev_target]
            p_item["card"].configure(
                border_width=1,
                border_color=p_item["base_border"],
                fg_color=p_item["base_fg"]
            )

        # Highlight new target drop card (if not the dragged source card)
        if 0 <= best_idx < len(cards) and best_idx != st["from_index"]:
            cards[best_idx]["card"].configure(
                border_width=2,
                border_color="#facc15",
                fg_color="#2a2f3d"
            )

    def _on_puzzle_drag_release(self, event=None):
        """Completes the drag-and-drop operation with instant single-card repacking and guaranteed ghost cleanup."""
        st = self.__dict__.get("_drag_puzzle_state")
        # IMPORTANT: destroy ghost BEFORE clearing _drag_puzzle_state!
        self._close_puzzle_drag_ghost()
        self._drag_puzzle_state = None

        if not st:
            return

        cards = self.__dict__.get("_puzzle_cards")
        if not cards:
            return

        from_idx = st.get("from_index", 0)
        to_idx = st.get("target_index", from_idx)
        seg_title = st.get("title", "")

        if from_idx != to_idx and 0 <= from_idx < len(cards) and 0 <= to_idx < len(cards):
            current_run = self.cfg.get("selected_combat_run", "default_run")
            config.reorder_segment_in_run(current_run, from_idx, to_idx)

            # Reorder list in memory
            item = cards.pop(from_idx)
            cards.insert(to_idx, item)

            # Visually move ONLY the dragged card widget in Tkinter (takes ~1ms!)
            moved_card = item["card"]
            try:
                moved_card.pack_forget()
                if to_idx + 1 < len(cards):
                    moved_card.pack(fill="x", pady=2, ipady=2, before=cards[to_idx + 1]["card"])
                elif to_idx - 1 >= 0:
                    moved_card.pack(fill="x", pady=2, ipady=2, after=cards[to_idx - 1]["card"])
                else:
                    moved_card.pack(fill="x", pady=2, ipady=2)
            except Exception:
                for it in cards:
                    it["card"].pack_forget()
                for it in cards:
                    it["card"].pack(fill="x", pady=2, ipady=2)

            # Update indices and badge numbers, and restore clean border/background on all affected cards
            for idx, it in enumerate(cards):
                it["index"] = idx
                if "badge_lbl" in it and it["badge_lbl"].winfo_exists():
                    it["badge_lbl"].configure(text=f" 🤖 #{idx + 1} " if it.get("is_auto") else f" #{idx + 1} ")
                it["card"].configure(
                    border_width=1,
                    border_color=it["base_border"],
                    fg_color=it["base_fg"]
                )

            # Fast-update main run summary label without triggering redundant second puzzle refresh
            if "run_info_main" in self.__dict__:
                self.run_info_main.configure(text=self._get_run_summary(self.bot.get_run_filepath("main")))
            self._log(f"🔀 Step '{seg_title}' was moved from position #{from_idx + 1} to position #{to_idx + 1}.")
        else:
            # Restore borders on all cards if dropped on the same spot
            for it in cards:
                it["card"].configure(
                    border_width=1,
                    border_color=it["base_border"],
                    fg_color=it["base_fg"]
                )

    def _close_puzzle_drag_ghost(self):
        st = self.__dict__.get("_drag_puzzle_state")
        if st and st.get("ghost"):
            try:
                st["ghost"].destroy()
            except Exception:
                pass
            st["ghost"] = None

        ghost_list = self.__dict__.get("_puzzle_ghost_list")
        if ghost_list:
            for g in ghost_list:
                try:
                    g.destroy()
                except Exception:
                    pass
            ghost_list.clear()

    def _puzzle_add_automat_step(self):
        """Adds an autonomous '🤖 AUTOMAT' room-clear step directly to the Puzzle list."""
        current_run = self.cfg.get("selected_combat_run", "default_run")
        data = config.add_automat_segment_to_run(current_run)
        seg = data["segments"][-1]
        self._refresh_puzzle_ui()
        self._refresh_all_run_infos()
        self._log(
            f"🤖 Added step '{seg.get('name')}' to Puzzle [{current_run}]! "
            f"(Clears room of mobs using skills 1,3,4,5 and returns character to start location)."
        )

    def handle_f1_puzzle_record(self):
        """
        Hotkey [F1]: Starts or stops recording a movement/combat Puzzle step.
        If a live [F2] Automat step is currently running, stops it and immediately begins recording the next movement step!
        """
        if getattr(self.bot, "_in_live_puzzle_automat", False):
            self._log("⏹ [F1] Finishing live 🤖 AUTO-MOB step and immediately starting next movement recording...")
            self.bot.stop_bot_loop()
            time.sleep(0.08)

        if self.bot.state == BotState.RECORDING:
            hk_f1 = self.cfg.get("hotkeys", {}).get("puzzle_record_step", "f1")
            stats = self.bot.stop_recording(stop_hotkey=hk_f1)
            self._refresh_all_run_infos()
            if stats:
                target_title = f"🧩 {stats.get('segment_name')}" if stats.get("is_segment") else stats.get("file", "")
                self.overlay.finish(stats.get("duration", 0), stats.get("event_count", 0), target_title)
            else:
                self.overlay.hide()
        elif self.bot.state == BotState.IDLE:
            self.toggle_recording("main")
        else:
            self._log("⚠️ Bot is busy performing another operation. Press [ESC] for emergency stop.")

    def handle_f2_puzzle_automat(self):
        """
        Hotkey [F2]:
        1. If currently recording a movement step via [F1]/[F7], automatically stops & saves it into Puzzle first.
        2. Appends a new '🤖 AUTOMAT' step to the Puzzle.
        3. Immediately launches Automat live in-game to clear the room and walk back to this exact spot!
        """
        self._save_timing_inputs()
        self._save_heal_inputs()
        self._save_automat_inputs()
        current_run = self.cfg.get("selected_combat_run", "default_run")

        # 1. If recording a movement step right now, stop & save it to Puzzle first!
        if self.bot.state == BotState.RECORDING:
            hk_f2 = self.cfg.get("hotkeys", {}).get("puzzle_automat_step", "f2")
            self.bot.current_recording_slot = "main"
            stats = self.bot.stop_recording(stop_hotkey=hk_f2)
            self.overlay.hide()
            if stats:
                self._log(
                    f"💾 [F2] Movement step '{stats.get('segment_name', 'Step')}' ({stats.get('duration', 0)}s) "
                    f"automatically saved into Puzzle [{current_run}]!"
                )

        # If live F2 Automat is already running and user presses F2 again, stop it
        if getattr(self.bot, "_in_live_puzzle_automat", False):
            self.bot.stop_bot_loop()
            self._refresh_all_run_infos()
            return

        if self.bot.state != BotState.IDLE:
            self._log("⚠️ Cannot start live [F2] Auto-Mob step because bot is not IDLE.")
            return

        # 2. Append 🤖 AUTOMAT step to Puzzle
        data = config.add_automat_segment_to_run(current_run)
        seg = data["segments"][-1]
        seg_name = seg.get("name", "🤖 AUTO-MOB")
        self._refresh_all_run_infos()
        self._log(f"🧩 [F2] Added '{seg_name}' to Puzzle [{current_run}] -> Immediately launching room clear in-game!")

        # 3. Run live room clear + return to origin
        self.bot.start_live_puzzle_automat_step(step_name=seg_name)



    def _puzzle_add_step_dialog(self):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        data = config.load_combat_run_data(current_run)
        step_num = len(data.get("segments", [])) + 1
        dialog = ctk.CTkInputDialog(
            text=f"Enter name for new puzzle step (e.g. Room {step_num}, Boss, Door):",
            title=f"New Puzzle Step #{step_num}"
        )
        name = dialog.get_input()
        if name is not None:
            chosen = name.strip() if name.strip() else f"Step {step_num}"
            started = self.bot.start_recording_segment(current_run, mode="add", name=chosen)
            if started:
                self.overlay.show(
                    slot="main",
                    get_event_count_func=lambda: len(self.bot.recorder.events),
                    custom_title=f"🧩 PUZZLE #{step_num}: {chosen}"
                )

    def _record_puzzle_segment(self, index: int, current_name: str):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        started = self.bot.start_recording_segment(current_run, mode="update", index=index, name=current_name)
        if started:
            self.overlay.show(
                slot="main",
                get_event_count_func=lambda: len(self.bot.recorder.events),
                custom_title=f"🧩 PUZZLE #{index + 1}: {current_name}"
            )

    def _rename_puzzle_segment_dialog(self, index: int, current_name: str):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        dialog = ctk.CTkInputDialog(
            text=f"Enter new name for step #{index + 1}:",
            title="Rename Puzzle Step"
        )
        new_name = dialog.get_input()
        if new_name and new_name.strip():
            config.update_segment_in_run(current_run, index, new_name=new_name.strip())
            self._refresh_puzzle_ui()
            self._refresh_all_run_infos()
            self._log(f"✏ Puzzle step #{index + 1} renamed to: '{new_name.strip()}'.")

    def _trim_puzzle_segment_dialog(self, index: int, current_name: str, duration: float):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        dialog = ctk.CTkInputDialog(
            text=f"Step '{current_name}' (duration {duration}s).\nEnter start second (or range, e.g. '2' or '2-50') to trim step:",
            title=f"Trim Step #{index + 1}"
        )
        inp = dialog.get_input()
        if inp and inp.strip():
            try:
                raw = inp.strip().replace(",", ".")
                if "-" in raw:
                    parts = [p.strip() for p in raw.split("-", 1)]
                    s_sec = float(parts[0]) if parts[0] else 0.0
                    e_sec = float(parts[1]) if parts[1] else None
                else:
                    s_sec = float(raw)
                    e_sec = None
                config.trim_segment_in_run(current_run, index, s_sec, e_sec)
                self._refresh_puzzle_ui()
                self._refresh_all_run_infos()
                self._log(f"✂️ Step #{index + 1} ('{current_name}') trimmed (from {s_sec}s) preserving held attacks.")
            except Exception as e:
                self._log(f"❌ Error trimming step: {e}")

    def _move_puzzle_segment(self, index: int, direction: int):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        config.move_segment_in_run(current_run, index, direction)
        self._refresh_puzzle_ui()
        self._refresh_all_run_infos()

    def _delete_puzzle_segment(self, index: int):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        config.delete_segment_from_run(current_run, index)
        self._refresh_puzzle_ui()
        self._refresh_all_run_infos()
        self._log(f"🗑 Puzzle step #{index + 1} deleted.")

    def _puzzle_split_dialog(self):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        dialog = ctk.CTkInputDialog(
            text="Enter split seconds separated by comma (e.g. 30, 60, 90):",
            title="Slice Entire Run by Seconds"
        )
        inp = dialog.get_input()
        if inp and inp.strip():
            try:
                splits = [float(s.strip().replace(",", ".")) for s in inp.split(",") if s.strip()]
                data = config.split_run_into_segments(current_run, splits)
                self._refresh_puzzle_ui()
                self._refresh_all_run_infos()
                segs = len(data.get("segments", []))
                self._log(f"✂️ Run '{current_run}' successfully sliced into {segs} modular puzzle steps!")
            except Exception as e:
                self._log(f"❌ Error slicing run: {e}")

    def _puzzle_convert_flat(self):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        config.convert_flat_run_to_puzzle(current_run, step_name="Step 1 (Base)")
        self._refresh_puzzle_ui()
        self._refresh_all_run_infos()
        self._log(f"🧩 Run '{current_run}' converted to modular puzzle with Step 1.")

    def _puzzle_merge_action(self):
        current_run = self.cfg.get("selected_combat_run", "default_run")
        config.merge_segments_to_single_run(current_run)
        self._refresh_puzzle_ui()
        self._refresh_all_run_infos()
        self._log(f"🔄 All puzzle steps of run '{current_run}' merged into a single flat run.")

    # --- ACTIONS ---
    def toggle_recording_active_slot(self):
        """Called by the global hotkey to toggle recording for the currently selected tab/slot."""
        self.toggle_recording(self.active_slot)

    def toggle_recording(self, slot: str = None):
        if slot:
            self.active_slot = slot

        target_slot = self.active_slot

        if self.bot.state == BotState.RECORDING:
            stats = self.bot.stop_recording(stop_hotkey=self.cfg.get("hotkeys", {}).get("record_active", "f7"))
            self._refresh_all_run_infos()
            if stats:
                target_title = f"🧩 {stats.get('segment_name')}" if stats.get("is_segment") else stats.get("file", "")
                self.overlay.finish(stats.get("duration", 0), stats.get("event_count", 0), target_title)
            else:
                self.overlay.hide()
        elif self.bot.state == BotState.IDLE:
            if hasattr(self, "automat_overlay"):
                self.automat_overlay.hide()
            self.bot.start_recording(slot=target_slot)
            
            # Form custom title for HUD
            if target_slot == "main":
                combat_name = self.cfg.get("selected_combat_run", "default_run")
                custom_hud_title = f"⚔️ MAIN RUN ({combat_name})"
            elif target_slot == "revive":
                custom_hud_title = "👼 RECOVERY: ANGEL (REVIVE)"
            elif target_slot == "reconnect":
                custom_hud_title = "🔌 RECOVERY: LOST CONNECTION"
            elif target_slot == "server_reconnect":
                custom_hud_title = "🌐 RECOVERY: SERVER RECONNECT"
            elif target_slot == "lobby":
                custom_hud_title = "🏰 RECOVERY: LOBBY (TOWN)"
            elif target_slot == "exit":
                custom_hud_title = "🚪 DUNGEON COMPLETE (EXIT RUN)"
            else:
                custom_hud_title = f"RUN ({target_slot.upper()})"

            self.overlay.show(
                slot=target_slot,
                get_event_count_func=lambda: len(self.bot.recorder.events),
                custom_title=custom_hud_title
            )

    def play_run_once(self, slot: str = "main"):
        self.bot.play_run_once(slot=slot)

    def toggle_bot_loop(self):
        if self.bot.state == BotState.IDLE:
            self._save_timing_inputs()
            self._save_heal_inputs()
            self._save_automat_inputs()

            self.bot.start_bot_loop()
        else:
            self.bot.stop_bot_loop()

    def toggle_automat_mode(self):
        if self.bot.state == BotState.IDLE:
            self._save_timing_inputs()
            self._save_heal_inputs()
            self._save_automat_inputs()
            self.bot.start_automat_loop()
        else:
            self.bot.stop_bot_loop()

    def _on_automat_settings_change(self):
        val = bool(self.chk_automat_f8.get())
        self.cfg["automat_use_on_f8"] = val
        self.bot.config["automat_use_on_f8"] = val
        if val and self.cfg.get("enable_automat_assist", False):
            # If user wants F8 to run pure Automat, turn off recorded-run assist to avoid confusion
            self.cfg["enable_automat_assist"] = False
            self.bot.config["enable_automat_assist"] = False
            if hasattr(self, "chk_main_automat_assist"):
                self.chk_main_automat_assist.deselect()
            if hasattr(self, "chk_tab_automat_assist"):
                self.chk_tab_automat_assist.deselect()
        config.save_config(self.cfg)
        self._log(f"🤖 Pure Auto-Mob mode on F8: {'ENABLED' if val else 'DISABLED (F8 runs recorded run)'}.")

    def _on_automat_assist_change(self, source: str = "main"):
        if source == "main" and hasattr(self, "chk_main_automat_assist"):
            val = bool(self.chk_main_automat_assist.get())
        elif hasattr(self, "chk_tab_automat_assist"):
            val = bool(self.chk_tab_automat_assist.get())
        else:
            val = False

        self.cfg["enable_automat_assist"] = val
        self.bot.config["enable_automat_assist"] = val

        if hasattr(self, "chk_main_automat_assist"):
            if val:
                self.chk_main_automat_assist.select()
            else:
                self.chk_main_automat_assist.deselect()
        if hasattr(self, "chk_tab_automat_assist"):
            if val:
                self.chk_tab_automat_assist.select()
            else:
                self.chk_tab_automat_assist.deselect()

        if val and self.cfg.get("automat_use_on_f8", False):
            # Ensure F8 starts the recorded run when Assist mode is enabled
            self.cfg["automat_use_on_f8"] = False
            self.bot.config["automat_use_on_f8"] = False
            if hasattr(self, "chk_automat_f8"):
                self.chk_automat_f8.deselect()

        config.save_config(self.cfg)
        self._log(
            f"🤝 Recorded run assist with Auto-Mob: "
            f"{'ENABLED (pauses on mobs, eliminates them, and resumes run)' if val else 'DISABLED'}."
        )

    def _on_automat_dir_selected(self, choice: str):
        if choice.lower().startswith("stand"):
            key = "stand"
            desc = "STAND (Hold position – remains stationary, attacks from spot)"
        elif choice.startswith("A"):
            key = "a"
            desc = "A (Left)"
        else:
            key = "d"
            desc = "D (Right)"
        self.cfg["automat_move_key"] = key
        self.bot.config["automat_move_key"] = key
        config.save_config(self.cfg)
        self._refresh_puzzle_ui()
        self._log(f"🏃 Auto-Mob movement mode set to: [{desc}].")

    def _save_automat_inputs(self, event=None):
        if hasattr(self, "entry_automat_linger"):
            try:
                val_l = float(self.entry_automat_linger.get().strip().replace(",", "."))
                if val_l < 0.0:
                    val_l = 0.0
                self.cfg["automat_combat_linger_seconds"] = val_l
                self.bot.config["automat_combat_linger_seconds"] = val_l
            except Exception:
                self.entry_automat_linger.delete(0, "end")
                self.entry_automat_linger.insert(0, str(self.cfg.get("automat_combat_linger_seconds", 3.0)))

        if hasattr(self, "entry_automat_jump"):
            try:
                val_j = float(self.entry_automat_jump.get().strip().replace(",", "."))
                if val_j < 0.0:
                    val_j = 0.0
                self.cfg["automat_jump_interval"] = val_j
                self.bot.config["automat_jump_interval"] = val_j
            except Exception:
                self.entry_automat_jump.delete(0, "end")
                self.entry_automat_jump.insert(0, str(self.cfg.get("automat_jump_interval", 10.0)))

        if hasattr(self, "entry_automat_aoe"):
            try:
                val_aoe = int(float(self.entry_automat_aoe.get().strip().replace(",", ".")))
                if val_aoe < 1:
                    val_aoe = 1
                self.cfg["automat_aoe_mob_threshold"] = val_aoe
                self.bot.config["automat_aoe_mob_threshold"] = val_aoe
            except Exception:
                self.entry_automat_aoe.delete(0, "end")
                self.entry_automat_aoe.insert(0, str(self.cfg.get("automat_aoe_mob_threshold", 3)))

        if hasattr(self, "entry_automat_aoe_mem"):
            try:
                val_mem = float(self.entry_automat_aoe_mem.get().strip().replace(",", "."))
                if val_mem < 0.0:
                    val_mem = 0.0
                self.cfg["automat_aoe_memory_seconds"] = val_mem
                self.bot.config["automat_aoe_memory_seconds"] = val_mem
            except Exception:
                self.entry_automat_aoe_mem.delete(0, "end")
                self.entry_automat_aoe_mem.insert(0, str(self.cfg.get("automat_aoe_memory_seconds", 20.0)))

        if hasattr(self, "entry_automat_angle"):
            try:
                val_ang = float(self.entry_automat_angle.get().strip().replace(",", "."))
                val_ang = max(-75.0, min(75.0, val_ang))
                self.cfg["automat_shoot_angle"] = val_ang
                self.bot.config["automat_shoot_angle"] = val_ang
            except Exception:
                self.entry_automat_angle.delete(0, "end")
                self.entry_automat_angle.insert(0, str(self.cfg.get("automat_shoot_angle", 0.0)))

        if hasattr(self, "entry_automat_spread"):
            try:
                val_spr = float(self.entry_automat_spread.get().strip().replace(",", "."))
                val_spr = max(0.0, min(60.0, val_spr))
                self.cfg["automat_shoot_spread"] = val_spr
                self.bot.config["automat_shoot_spread"] = val_spr
            except Exception:
                self.entry_automat_spread.delete(0, "end")
                self.entry_automat_spread.insert(0, str(self.cfg.get("automat_shoot_spread", 12.0)))

        if hasattr(self, "entry_automat_s5_cd"):
            try:
                val_s5cd = float(self.entry_automat_s5_cd.get().strip().replace(",", "."))
                if val_s5cd < 0.0:
                    val_s5cd = 0.0
                self.cfg["automat_skill_5_min_interval"] = val_s5cd
                self.bot.config["automat_skill_5_min_interval"] = val_s5cd
            except Exception:
                self.entry_automat_s5_cd.delete(0, "end")
                self.entry_automat_s5_cd.insert(0, str(self.cfg.get("automat_skill_5_min_interval", 15.0)))

        for attr, cfg_key, default_v in [
            ("entry_auto_s1", "automat_skill_1_key", "1"),
            ("entry_auto_s3", "automat_skill_3_key", "3"),
            ("entry_auto_s4", "automat_skill_4_key", "4"),
            ("entry_auto_s5", "automat_skill_5_key", "5"),
        ]:
            if hasattr(self, attr):
                v = getattr(self, attr).get().strip()
                if v:
                    self.cfg[cfg_key] = v
                    self.bot.config[cfg_key] = v
                else:
                    getattr(self, attr).insert(0, default_v)

        config.save_config(self.cfg)

    def _test_automat_detection(self):
        self._save_automat_inputs()
        res = self.bot.detector.test_automat_scan()
        self.lbl_automat_test_result.configure(
            text=res["message"],
            text_color="#38d9a9" if res.get("found_ui") else "#fbbf24"
        )
        self._log(res["message"].replace("\n", " | "))

    def emergency_stop(self):
        self.overlay.hide()
        if hasattr(self, "automat_overlay"):
            self.automat_overlay.finish(
                duration=0.0,
                title_text="🛑 AUTO-MOB STOPPED (ESC)",
                status_text="Emergency stop triggered",
                hint_text="All keys and mouse buttons released."
            )
        self._prev_automat_hud_active = False
        self.bot.emergency_stop()

    def _save_timing_inputs(self, event=None):
        if hasattr(self, "entry_delay"):
            try:
                val_delay = float(self.entry_delay.get().strip().replace(",", "."))
                if val_delay < 0: val_delay = 0.0
                self.cfg["start_delay"] = val_delay
                self.bot.config["start_delay"] = val_delay
            except Exception:
                self.entry_delay.delete(0, "end")
                self.entry_delay.insert(0, str(self.cfg.get("start_delay", 3.0)))

        if hasattr(self, "entry_death_rewind"):
            try:
                val_dr = float(self.entry_death_rewind.get().strip().replace(",", "."))
                if val_dr < 0: val_dr = 0.0
                self.cfg["death_rewind_seconds"] = val_dr
                self.bot.config["death_rewind_seconds"] = val_dr
            except Exception:
                self.entry_death_rewind.delete(0, "end")
                self.entry_death_rewind.insert(0, str(self.cfg.get("death_rewind_seconds", 3.0)))

        if hasattr(self, "entry_disconnect_rewind"):
            try:
                val_dcr = float(self.entry_disconnect_rewind.get().strip().replace(",", "."))
                if val_dcr < 0: val_dcr = 0.0
                self.cfg["disconnect_rewind_seconds"] = val_dcr
                self.bot.config["disconnect_rewind_seconds"] = val_dcr
            except Exception:
                self.entry_disconnect_rewind.delete(0, "end")
                self.entry_disconnect_rewind.insert(0, str(self.cfg.get("disconnect_rewind_seconds", 3.0)))

        if hasattr(self, "entry_server_reconnect_rewind"):
            try:
                val_sr = float(self.entry_server_reconnect_rewind.get().strip().replace(",", "."))
                if val_sr < 0: val_sr = 0.0
                self.cfg["server_reconnect_rewind_seconds"] = val_sr
                self.bot.config["server_reconnect_rewind_seconds"] = val_sr
            except Exception:
                self.entry_server_reconnect_rewind.delete(0, "end")
                self.entry_server_reconnect_rewind.insert(0, str(self.cfg.get("server_reconnect_rewind_seconds", 3.0)))

        if hasattr(self, "entry_lobby_rewind"):
            try:
                val_lr = float(self.entry_lobby_rewind.get().strip().replace(",", "."))
                if val_lr < 0: val_lr = 0.0
                self.cfg["lobby_rewind_seconds"] = val_lr
                self.bot.config["lobby_rewind_seconds"] = val_lr
            except Exception:
                self.entry_lobby_rewind.delete(0, "end")
                self.entry_lobby_rewind.insert(0, str(self.cfg.get("lobby_rewind_seconds", 0.0)))

        if hasattr(self, "entry_constant_attack_delay"):
            try:
                val_cad = float(self.entry_constant_attack_delay.get().strip().replace(",", "."))
                if val_cad < 0: val_cad = 0.0
                self.cfg["constant_attack_delay"] = val_cad
                self.bot.config["constant_attack_delay"] = val_cad
            except Exception:
                self.entry_constant_attack_delay.delete(0, "end")
                self.entry_constant_attack_delay.insert(0, str(self.cfg.get("constant_attack_delay", 5.0)))

        config.save_config(self.cfg)

    def _toggle_constant_attack(self):
        new_state = not bool(self.cfg.get("enable_constant_attack", True))
        self.cfg["enable_constant_attack"] = new_state
        self.bot.config["enable_constant_attack"] = new_state
        self._save_timing_inputs()
        if hasattr(self, "btn_constant_attack"):
            self.btn_constant_attack.configure(
                text="🗡️ CONSTANT ATTACK (Hold LMB on character): ON" if new_state else "🗡️ CONSTANT ATTACK (Hold LMB on character): OFF",
                fg_color="#ca8a04" if new_state else "#475569",
                hover_color="#a16207" if new_state else "#334155"
            )
        delay_s = self.cfg.get("constant_attack_delay", 5.0)
        self._log(f"🗡️ Constant attack: {'ON (after ' + str(delay_s) + 's of combat run)' if new_state else 'OFF'}.")

    def _on_recovery_settings_change(self):
        self.cfg["enable_death_recovery"] = bool(self.chk_death.get())
        self.cfg["enable_disconnect_recovery"] = bool(self.chk_disc.get())
        if hasattr(self, "chk_server_reconnect"):
            self.cfg["enable_server_reconnect_recovery"] = bool(self.chk_server_reconnect.get())
            self.bot.config["enable_server_reconnect_recovery"] = self.cfg["enable_server_reconnect_recovery"]
        if hasattr(self, "chk_lobby"):
            self.cfg["enable_lobby_recovery"] = bool(self.chk_lobby.get())
            self.bot.config["enable_lobby_recovery"] = self.cfg["enable_lobby_recovery"]
        self.cfg["enable_dungeon_complete_recovery"] = bool(self.chk_exit.get())
        self.bot.config["enable_death_recovery"] = self.cfg["enable_death_recovery"]
        self.bot.config["enable_disconnect_recovery"] = self.cfg["enable_disconnect_recovery"]
        self.bot.config["enable_dungeon_complete_recovery"] = self.cfg["enable_dungeon_complete_recovery"]
        config.save_config(self.cfg)

    def _on_heal_settings_change(self):
        self.cfg["enable_auto_heal"] = bool(self.chk_auto_heal.get())
        self.bot.config["enable_auto_heal"] = self.cfg["enable_auto_heal"]
        if hasattr(self, "chk_heal_save_mana"):
            self.cfg["heal_save_mana_enabled"] = bool(self.chk_heal_save_mana.get())
            self.bot.config["heal_save_mana_enabled"] = self.cfg["heal_save_mana_enabled"]
        self._save_heal_inputs()
        self._log(
            f"🧪 Auto-Heal: {'ENABLED' if self.cfg['enable_auto_heal'] else 'DISABLED'} | "
            f"Save mana for Heal under {self.cfg.get('heal_save_mana_hp_threshold', 50.0):.0f}% HP: "
            f"{'ON' if self.cfg.get('heal_save_mana_enabled', True) else 'OFF'}."
        )

    def _save_heal_inputs(self, event=None):
        if hasattr(self, "entry_heal_key"):
            k_val = self.entry_heal_key.get().strip()
            if k_val:
                self.cfg["heal_key"] = k_val
                self.bot.config["heal_key"] = k_val

        if hasattr(self, "entry_heal_thresh"):
            try:
                ht_val = float(self.entry_heal_thresh.get().strip().replace(",", "."))
                ht_val = max(1.0, min(99.0, ht_val))
                self.cfg["heal_hp_threshold"] = ht_val
                self.bot.config["heal_hp_threshold"] = ht_val
            except Exception:
                self.entry_heal_thresh.delete(0, "end")
                self.entry_heal_thresh.insert(0, str(self.cfg.get("heal_hp_threshold", 40.0)))

        if hasattr(self, "entry_heal_cooldown"):
            try:
                cd_val = float(self.entry_heal_cooldown.get().strip().replace(",", "."))
                if cd_val < 0.5: cd_val = 0.5
                self.cfg["heal_cooldown_seconds"] = cd_val
                self.bot.config["heal_cooldown_seconds"] = cd_val
            except Exception:
                self.entry_heal_cooldown.delete(0, "end")
                self.entry_heal_cooldown.insert(0, str(self.cfg.get("heal_cooldown_seconds", 2.0)))

        if hasattr(self, "entry_heal_save_mana_thresh"):
            try:
                sm_val = float(self.entry_heal_save_mana_thresh.get().strip().replace(",", "."))
                sm_val = max(1.0, min(99.0, sm_val))
                self.cfg["heal_save_mana_hp_threshold"] = sm_val
                self.bot.config["heal_save_mana_hp_threshold"] = sm_val
            except Exception:
                self.entry_heal_save_mana_thresh.delete(0, "end")
                self.entry_heal_save_mana_thresh.insert(0, str(self.cfg.get("heal_save_mana_hp_threshold", 50.0)))

        config.save_config(self.cfg)

    def _test_heal_detection(self):
        self._save_heal_inputs()
        thresh = float(self.cfg.get("heal_hp_threshold", 40.0))
        res = self.bot.detector.test_hp_and_skill_scan(hp_threshold=thresh)
        self.lbl_heal_test_result.configure(text=res["message"], text_color="#38d9a9" if res.get("found") else "#f87171")
        self._log(res["message"].replace("\n", " | "))

    def _on_settings_checkbox(self):
        self.cfg["record_mouse_move"] = bool(self.chk_mouse.get())
        self.cfg["sound_enabled"] = bool(self.chk_sound.get())
        self.bot.recorder.record_mouse_move = self.cfg["record_mouse_move"]
        self.bot.config["sound_enabled"] = self.cfg["sound_enabled"]
        config.save_config(self.cfg)

