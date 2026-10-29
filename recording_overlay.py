import time
import os
import tkinter as tk
import customtkinter as ctk

class RecordingOverlay:
    def __init__(self, master):
        self.master = master
        self.win = None
        self._is_active = False
        self._start_time = 0.0
        self._get_event_count_func = None
        self._slot_name = ""
        self._drag_start_x = 0
        self._drag_start_y = 0

    def show(self, slot: str, get_event_count_func=None, custom_title: str = None):
        """Creates and displays the floating top-most mini overlay."""
        self.hide() # Close existing if any

        if custom_title:
            self._slot_name = custom_title
        else:
            slot_titles = {
                "main": "⚔️ MAIN COMBAT RUN",
                "revive": "👼 RECOVERY: ANGEL (REVIVE)",
                "reconnect": "🔌 RECOVERY: LOST CONNECTION",
                "exit": "🚪 DUNGEON COMPLETE (EXIT RUN)"
            }
            self._slot_name = slot_titles.get(slot, f"RUN: {slot.upper()}")

        self._get_event_count_func = get_event_count_func
        self._start_time = time.perf_counter()
        self._is_active = True

        self.win = ctk.CTkToplevel(self.master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        # Calculate position: top center of primary screen
        sw = self.win.winfo_screenwidth()
        w = 340
        h = 82
        x = max(10, (sw - w) // 2)
        y = 20
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        # Main container with red warning border
        self.card = ctk.CTkFrame(
            self.win,
            fg_color="#181a20",
            border_color="#e03131",
            border_width=2,
            corner_radius=12
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        # Make it draggable
        self.card.bind("<Button-1>", self._start_drag)
        self.card.bind("<B1-Motion>", self._do_drag)

        # Title row: pulsing indicator + slot title
        self.lbl_title = ctk.CTkLabel(
            self.card,
            text=f"🔴 RECORDING: {self._slot_name}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ff8787"
        )
        self.lbl_title.pack(pady=(6, 2))
        self.lbl_title.bind("<Button-1>", self._start_drag)
        self.lbl_title.bind("<B1-Motion>", self._do_drag)

        # Live stats row
        self.lbl_stats = ctk.CTkLabel(
            self.card,
            text="⏱ Time: 00:00.0  |  Actions: 0",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#f8f9fa"
        )
        self.lbl_stats.pack(pady=1)
        self.lbl_stats.bind("<Button-1>", self._start_drag)
        self.lbl_stats.bind("<B1-Motion>", self._do_drag)

        # Bottom hint
        self.lbl_hint = ctk.CTkLabel(
            self.card,
            text="Press [F7] to finish and save",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        )
        self.lbl_hint.pack(pady=(0, 4))
        self.lbl_hint.bind("<Button-1>", self._start_drag)
        self.lbl_hint.bind("<B1-Motion>", self._do_drag)

        self._tick()

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event):
        if not self.win:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        new_x = self.win.winfo_x() + dx
        new_y = self.win.winfo_y() + dy
        self.win.geometry(f"+{new_x}+{new_y}")

    def _tick(self):
        if not self._is_active or not self.win:
            return

        elapsed = time.perf_counter() - self._start_time
        mins = int(elapsed // 60)
        secs = elapsed % 60

        count = self._get_event_count_func() if self._get_event_count_func else 0

        # Alternate dot color between bright red and soft red every 500ms
        dot = "🔴" if int(elapsed * 2) % 2 == 0 else "⭕"
        self.lbl_title.configure(text=f"{dot} RECORDING: {self._slot_name}")
        self.lbl_stats.configure(text=f"⏱ {mins:02d}:{secs:04.1f}  |  Actions: {count}")

        self.master.after(100, self._tick)

    def finish(self, duration: float, count: int, filename: str):
        """Displays saved confirmation and closes after short delay."""
        if not self.win:
            return

        self._is_active = False
        fname = os.path.basename(filename)

        self.card.configure(border_color="#2b8a3e")
        self.lbl_title.configure(text=f"✅ SAVED: {self._slot_name}", text_color="#69db7c")
        self.lbl_stats.configure(text=f"Duration: {duration:.1f}s  |  Actions: {count}")
        lbl_info = f"Saved: {fname}" if fname.startswith("🧩") else f"File: {fname} ready!"
        self.lbl_hint.configure(text=lbl_info, text_color="#a0aec0")

        # Auto close after 1.8 seconds
        self.master.after(1800, self.hide)

    def hide(self):
        """Destroys the overlay window."""
        self._is_active = False
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


class AutomatOverlay:
    """Floating top-most HUD overlay above the game showing when Auto-Mob is ON and when it turns OFF."""
    def __init__(self, master):
        self.master = master
        self.win = None
        self._is_active = False
        self._start_time = 0.0
        self._get_info_func = None
        self._drag_start_x = 0
        self._drag_start_y = 0

    def show(self, get_info_func=None):
        """Creates and displays the floating top-most Auto-Mob HUD overlay."""
        self.hide()

        self._get_info_func = get_info_func
        self._start_time = time.perf_counter()
        self._is_active = True

        self.win = ctk.CTkToplevel(self.master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        sw = self.win.winfo_screenwidth()
        w = 390
        h = 84
        x = max(10, (sw - w) // 2)
        y = 18
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        self.card = ctk.CTkFrame(
            self.win,
            fg_color="#111827",
            border_color="#10b981",
            border_width=2,
            corner_radius=12
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        self.card.bind("<Button-1>", self._start_drag)
        self.card.bind("<B1-Motion>", self._do_drag)

        self.lbl_title = ctk.CTkLabel(
            self.card,
            text="🟢 🤖 AUTO-MOB ACTIVE",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#34d399"
        )
        self.lbl_title.pack(pady=(6, 2))
        self.lbl_title.bind("<Button-1>", self._start_drag)
        self.lbl_title.bind("<B1-Motion>", self._do_drag)

        self.lbl_stats = ctk.CTkLabel(
            self.card,
            text="⏱ 00:00.0  |  Scanning enemies...",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#f8f9fa"
        )
        self.lbl_stats.pack(pady=1)
        self.lbl_stats.bind("<Button-1>", self._start_drag)
        self.lbl_stats.bind("<B1-Motion>", self._do_drag)

        self.lbl_hint = ctk.CTkLabel(
            self.card,
            text="Press [F1] to record movement or [ESC] to Stop",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        )
        self.lbl_hint.pack(pady=(0, 4))
        self.lbl_hint.bind("<Button-1>", self._start_drag)
        self.lbl_hint.bind("<B1-Motion>", self._do_drag)

        self._tick()

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event):
        if not self.win:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        new_x = self.win.winfo_x() + dx
        new_y = self.win.winfo_y() + dy
        self.win.geometry(f"+{new_x}+{new_y}")

    def _tick(self):
        if not self._is_active or not self.win:
            return

        elapsed = time.perf_counter() - self._start_time
        mins = int(elapsed // 60)
        secs = elapsed % 60

        info = self._get_info_func() if self._get_info_func else {}
        title_str = info.get("title", "🤖 AUTO-MOB ACTIVE")
        status_str = info.get("status", "Active")
        hint_str = info.get("hint", "Press [F1] to record movement | [ESC] Stop")

        dot = "🟢" if int(elapsed * 2) % 2 == 0 else "🤖"
        self.lbl_title.configure(text=f"{dot} {title_str}")
        self.lbl_stats.configure(text=f"⏱ {mins:02d}:{secs:04.1f}  |  {status_str}")
        self.lbl_hint.configure(text=hint_str)

        self.master.after(100, self._tick)

    def finish(self, duration: float = 0.0, title_text: str = "🤖 AUTO-MOB STOPPED", status_text: str = "Room cleared!", hint_text: str = ""):
        """Displays confirmation when Auto-Mob turns OFF and closes after 1.8s."""
        if not self.win:
            return

        self._is_active = False
        self.card.configure(border_color="#3b82f6")
        self.lbl_title.configure(text=f"⏹ {title_text}", text_color="#60a5fa")
        self.lbl_stats.configure(text=f"{status_text} (Duration: {duration:.1f}s)")
        self.lbl_hint.configure(
            text=hint_text if hint_text else "Auto-Mob ended.",
            text_color="#cbd5e1"
        )

        self.master.after(1800, self.hide)

    def hide(self):
        """Destroys the Auto-Mob HUD window."""
        self._is_active = False
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
