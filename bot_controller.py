import time
import os
import math
import random
import threading
import winsound
import config
from recorder import InputRecorder
from replayer import InputReplayer, is_hardware_esc_pressed
from recovery_detector import RecoveryDetector

class BotState:
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    COUNTDOWN = "COUNTDOWN"
    EXECUTING_RUN = "EXECUTING_RUN"
    WAITING_FOR_SPAWN = "WAITING_FOR_SPAWN"
    RECOVERING_DEATH = "RECOVERING_DEATH"
    RECOVERING_DISCONNECT = "RECOVERING_DISCONNECT"
    RECOVERING_SERVER_RECONNECT = "RECOVERING_SERVER_RECONNECT"
    RECOVERING_LOBBY = "RECOVERING_LOBBY"
    RECOVERING_EXIT = "RECOVERING_EXIT"

class BotController:
    def __init__(self, config_dict: dict, on_state_change=None, on_log=None):
        self.config = config_dict
        self.on_state_change = on_state_change
        self.on_log = on_log

        self.state = BotState.IDLE
        self.state_details = ""
        self.current_recording_slot = "main" # 'main', 'revive', 'reconnect', 'server_reconnect', 'lobby', 'exit'
        self.paused_run_index = 0 # Tracks action index for pausing/resuming combat run
        self.paused_step_index = 0 # Tracks puzzle segment index for pausing/resuming

        # Puzzle / Segment tracking
        self.is_segmented_run = False
        self.current_step_index = 0
        self.total_steps = 1
        self.current_step_name = ""
        self.recording_segment_target = None # Dict if recording a single puzzle segment

        # Live statistics
        self.bot_start_time = 0.0
        self.loop_count = 0
        self.revive_count = 0
        self.disconnect_count = 0
        self.server_reconnect_count = 0
        self.lobby_count = 0
        self.exit_count = 0
        self.heal_count = 0

        # Auto-Heal live tracking
        self._last_heal_time = 0.0
        self.last_hp_percent = 100.0
        self.last_skill_ready = False
        self.last_ui_found = False

        self._last_death_incident_time = 0.0
        self._last_skill_5_cast_time = 0.0
        self._aoe_pack_seen_time = 0.0
        self._aoe_pack_max_mobs = 0

        self.recorder = InputRecorder()
        self.replayer = InputReplayer()
        self.detector = RecoveryDetector(targets_dir="targets")

        self._bot_thread = None
        self._watchdog_thread = None
        self._stop_bot_event = threading.Event()
        self._recovery_requested = None # 'death' or 'disconnect' or 'automat_assist'
        self._in_recorded_combat_run = False
        self._in_automat_assist_combat = False
        self._in_live_puzzle_automat = False

        # Live Automat HUD Overlay state
        self.automat_hud_active = False
        self.automat_hud_start_time = 0.0
        self.automat_hud_title = "🤖 AUTO-MOB ON"
        self.automat_hud_status = "Skenujem mobov..."
        self.automat_hud_hint = "Press [F1] to record movement | [ESC] Stop"
        self.automat_hud_last_finish = None

    def _set_state(self, new_state: str, details: str = ""):
        self.state = new_state
        self.state_details = details
        if self.on_state_change:
            self.on_state_change(new_state, details)

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        if self.on_log:
            self.on_log(formatted)
        try:
            print(formatted)
        except Exception:
            try:
                print(formatted.encode("ascii", errors="replace").decode("ascii"))
            except Exception:
                pass

    def get_live_stats(self) -> dict:
        """Returns snapshot of current live statistics for the Bot HUD."""
        uptime = time.perf_counter() - self.bot_start_time if (self.bot_start_time > 0 and self.state != BotState.IDLE) else 0.0
        return {
            "uptime": uptime,
            "state": self.state,
            "state_details": self.state_details,
            "loop_count": self.loop_count,
            "revive_count": self.revive_count,
            "disconnect_count": self.disconnect_count,
            "server_reconnect_count": self.server_reconnect_count,
            "lobby_count": self.lobby_count,
            "exit_count": self.exit_count,
            "heal_count": self.heal_count,
            "hp_percent": self.last_hp_percent,
            "skill_ready": self.last_skill_ready,
            "ui_found": self.last_ui_found,
            "profile": self.config.get("selected_combat_run", "predvoleny_run"),
            "paused_index": self.paused_run_index,
            "paused_step_index": self.paused_step_index,
            "is_segmented": self.is_segmented_run,
            "step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "step_name": self.current_step_name,
            "is_running": (self._bot_thread is not None and self._bot_thread.is_alive())
        }

    def _play_sound(self, sound_type: str):
        if not self.config.get("sound_enabled", True):
            return
        try:
            if sound_type == "start_record":
                winsound.Beep(1000, 150)
            elif sound_type == "stop_record":
                winsound.Beep(600, 200)
            elif sound_type == "run_start":
                winsound.Beep(1200, 100)
                winsound.Beep(1500, 120)
            elif sound_type == "victory":
                winsound.Beep(1100, 120)
                winsound.Beep(1450, 180)
            elif sound_type == "alarm":
                winsound.Beep(800, 100)
                winsound.Beep(1200, 150)
                winsound.Beep(800, 100)
            elif sound_type == "stop":
                winsound.Beep(450, 250)
            elif sound_type == "error":
                winsound.Beep(300, 300)
        except Exception:
            pass

    def get_run_filepath(self, slot: str) -> str:
        if slot == "revive":
            return self.config.get("revive_run_file", "revive_run.json")
        elif slot == "reconnect":
            return self.config.get("reconnect_run_file", "reconnect_run.json")
        elif slot == "server_reconnect":
            return self.config.get("server_reconnect_run_file", "server_reconnect_run.json")
        elif slot == "lobby":
            return self.config.get("lobby_run_file", "lobby_run.json")
        elif slot == "exit":
            return self.config.get("exit_run_file", "exit_run.json")
        # Main combat run: dynamically retrieved from selected profile in runs/
        combat_name = self.config.get("selected_combat_run", "predvoleny_run")
        return config.get_combat_run_path(combat_name)

    # --- RECORDING RUN (MULTI-SLOT & MULTI-PROFILE & PUZZLE SEGMENTS) ---
    def start_recording(self, slot: str = "main"):
        if self.state != BotState.IDLE:
            self.log("⚠️ Cannot start recording, bot is not IDLE.")
            return

        self.recording_segment_target = None
        self.current_recording_slot = slot
        if slot == "main":
            combat_name = self.config.get("selected_combat_run", "predvoleny_run")
            data = config.load_combat_run_data(combat_name)
            next_step = len(data.get("segments", [])) + 1
            slot_desc = f"Puzzle Step #{next_step} [{combat_name}]"
        elif slot == "revive":
            slot_desc = "Death Recovery Run (Angel)"
        elif slot == "reconnect":
            slot_desc = "Lost Connection Recovery Run"
        elif slot == "server_reconnect":
            slot_desc = "Server Disconnect Recovery Run"
        elif slot == "lobby":
            slot_desc = "Town / Lobby Return Recovery Run"
        elif slot == "exit":
            slot_desc = "Dungeon Complete Run (Exit Run)"
        else:
            slot_desc = "Run"

        self._set_state(BotState.RECORDING, f"Recording: {slot_desc}...")
        self._play_sound("start_record")
        self.log(f"🔴 Recording started [{slot_desc}]! Press recording hotkey to stop.")

        record_mouse = self.config.get("record_mouse_move", True)
        self.recorder.start(record_mouse_move=record_mouse)

    def start_recording_segment(self, run_name: str, mode: str = "add", index: int = None, name: str = ""):
        """Starts recording specifically for an individual puzzle step (add or re-record)."""
        if self.state != BotState.IDLE:
            self.log("⚠️ Cannot start puzzle step recording, bot is not IDLE.")
            return False

        self.current_recording_slot = "main"
        self.recording_segment_target = {
            "run_name": run_name,
            "mode": mode,
            "index": index,
            "name": name
        }

        seg_desc = name if name else (f"Step #{index + 1}" if index is not None else "New Step")
        self._set_state(BotState.RECORDING, f"Recording puzzle step: {seg_desc}...")
        self._play_sound("start_record")
        self.log(f"🔴 Puzzle step recording [{seg_desc}] started! Press recording hotkey to stop.")

        record_mouse = self.config.get("record_mouse_move", True)
        self.recorder.start(record_mouse_move=record_mouse)
        return True

    def stop_recording(self, stop_hotkey: str = None) -> dict:
        if self.state != BotState.RECORDING:
            return {}

        events = self.recorder.stop(stop_hotkey=stop_hotkey)

        # 1. If explicit segment target was set (e.g. re-recording a specific step):
        if getattr(self, "recording_segment_target", None):
            target = self.recording_segment_target
            self.recording_segment_target = None
            run_name = target.get("run_name") or self.config.get("selected_combat_run", "predvoleny_run")
            mode = target.get("mode", "add")
            name = target.get("name", "")
            index = target.get("index", None)

            if mode == "update" and index is not None:
                data = config.update_segment_in_run(run_name, index, new_events=events, new_name=name)
                seg = data["segments"][index] if (0 <= index < len(data["segments"])) else {}
            else:
                data = config.add_segment_to_run(run_name, name, events)
                seg = data["segments"][-1]

            dur = seg.get("duration", 0.0)
            cnt = seg.get("event_count", len(events))
            stats = {
                "duration": dur,
                "event_count": cnt,
                "file": config.get_combat_run_path(run_name),
                "is_segment": True,
                "segment_name": seg.get("name", name)
            }
            self._play_sound("stop_record")
            self._set_state(BotState.IDLE, "Puzzle step saved successfully.")
            self.log(f"⏹ Puzzle step '{seg.get('name', name)}' saved! Duration: {dur}s, Actions: {cnt}.")
            return stats

        # 2. If recording main combat run via hotkey F7, auto-append as next puzzle step!
        if self.current_recording_slot == "main":
            run_name = self.config.get("selected_combat_run", "predvoleny_run")
            data = config.load_combat_run_data(run_name)
            segs = data.get("segments", [])
            step_num = len(segs) + 1
            step_name = f"Step {step_num}"
            data = config.add_segment_to_run(run_name, step_name, events)
            seg = data["segments"][-1]
            dur = seg.get("duration", 0.0)
            cnt = seg.get("event_count", len(events))
            stats = {
                "duration": dur,
                "event_count": cnt,
                "file": config.get_combat_run_path(run_name),
                "is_segment": True,
                "segment_name": step_name
            }
            self._play_sound("stop_record")
            self._set_state(BotState.IDLE, f"Puzzle step '{step_name}' added.")
            self.log(f"🧩 New puzzle step '{step_name}' added to run [{run_name}]! Duration: {dur}s, Actions: {cnt}.")
            return stats

        target_file = self.get_run_filepath(self.current_recording_slot)
        stats = self.recorder.save_run(target_file)

        self._play_sound("stop_record")
        self._set_state(BotState.IDLE, "Run saved successfully.")
        self.log(f"⏹ Recording finished! Duration: {stats['duration']}s, Actions: {stats['event_count']}. Saved to: {target_file}")
        return stats

    # --- TESTING RUN REPLAY (1x) ---
    def play_run_once(self, slot: str = "main"):
        if self.state != BotState.IDLE:
            self.log("⚠️ Cannot play run, bot is not IDLE.")
            return

        run_file = self.get_run_filepath(slot)
        if not os.path.exists(run_file):
            self.log(f"⚠️ Run file '{run_file}' does not exist! Record it first.")
            return

        def _play_thread():
            try:
                events = self.replayer.load_run(run_file)
                self._set_state(BotState.EXECUTING_RUN, f"Testovacie prehratie ({slot})...")
                self.log(f"▶ Starting test replay ({run_file})...")
                self._play_sound("run_start")
                finished, _ = self.replayer.play(events, start_index=0)
                if finished:
                    self.log(f"✅ Test replay ({slot}) completed successfully.")
                else:
                    self.log(f"⏹ Replay ({slot}) was interrupted.")
            except Exception as e:
                self.log(f"❌ Error playing run: {e}")
            finally:
                self._set_state(BotState.IDLE, "Ready.")

        threading.Thread(target=_play_thread, daemon=True).start()

    # --- AUTOMATIC LOOP WITH FAILURE WATCHDOG & PAUSE/RESUME ---
    def start_bot_loop(self):
        if self.state != BotState.IDLE:
            self.log("⚠️ Bot is already running or recording.")
            return

        if self.config.get("automat_use_on_f8", False):
            self.start_automat_loop()
            return

        main_run_file = self.get_run_filepath("main")
        if not os.path.exists(main_run_file):
            self.log(f"❌ Main run '{main_run_file}' does not exist! Record a combat run first.")
            self._play_sound("error")
            return

        combat_name = self.config.get("selected_combat_run", "predvoleny_run")
        run_data = config.load_combat_run_data(main_run_file)
        has_segs = bool(run_data.get("is_segmented") and run_data.get("segments"))
        has_evts = bool(run_data.get("events"))
        if not has_segs and not has_evts:
            self.log(f"⚠️ Run [{combat_name}] is empty (contains no puzzle steps or actions)! Record steps first.")
            self._play_sound("error")
            return

        # Check recovery run existence if enabled
        if self.config.get("enable_death_recovery", True):
            revive_file = self.get_run_filepath("revive")
            if not os.path.exists(revive_file):
                self.log(f"⚠️ Warning: Revive run '{revive_file}' is not recorded yet. You can record it in the 'Revive' tab.")

        if self.config.get("enable_disconnect_recovery", True):
            reconnect_file = self.get_run_filepath("reconnect")
            if not os.path.exists(reconnect_file):
                self.log(f"⚠️ Warning: Reconnect run '{reconnect_file}' is not recorded yet. You can record it in the 'Reconnect' tab.")

        if self.config.get("enable_server_reconnect_recovery", True):
            s_file = self.get_run_filepath("server_reconnect")
            if not os.path.exists(s_file):
                self.log(f"⚠️ Warning: Server Reconnect run '{s_file}' is not recorded yet. You can record it in the 'Server' tab.")

        if self.config.get("enable_lobby_recovery", True):
            l_file = self.get_run_filepath("lobby")
            if not os.path.exists(l_file):
                self.log(f"⚠️ Warning: Lobby run '{l_file}' is not recorded yet. You can record it in the 'Lobby' tab.")

        self._stop_bot_event.clear()
        self._recovery_requested = None
        self._in_recorded_combat_run = True
        self._in_automat_assist_combat = False
        self.paused_run_index = 0

        # Initialize live statistics
        self.bot_start_time = time.perf_counter()
        self.loop_count = 0
        self.revive_count = 0
        self.disconnect_count = 0
        self.server_reconnect_count = 0
        self.lobby_count = 0
        self.exit_count = 0
        self.heal_count = 0
        self._last_heal_time = 0.0
        self._last_death_incident_time = 0.0
        self._last_skill_5_cast_time = 0.0
        self._aoe_pack_seen_time = 0.0
        self._aoe_pack_max_mobs = 0

        self.detector.reload_templates()
        self._bot_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)

        self._bot_thread.start()
        self._watchdog_thread.start()

    # --- AUTONOMOUS COMBAT & MOVEMENT MODE ("AUTOMAT") ---
    def start_automat_loop(self):
        if self.state != BotState.IDLE:
            self.log("⚠️ Bot is already running or recording.")
            return

        self._stop_bot_event.clear()
        self._recovery_requested = None
        self._in_recorded_combat_run = False
        self._in_automat_assist_combat = False
        self.paused_run_index = 0
        self.paused_step_index = 0

        self.bot_start_time = time.perf_counter()
        self.loop_count = 1
        self.revive_count = 0
        self.disconnect_count = 0
        self.server_reconnect_count = 0
        self.lobby_count = 0
        self.exit_count = 0
        self.heal_count = 0
        self._last_heal_time = 0.0
        self._last_death_incident_time = 0.0
        self._last_skill_5_cast_time = 0.0
        self._aoe_pack_seen_time = 0.0
        self._aoe_pack_max_mobs = 0

        self.detector.reload_templates()
        self._bot_thread = threading.Thread(target=self._automat_loop, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)

        self._bot_thread.start()
        self._watchdog_thread.start()

    def _press_skill_key_quick(self, key_str: str):
        """Quickly taps a combat skill key (1, 3, 4, 5) without blocking the movement/aiming loop."""
        def _tap():
            try:
                k = str(key_str).lower().strip()
                if not k:
                    return
                import pydirectinput
                if k in pydirectinput.KEYBOARD_MAPPING:
                    pydirectinput.keyDown(k)
                    time.sleep(0.035)
                    pydirectinput.keyUp(k)
                else:
                    self.replayer._execute_key(k, is_down=True)
                    time.sleep(0.035)
                    self.replayer._execute_key(k, is_down=False)
            except Exception:
                pass

        threading.Thread(target=_tap, daemon=True).start()

    def _compute_advance_aim(self, move_dir: str, sweep_step: int) -> tuple:
        """
        Computes the cursor (tx, ty) for shooting ahead during Advance state,
        using configurable base angle (`automat_shoot_angle` in degrees, +up / -down)
        and angular spread (`automat_shoot_spread` in degrees).
        Dynamically adapts to Fullscreen and Browser Window geometry.
        """
        char_x, char_y, scale = self.detector.get_character_center()
        radius = 340.0 * scale
        base_deg = float(self.config.get("automat_shoot_angle", 0.0))
        spread_deg = max(0.0, float(self.config.get("automat_shoot_spread", 12.0)))
        cur_deg = base_deg + spread_deg * math.sin(sweep_step * 0.40)
        rad = math.radians(cur_deg)

        dx = int(radius * math.cos(rad))
        dy = int(radius * math.sin(rad))

        if move_dir == "a":
            tx = char_x - dx
        else:
            tx = char_x + dx
        ty = char_y - dy  # positive angle aims upward (smaller Y)

        min_x = max(50, char_x - int(680 * scale))
        max_x = min(1900, char_x + int(680 * scale))
        min_y = max(50, char_y - int(400 * scale))
        max_y = min(1040, char_y + int(300 * scale))

        tx = max(min_x, min(max_x, tx))
        ty = max(min_y, min(max_y, ty))
        return tx, ty

    def _try_cast_automat_skills(self, cached_ui_state: dict, enemy_count: int, now: float, last_skill_cast_time: float, skill_cd: float) -> float:
        """
        Evaluates and casts combat skills 1, 3, 4, 5:
        - Skills 4 & 5: always cast immediately when ready (colored).
        - Skills 1 & 3: if enemy_count >= automat_aoe_mob_threshold (e.g. 3+), or if a pack of >= threshold
          mobs was seen within the last `automat_aoe_memory_seconds` (default 20s), save mana exclusively
          for Skill 3 (AoE) and do NOT cast Skill 1; otherwise spam Skill 1.
        Returns updated last_skill_cast_time.
        """
        aoe_thresh = max(1, int(self.config.get("automat_aoe_mob_threshold", 3)))
        aoe_mem_sec = max(0.0, float(self.config.get("automat_aoe_memory_seconds", 20.0)))

        # Record / refresh AoE pack memory immediately whenever >= aoe_thresh mobs are visible on screen
        if enemy_count >= aoe_thresh:
            was_active = (self._aoe_pack_seen_time > 0.0) and ((now - self._aoe_pack_seen_time) <= aoe_mem_sec)
            self._aoe_pack_seen_time = now
            self._aoe_pack_max_mobs = max(self._aoe_pack_max_mobs, enemy_count)
            if not was_active and aoe_mem_sec > 0.0:
                self.log(
                    f"🧠 AUTO-MOB: Detected pack of {enemy_count} enemies (>= {aoe_thresh}) -> "
                    f"Memorized for {aoe_mem_sec:.0f}s (saving mana for AoE Skill 3)!"
                )

        if not cached_ui_state.get("found_ui", False) or (now - last_skill_cast_time < skill_cd):
            return last_skill_cast_time

        s_ready = cached_ui_state.get("skills_ready", {})
        mana_pct = float(cached_ui_state.get("mana_percent", 0.0))

        k4 = str(self.config.get("automat_skill_4_key", "4")).strip()
        k5 = str(self.config.get("automat_skill_5_key", "5")).strip()
        k1 = str(self.config.get("automat_skill_1_key", "1")).strip()
        k3 = str(self.config.get("automat_skill_3_key", "3")).strip()

        # Priority 1: Skills 4 and 5 whenever available (Skill 5 has a minimum interval so 2nd press doesn't pop the shield)
        if s_ready.get(4, False) and k4:
            self._press_skill_key_quick(k4)
            self.log(f"⚡ AUTO-MOB Skill 4 [{k4}] ready -> Casting!")
            return now

        s5_min_interval = max(0.0, float(self.config.get("automat_skill_5_min_interval", 15.0)))
        if s_ready.get(5, False) and k5 and (now - self._last_skill_5_cast_time >= s5_min_interval):
            self._press_skill_key_quick(k5)
            self._last_skill_5_cast_time = now
            self.log(f"🛡️ AUTO-MOB Skill 5 (Shield) [{k5}] activated! (Cooldown guard: {s5_min_interval:.0f}s)")
            return now

        # Check if we need to save mana for Heal (Skill 2) when HP is below threshold (default 50%)
        hp_pct = float(cached_ui_state.get("hp_percent", self.last_hp_percent))
        save_mana_enabled = bool(self.config.get("heal_save_mana_enabled", True))
        save_mana_hp_thresh = float(self.config.get("heal_save_mana_hp_threshold", 50.0))
        saving_mana_for_heal = save_mana_enabled and (hp_pct < save_mana_hp_thresh)

        in_aoe_memory = (enemy_count >= aoe_thresh) or (
            aoe_mem_sec > 0.0 and self._aoe_pack_seen_time > 0.0 and (now - self._aoe_pack_seen_time) <= aoe_mem_sec
        )

        # Priority 2: Skills 3 (AoE for multiple mobs / remembered pack) and 1 (Single target spam) when Mana >= 12%
        if mana_pct >= 12.0:
            if in_aoe_memory:
                # Multiple mobs on screen OR remembered pack within memory window -> wait exclusively for AoE Skill 3 (save mana for AoE, do NOT cast Skill 1)
                if s_ready.get(3, False) and k3:
                    self._press_skill_key_quick(k3)
                    rem_mem = max(0.0, aoe_mem_sec - (now - self._aoe_pack_seen_time)) if self._aoe_pack_seen_time > 0.0 else 0.0
                    pack_info = (
                        f"{enemy_count} mobov >= {aoe_thresh}"
                        if enemy_count >= aoe_thresh
                        else f"pack memory {self._aoe_pack_max_mobs} mobs active {rem_mem:.1f}s"
                    )
                    self.log(f"💥 AUTO-MOB AoE Skill 3 [{k3}] ({pack_info}, Mana: {mana_pct:.0f}%) -> Casting!")
                    return now
            else:
                self._aoe_pack_max_mobs = 0
                # Fewer mobs (e.g. 1-2 mobs and no active pack memory) -> spam Skill 1 exclusively, UNLESS saving mana for Heal (HP < 50%)
                if saving_mana_for_heal:
                    return last_skill_cast_time
                if s_ready.get(1, False) and k1:
                    self._press_skill_key_quick(k1)
                    self.log(f"🔥 AUTO-MOB Skill 1 [{k1}] (Mobs: {max(1, enemy_count)}, Mana: {mana_pct:.0f}%) -> Casting!")
                    return now

        return last_skill_cast_time

    def _automat_loop(self):
        """
        Autonomous combat & advance loop ('Automat'):
        1. ADVANCE STATE (no enemy HP bars visible & linger timer expired):
           - Holds forward direction key ('d' or 'a')
           - Holds left mouse button and sweeps cursor ahead of character to hit/reveal enemy HP bars
           - Does NOT fire skills 1, 3, 4, 5
        2. COMBAT + LINGER STATE (enemy HP bar visible OR within linger delay after last enemy seen):
           - Stops blind forward running; moves toward nearest enemy HP bar or stands in combat range
           - Aims directly at nearest enemy body (below HP bar) and holds left mouse button
           - Fires Skills 4 & 5 immediately whenever their HUD icons are colored (ready)
           - Fires Skills 1 & 3 randomly/alternatingly based on Mana % and icon readiness
           - Continues attacking for `automat_combat_linger_seconds` (e.g. 3.0s) after HP bars disappear
             before verifying the room is clear and resuming ADVANCE.
        """
        revive_file = self.get_run_filepath("revive")
        reconnect_file = self.get_run_filepath("reconnect")
        server_reconnect_file = self.get_run_filepath("server_reconnect")
        lobby_file = self.get_run_filepath("lobby")
        exit_file = self.get_run_filepath("exit")

        start_delay = float(self.config.get("start_delay", 3.0))
        move_dir = str(self.config.get("automat_move_key", "d")).lower().strip()
        if move_dir not in ("d", "a", "stand"):
            move_dir = "d"
        linger_cfg = float(self.config.get("automat_combat_linger_seconds", 3.0))
        dir_disp = "STAND (Hold Position)" if move_dir == "stand" else move_dir.upper()

        self.log(
            f"🤖 AUTO-MOB mode started! Movement: [{dir_disp}], "
            f"Combat linger after mobs: {linger_cfg:.1f}s. Initial countdown: {start_delay:.1f}s"
        )

        if start_delay > 0:
            delay_start = time.perf_counter()
            while time.perf_counter() - delay_start < start_delay:
                if self._stop_bot_event.is_set():
                    self._set_state(BotState.IDLE, "Stopped.")
                    return
                if self._recovery_requested:
                    break
                remaining = max(0.0, start_delay - (time.perf_counter() - delay_start))
                self._set_state(BotState.COUNTDOWN, f"🤖 Auto-Mob starting in {remaining:.1f}s - switch to game!")
                time.sleep(0.05)

        self._play_sound("run_start")

        self.automat_hud_start_time = time.perf_counter()
        self.automat_hud_title = f"🤖 AUTO-MOB ACTIVE [{dir_disp}]"
        self.automat_hud_status = "Skenujem mobov..."
        self.automat_hud_hint = "Press [F8] or [ESC] to stop Auto-Mob"
        self.automat_hud_active = True

        held_move_key = None
        left_mouse_held = False
        last_enemy_seen_time = 0.0
        last_target_pos = (1120, 520) if move_dir == "d" else (800, 520)
        last_skill_cast_time = 0.0
        last_jump_time = time.perf_counter()
        last_ui_check_time = 0.0
        cached_ui_state = {"found_ui": False, "mana_percent": 100.0, "skills_ready": {1: False, 3: False, 4: False, 5: False}}
        last_mode_logged = None
        sweep_step = 0

        def _set_move_key(new_key):
            nonlocal held_move_key
            if held_move_key == new_key:
                return
            if held_move_key is not None:
                self.replayer._execute_key(held_move_key, is_down=False)
                held_move_key = None
            if new_key is not None:
                self.replayer._execute_key(new_key, is_down=True)
                held_move_key = new_key

        def _ensure_left_down(tx: int, ty: int):
            nonlocal left_mouse_held
            if not left_mouse_held:
                self.replayer._execute_mouse_button("left", is_down=True, x=int(tx), y=int(ty))
                left_mouse_held = True
            else:
                self.replayer._execute_mouse_move(int(tx), int(ty))

        def _release_automat_controls():
            nonlocal held_move_key, left_mouse_held
            _set_move_key(None)
            if left_mouse_held:
                self.replayer._execute_mouse_button("left", is_down=False)
                left_mouse_held = False
            self.replayer.release_all_inputs()

        try:
            while not self._stop_bot_event.is_set():
                try:
                    if is_hardware_esc_pressed():
                        self.log("🛑 [ESC] pressed -> Immediately stopping Auto-Mob!")
                        self._stop_bot_event.set()
                        break

                    if self._recovery_requested:
                        rec_type = self._recovery_requested
                        self._recovery_requested = None
                        _release_automat_controls()
                        self.log(f"⏸️ Auto-Mob paused for recovery ({rec_type})...")
                        self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                        if self._stop_bot_event.is_set():
                            break
                        if rec_type == "dungeon_complete":
                            self.loop_count += 1
                            self.log(f"🚪 Dungeon complete! Auto-Mob starting cycle #{self.loop_count}.")
                        else:
                            self.log("✅ Recovery run complete! Auto-Mob resuming work.")
                        last_enemy_seen_time = 0.0
                        last_mode_logged = None
                        time.sleep(0.8)
                        continue

                    now = time.perf_counter()
                    move_dir = str(self.config.get("automat_move_key", "d")).lower().strip()
                    if move_dir not in ("d", "a", "stand"):
                        move_dir = "d"
                    is_stand_mode = (move_dir == "stand")
                    linger_seconds = max(0.0, float(self.config.get("automat_combat_linger_seconds", 3.0)))
                    skill_cd = max(0.25, float(self.config.get("automat_skill_cooldown", 0.55)))

                    screen = self.detector.capture_screen()
                    enemies = self.detector.detect_enemy_hp_bars(screen)
                    sweep_step += 1

                    if enemies:
                        last_enemy_seen_time = now
                        primary = enemies[0]
                        last_target_pos = (primary["target_x"], primary["target_y"])

                    time_since_enemy = now - last_enemy_seen_time if last_enemy_seen_time > 0 else 9999.0
                    in_combat = (len(enemies) > 0) or (time_since_enemy <= linger_seconds)

                    if in_combat:
                        # --- STATE 2: COMBAT + POST-COMBAT LINGER ---
                        if len(enemies) > 0:
                            primary = enemies[0]
                            tx, ty = primary["target_x"], primary["target_y"]
                            ex = primary["x"]
                            enemy_count = len(enemies)

                            # Position character toward enemy if outside ideal attack zone, unless in Stand mode
                            char_x, _, scale = self.detector.get_character_center()
                            zone_left = char_x - int(140 * scale)
                            zone_right = char_x + int(160 * scale)

                            if is_stand_mode:
                                desired_key = None
                            elif ex > zone_right:
                                desired_key = "d"
                            elif ex < zone_left:
                                desired_key = "a"
                            else:
                                desired_key = None

                            _set_move_key(desired_key)
                            _ensure_left_down(tx, ty)

                            state_msg = f"🤖 AUTO-MOB: Combat {'[Stand] ' if is_stand_mode else ''}({enemy_count} enemies) | Target [{tx}, {ty}]"
                            self.automat_hud_status = f"⚔️ Combat {'[Stand] ' if is_stand_mode else ''}({enemy_count} enemies)"
                            if last_mode_logged != "combat":
                                last_mode_logged = "combat"
                                self.log(f"🎯 Detected enemy ({enemy_count}x HP bar) at [{tx}, {ty}] -> Attacking with skills{' (Stand - in place)' if is_stand_mode else ''}!")
                        else:
                            # Linger phase: enemy HP bar disappeared recently (< linger_seconds ago)
                            rem_linger = max(0.0, linger_seconds - time_since_enemy)
                            # Stand still and sweep around last known target / ahead to finish off or re-detect mobs
                            _set_move_key(None)
                            base_x, base_y = last_target_pos
                            offset_x = int(95 * math.sin(sweep_step * 0.75))
                            offset_y = int(28 * math.cos(sweep_step * 0.55))
                            tx = max(350, min(1580, base_x + offset_x))
                            ty = max(260, min(720, base_y + offset_y))
                            _ensure_left_down(tx, ty)

                            state_msg = f"🤖 AUTO-MOB: Combat linger ({rem_linger:.1f}s) - verifying room is clear..."
                            self.automat_hud_status = f"⏳ Combat linger ({rem_linger:.1f}s)"

                        self._set_state(BotState.EXECUTING_RUN, state_msg)

                        # Periodically check HUD for Mana & Skills 1, 3, 4, 5 readiness (every ~0.18s)
                        if now - last_ui_check_time >= 0.18:
                            last_ui_check_time = now
                            cached_ui_state = self.detector.get_skills_and_mana_state(screen)

                        # Fire skills ONLY in combat / linger if global skill cooldown elapsed
                        last_skill_cast_time = self._try_cast_automat_skills(
                            cached_ui_state, len(enemies), now, last_skill_cast_time, skill_cd
                        )

                    else:
                        # --- STATE 1: ADVANCE / STAND SCAN (ROOM CLEAR) ---
                        self._aoe_pack_seen_time = 0.0
                        self._aoe_pack_max_mobs = 0
                        if is_stand_mode:
                            if last_mode_logged != "advance":
                                self.log("🧍 AUTO-MOB [Stand]: Standing still, shooting and waiting for enemies...")
                                last_mode_logged = "advance"
                            _set_move_key(None)
                            tx, ty = self._compute_advance_aim("d", sweep_step)
                            _ensure_left_down(tx, ty)
                            self._set_state(
                                BotState.EXECUTING_RUN,
                                "🤖 AUTO-MOB [Stand]: Standing still + Shooting (Waiting for enemies...)"
                            )
                            self.automat_hud_status = "🧍 Stand: Standing still + Shooting"
                        else:
                            if last_mode_logged != "advance":
                                if last_mode_logged == "combat":
                                    self.log(f"✅ Screen clear (no enemies for {linger_seconds:.1f}s) -> Advancing [{move_dir.upper()}] and shooting ahead.")
                                else:
                                    self.log(f"🏃 AUTO-MOB: Advancing [{move_dir.upper()}] and scanning enemies ahead...")
                                last_mode_logged = "advance"

                            _set_move_key(move_dir)

                            # Periodic jump (W) during advance to clear stairs/obstacles (if interval > 0)
                            jump_interval = float(self.config.get("automat_jump_interval", 10.0))
                            if jump_interval > 0.0 and (now - last_jump_time >= jump_interval):
                                last_jump_time = now
                                self._press_skill_key_quick("w")

                            # Compute aim point ahead of character using configured shoot angle & spread
                            tx, ty = self._compute_advance_aim(move_dir, sweep_step)

                            _ensure_left_down(tx, ty)
                            self._set_state(
                                BotState.EXECUTING_RUN,
                                f"🤖 AUTO-MOB: Advance [{move_dir.upper()}] + Shoot Ahead (Scanning for mobs...)"
                            )
                            self.automat_hud_status = f"🏃 Advance [{move_dir.upper()}] + Shooting ahead"

                    time.sleep(0.055)
                except Exception as e:
                    self.log(f"❌ Error in Auto-Mob loop: {e}")
                    time.sleep(0.2)
        finally:
            _release_automat_controls()
            dur_auto = max(0.0, time.perf_counter() - self.automat_hud_start_time)
            self.automat_hud_last_finish = {
                "duration": dur_auto,
                "title": "🤖 AUTO-MOB STOPPED",
                "status": "Auto-Mob mode was stopped",
                "hint": "Bot is in IDLE state (Ready)."
            }
            self.automat_hud_active = False
            self._set_state(BotState.IDLE, "Auto-Mob stopped.")
            self.log("⏹ Auto-Mob mode stopped.")

    def _watchdog_loop(self):
        """Monitors screen for Angel (Death), Lost Connection, Server Reconnect, Lobby or Dungeon Complete while bot is active."""
        death_thresh = float(self.config.get("death_threshold", 0.75))
        disc_thresh = float(self.config.get("disconnect_threshold", 0.75))
        server_reconnect_thresh = float(self.config.get("server_reconnect_threshold", 0.75))
        lobby_thresh = float(self.config.get("lobby_threshold", 0.75))
        comp_thresh = float(self.config.get("dungeon_complete_threshold", 0.75))

        while not self._stop_bot_event.is_set():
            if is_hardware_esc_pressed():
                self.log("🛑 [ESC] pressed -> Emergency stop triggered!")
                self._stop_bot_event.set()
                self.replayer.stop()
                break

            if self.state == BotState.EXECUTING_RUN and not self._recovery_requested:
                try:
                    screen = self.detector.capture_screen()

                    # 1. Check Server Reconnect (full client disconnect screen)
                    if self.config.get("enable_server_reconnect_recovery", True):
                        found_sr, score_sr, loc_sr, name_sr = self.detector.check_server_reconnect(screen, threshold=server_reconnect_thresh)
                        if found_sr:
                            score_pct = round(score_sr * 100, 1)
                            self.log(f"🌐 SERVER DISCONNECT DETECTED! Detected '{name_sr}' with match {score_pct}%. Starting Server Reconnect Run...")
                            self._trigger_recovery("server_reconnect")
                            time.sleep(1.0)
                            continue

                    # 2. Check Lobby (return to city/town)
                    if self.config.get("enable_lobby_recovery", True):
                        found_lb, score_lb, loc_lb, name_lb = self.detector.check_lobby(screen, threshold=lobby_thresh)
                        if found_lb:
                            score_pct = round(score_lb * 100, 1)
                            self.log(f"🏰 TOWN / LOBBY DETECTED! Detected '{name_lb}' with match {score_pct}%. Starting Lobby Run...")
                            self._trigger_recovery("lobby")
                            time.sleep(1.0)
                            continue

                    # 3. Check Death / Angel
                    if self.config.get("enable_death_recovery", True):
                        found_death, score_d, loc_d, name_d = self.detector.check_death(screen, threshold=death_thresh)
                        if found_death:
                            now = time.perf_counter()
                            # Cooldown: Ignore re-detection of the lingering angel graphic from the same death incident
                            if now - self._last_death_incident_time < 12.0:
                                time.sleep(0.5)
                                continue

                            self._last_death_incident_time = now
                            score_pct = round(score_d * 100, 1)
                            self.log(
                                f"🚨 DEATH DETECTED (ANGEL)! Detected '{name_d}' with match {score_pct}%. "
                                f"Starting Revive Run and resuming combat."
                            )
                            self._trigger_recovery("death")
                            time.sleep(1.0)
                            continue

                    # 4. Check Disconnect (in-game popup)
                    if self.config.get("enable_disconnect_recovery", True):
                        found_disc, score_dc, loc_dc, name_dc = self.detector.check_disconnect(screen, threshold=disc_thresh)
                        if found_disc:
                            score_pct = round(score_dc * 100, 1)
                            self.log(f"🚨 LOST CONNECTION DETECTED! Detected '{name_dc}' with match {score_pct}%.")
                            self._trigger_recovery("disconnect")
                            time.sleep(1.0)
                            continue

                    # 5. Check Dungeon Complete / Exit Dungeon
                    if self.config.get("enable_dungeon_complete_recovery", True):
                        found_comp, score_c, loc_c, name_c = self.detector.check_dungeon_complete(screen, threshold=comp_thresh)
                        if found_comp:
                            score_pct = round(score_c * 100, 1)
                            self.log(f"🚪 DUNGEON COMPLETE DETECTED! Detected '{name_c}' with match {score_pct}%.")
                            self._trigger_recovery("dungeon_complete")
                            time.sleep(1.0)
                            continue

                    # 6. Check Auto-Heal (HP Orb & Skill 2)
                    # This check executes in parallel and NEVER interrupts or pauses the combat run!
                    if self.config.get("enable_auto_heal", True):
                        try:
                            heal_info = self.detector.get_hp_and_skill_state(screen)
                            self.last_ui_found = heal_info.get("found_ui", False)
                            if self.last_ui_found:
                                self.last_hp_percent = heal_info.get("hp_percent", 100.0)
                                self.last_skill_ready = heal_info.get("skill_ready", False)

                                thresh = float(self.config.get("heal_hp_threshold", 40.0))
                                heal_key = str(self.config.get("heal_key", "2")).strip()
                                cooldown = float(self.config.get("heal_cooldown_seconds", 2.0))
                                now = time.perf_counter()

                                if self.last_hp_percent <= thresh and self.last_skill_ready:
                                    if now - self._last_heal_time >= cooldown:
                                        self._last_heal_time = now
                                        self.heal_count += 1
                                        self.log(
                                            f"🧪 AUTO-HEAL: HP dropped to {self.last_hp_percent:.0f}% (threshold: {thresh:.0f}%). "
                                            f"Skill '{heal_key}' is ready (Colored) -> Pressing [{heal_key}]!"
                                        )
                                        self._execute_quick_heal(heal_key)
                        except Exception:
                            pass

                    # 7. Check Automat Assist during Recorded Combat Run (if enabled and not already in assist combat)
                    if (
                        self._in_recorded_combat_run
                        and not self._in_automat_assist_combat
                        and self.config.get("enable_automat_assist", False)
                    ):
                        enemies_assist = self.detector.detect_enemy_hp_bars(screen)
                        if enemies_assist:
                            self.log(
                                f"🤖 AUTO-MOB ASSIST: Detected {len(enemies_assist)} mobov during recorded run! "
                                f"Pausing run in place and engaging Auto-Mob combat..."
                            )
                            self._trigger_recovery("automat_assist")
                            time.sleep(0.5)
                            continue

                except Exception as e:
                    pass

            time.sleep(0.28)

    def _execute_quick_heal(self, key_str: str):
        """Quickly fires the heal skill key in background without interrupting or stopping the combat run playback."""
        def _press():
            try:
                k = key_str.lower().strip()
                if not k:
                    return
                import pydirectinput
                if k in pydirectinput.KEYBOARD_MAPPING:
                    pydirectinput.keyDown(k)
                    time.sleep(0.04)
                    pydirectinput.keyUp(k)
                else:
                    self.replayer._execute_key(k, is_down=True)
                    time.sleep(0.04)
                    self.replayer._execute_key(k, is_down=False)
            except Exception as e:
                self.log(f"⚠️ Error pressing heal key [{key_str}]: {e}")

        threading.Thread(target=_press, daemon=True).start()

    def _trigger_recovery(self, recovery_type: str):
        """Signals the main bot loop to pause/abort current run and execute recovery."""
        self._recovery_requested = recovery_type
        self.replayer.stop()

    def _execute_automat_assist_combat(self):
        """
        Executes stationary Automat combat when enemies are detected during a recorded run:
        - Stands strictly in place (releases W/A/S/D so door/parkour alignment is preserved).
        - Aims at detected enemy HP bars, holds left mouse button, and fires Skills 4, 5, 3 (AoE), or 1 (Spam).
        - Continues for `automat_combat_linger_seconds` after the last HP bar disappears.
        - Exits immediately if a real recovery event (death, disconnect, etc.) or stop is triggered.
        """
        self._in_automat_assist_combat = True
        self.replayer.release_all_inputs()
        self._aoe_pack_seen_time = 0.0
        self._aoe_pack_max_mobs = 0

        self.automat_hud_start_time = time.perf_counter()
        self.automat_hud_title = "🤖 AUTO-MOB ASSIST ON"
        self.automat_hud_status = "Likvidujem mobov na mieste..."
        self.automat_hud_hint = "Combat run resumes after mobs are cleared | [ESC] Stop"
        self.automat_hud_active = True

        linger_seconds = max(0.0, float(self.config.get("automat_combat_linger_seconds", 3.0)))
        skill_cd = max(0.25, float(self.config.get("automat_skill_cooldown", 0.55)))
        move_dir = str(self.config.get("automat_move_key", "d")).lower().strip()

        last_enemy_seen_time = time.perf_counter()
        last_target_pos = (1120, 520) if move_dir != "a" else (800, 520)
        last_skill_cast_time = 0.0
        last_ui_check_time = 0.0
        cached_ui_state = {"found_ui": False, "mana_percent": 100.0, "skills_ready": {1: False, 3: False, 4: False, 5: False}}
        left_mouse_held = False
        sweep_step = 0

        try:
            while not self._stop_bot_event.is_set():
                if is_hardware_esc_pressed():
                    self._stop_bot_event.set()
                    break
                # If a real recovery (Death, Disconnect, Server, Lobby, Exit) was triggered by Watchdog, abort assist immediately
                if self._recovery_requested and self._recovery_requested != "automat_assist":
                    break

                now = time.perf_counter()
                linger_seconds = max(0.0, float(self.config.get("automat_combat_linger_seconds", 3.0)))
                skill_cd = max(0.25, float(self.config.get("automat_skill_cooldown", 0.55)))

                screen = self.detector.capture_screen()
                enemies = self.detector.detect_enemy_hp_bars(screen)
                sweep_step += 1

                if enemies:
                    last_enemy_seen_time = now
                    primary = enemies[0]
                    tx, ty = primary["target_x"], primary["target_y"]
                    last_target_pos = (tx, ty)
                    state_msg = f"🤖 AUTO-MOB ASSIST: Combat in place ({len(enemies)} enemies) | Target [{tx}, {ty}]"
                    self.automat_hud_status = f"⚔️ Combat in place ({len(enemies)} enemies)"
                else:
                    time_since = now - last_enemy_seen_time
                    if time_since > linger_seconds:
                        self.log(f"✅ Auto-Mob Assist: Mobs eliminated (room clear after {linger_seconds:.1f}s) -> Resuming recorded run!")
                        break
                    rem = max(0.0, linger_seconds - time_since)
                    base_x, base_y = last_target_pos
                    offset_x = int(95 * math.sin(sweep_step * 0.75))
                    offset_y = int(28 * math.cos(sweep_step * 0.55))
                    tx = max(350, min(1580, base_x + offset_x))
                    ty = max(260, min(720, base_y + offset_y))
                    state_msg = f"🤖 AUTO-MOB ASSIST: Attack linger ({rem:.1f}s) before resuming run..."
                    self.automat_hud_status = f"⏳ Combat linger ({rem:.1f}s)"

                if not left_mouse_held:
                    self.replayer._execute_mouse_button("left", is_down=True, x=int(tx), y=int(ty))
                    left_mouse_held = True
                else:
                    self.replayer._execute_mouse_move(int(tx), int(ty))

                self._set_state(BotState.EXECUTING_RUN, state_msg)

                if now - last_ui_check_time >= 0.18:
                    last_ui_check_time = now
                    cached_ui_state = self.detector.get_skills_and_mana_state(screen)

                last_skill_cast_time = self._try_cast_automat_skills(
                    cached_ui_state, len(enemies), now, last_skill_cast_time, skill_cd
                )

                time.sleep(0.055)
        finally:
            if left_mouse_held:
                self.replayer._execute_mouse_button("left", is_down=False)
            self.replayer.release_all_inputs()
            self._in_automat_assist_combat = False
            dur_ast = max(0.0, time.perf_counter() - self.automat_hud_start_time)
            self.automat_hud_last_finish = {
                "duration": dur_ast,
                "title": "🤖 AUTO-MOB ASSIST OFF",
                "status": "✅ Mobs eliminated!",
                "hint": "Resuming recorded combat run..."
            }
            self.automat_hud_active = False

    def _execute_puzzle_automat_step(self, step_label: str = "🤖 AUTO-MOB", return_to_origin: bool = True) -> bool:
        """
        Executes a Puzzle '🤖 AUTOMAT' room-clear step:
        - Chases detected mobs left ('a') and right ('d') while tracking exact net horizontal movement time
          (`net_move_time`: +dt when holding 'd', -dt when holding 'a').
        - Aims at detected enemy HP bars, holds left mouse button, and fires Skills 4, 5, 3 (AoE), and 1 (Single).
        - Sweeps/shoots for `automat_combat_linger_seconds` after the last enemy HP bar disappears.
        - Once the room is confirmed clear, if `return_to_origin=True` and `abs(net_move_time) > 0.08`,
          automatically walks the character back to the exact starting spot where the step began!
        - Returns True if the room was cleared and return-to-origin finished; False if interrupted by recovery or stop.
        """
        self.replayer.release_all_inputs()
        self._aoe_pack_seen_time = 0.0
        self._aoe_pack_max_mobs = 0

        linger_seconds = max(1.0, float(self.config.get("automat_combat_linger_seconds", 3.0)))
        skill_cd = max(0.25, float(self.config.get("automat_skill_cooldown", 0.55)))
        move_dir = str(self.config.get("automat_move_key", "d")).lower().strip()
        if move_dir not in ("d", "a", "stand"):
            move_dir = "d"
        is_stand_mode = (move_dir == "stand")

        mode_tag = "STAND" if is_stand_mode else move_dir.upper()
        self.automat_hud_start_time = time.perf_counter()
        self.automat_hud_title = f"🤖 AUTO-MOB ACTIVE [{mode_tag}]: {step_label}"
        self.automat_hud_status = "Scanning and clearing room..."
        self.automat_hud_hint = (
            "Press [F1] to record movement or [ESC] for Stop"
            if self._in_live_puzzle_automat
            else "Next Puzzle step continues after room is clear | [ESC] Stop"
        )
        self.automat_hud_active = True

        last_enemy_seen_time = time.perf_counter()
        last_target_pos = (1120, 520) if move_dir != "a" else (800, 520)
        last_skill_cast_time = 0.0
        last_ui_check_time = 0.0
        cached_ui_state = {"found_ui": False, "mana_percent": 100.0, "skills_ready": {1: False, 3: False, 4: False, 5: False}}

        held_move_key = None
        last_move_tick = time.perf_counter()
        net_move_time = 0.0  # +seconds moved right ('d'), -seconds moved left ('a')
        left_mouse_held = False
        sweep_step = 0

        def _update_move_displacement():
            nonlocal last_move_tick, net_move_time
            t_now = time.perf_counter()
            dt = max(0.0, t_now - last_move_tick)
            last_move_tick = t_now
            if held_move_key == "d":
                net_move_time += dt
            elif held_move_key == "a":
                net_move_time -= dt

        def _set_move_key(new_key):
            nonlocal held_move_key
            _update_move_displacement()
            if held_move_key == new_key:
                return
            if held_move_key is not None:
                self.replayer._execute_key(held_move_key, is_down=False)
                held_move_key = None
            if new_key is not None:
                self.replayer._execute_key(new_key, is_down=True)
                held_move_key = new_key

        completed_room = False
        try:
            while not self._stop_bot_event.is_set():
                if is_hardware_esc_pressed():
                    self.log("🛑 [ESC] pressed -> Immediately stopping Puzzle Auto-Mob step!")
                    self._stop_bot_event.set()
                    break

                if self._recovery_requested and self._recovery_requested != "automat_assist":
                    break

                _update_move_displacement()
                now = time.perf_counter()
                linger_seconds = max(1.0, float(self.config.get("automat_combat_linger_seconds", 3.0)))
                skill_cd = max(0.25, float(self.config.get("automat_skill_cooldown", 0.55)))
                move_dir = str(self.config.get("automat_move_key", "d")).lower().strip()
                if move_dir not in ("d", "a", "stand"):
                    move_dir = "d"
                is_stand_mode = (move_dir == "stand")

                screen = self.detector.capture_screen()
                enemies = self.detector.detect_enemy_hp_bars(screen)
                sweep_step += 1

                if enemies:
                    last_enemy_seen_time = now
                    primary = enemies[0]
                    tx, ty = primary["target_x"], primary["target_y"]
                    ex = primary["x"]
                    last_target_pos = (tx, ty)

                    char_x, _, scale = self.detector.get_character_center()
                    zone_left = char_x - int(140 * scale)
                    zone_right = char_x + int(160 * scale)

                    if is_stand_mode:
                        desired_key = None
                    elif ex > zone_right:
                        desired_key = "d"
                    elif ex < zone_left:
                        desired_key = "a"
                    else:
                        desired_key = None

                    _set_move_key(desired_key)
                    if is_stand_mode:
                        state_msg = f"🤖 {step_label} [Stand]: Combat in place ({len(enemies)} enemies) | Target [{tx}, {ty}]"
                        self.automat_hud_status = f"⚔️ Combat in place ({len(enemies)} enemies)"
                    else:
                        state_msg = f"🤖 {step_label}: Combat ({len(enemies)} enemies) | Shift: {net_move_time:+.1f}s"
                        self.automat_hud_status = f"⚔️ Combat ({len(enemies)} enemies) | Shift {net_move_time:+.1f}s"
                else:
                    _set_move_key(None)
                    time_since = now - last_enemy_seen_time
                    if time_since > linger_seconds:
                        completed_room = True
                        break
                    rem = max(0.0, linger_seconds - time_since)
                    # Alternate sweeping around last target and ahead of character to reveal any unhit mob
                    if sweep_step % 6 < 4:
                        base_x, base_y = last_target_pos
                        offset_x = int(110 * math.sin(sweep_step * 0.75))
                        offset_y = int(30 * math.cos(sweep_step * 0.55))
                        tx = max(350, min(1580, base_x + offset_x))
                        ty = max(260, min(720, base_y + offset_y))
                    else:
                        tx, ty = self._compute_advance_aim(move_dir, sweep_step)
                    if is_stand_mode:
                        state_msg = f"🤖 {step_label} [Stand]: Combat linger in place ({rem:.1f}s)..."
                        self.automat_hud_status = f"⏳ Linger in place ({rem:.1f}s)"
                    else:
                        state_msg = f"🤖 {step_label}: Combat linger ({rem:.1f}s) | Shift: {net_move_time:+.1f}s"
                        self.automat_hud_status = f"⏳ Linger ({rem:.1f}s) | Shift {net_move_time:+.1f}s"

                if not left_mouse_held:
                    self.replayer._execute_mouse_button("left", is_down=True, x=int(tx), y=int(ty))
                    left_mouse_held = True
                else:
                    self.replayer._execute_mouse_move(int(tx), int(ty))

                self._set_state(BotState.EXECUTING_RUN, state_msg)

                if now - last_ui_check_time >= 0.18:
                    last_ui_check_time = now
                    cached_ui_state = self.detector.get_skills_and_mana_state(screen)

                last_skill_cast_time = self._try_cast_automat_skills(
                    cached_ui_state, len(enemies), now, last_skill_cast_time, skill_cd
                )

                time.sleep(0.055)

            # Stop attacking before returning to origin
            _set_move_key(None)
            if left_mouse_held:
                self.replayer._execute_mouse_button("left", is_down=False)
                left_mouse_held = False

            # Return to Origin if room was cleared and character moved away from the starting spot
            if completed_room and return_to_origin and abs(net_move_time) > 0.08 and not self._stop_bot_event.is_set():
                ret_key = "a" if net_move_time > 0 else "d"
                ret_dur = min(abs(net_move_time), 10.0)
                dir_word = "left [A]" if ret_key == "a" else "right [D]"
                self.log(f"↩️ {step_label}: Room clear! Returning character to starting mark ({ret_dur:.2f}s {dir_word})...")
                self._set_state(BotState.EXECUTING_RUN, f"↩️ {step_label}: Returning to mark ({ret_dur:.1f}s [{ret_key.upper()}])...")
                self.automat_hud_status = f"↩️ Returning to mark ({ret_dur:.1f}s [{ret_key.upper()}])"

                self.replayer._execute_key(ret_key, is_down=True)
                t_ret_start = time.perf_counter()
                try:
                    while (time.perf_counter() - t_ret_start) < ret_dur:
                        if self._stop_bot_event.is_set() or is_hardware_esc_pressed():
                            self._stop_bot_event.set()
                            completed_room = False
                            break
                        if self._recovery_requested and self._recovery_requested != "automat_assist":
                            completed_room = False
                            break
                        time.sleep(0.02)
                finally:
                    self.replayer._execute_key(ret_key, is_down=False)

            return completed_room
        finally:
            _set_move_key(None)
            if left_mouse_held:
                self.replayer._execute_mouse_button("left", is_down=False)
            self.replayer.release_all_inputs()
            dur_step = max(0.0, time.perf_counter() - self.automat_hud_start_time)
            self.automat_hud_last_finish = {
                "duration": dur_step,
                "title": f"🤖 AUTO-MOB STOPPED: {step_label}",
                "status": "✅ Room cleared!" if completed_room else "⏹ Auto-Mob finished",
                "hint": (
                    "Press [F1] to record next movement!"
                    if self._in_live_puzzle_automat
                    else "Continuing to next step in Puzzle run..."
                )
            }
            self.automat_hud_active = False

    def start_live_puzzle_automat_step(self, step_name: str = "🤖 AUTO-MOB"):
        """
        Launched when user presses F2 in-game during Puzzle building:
        Immediately executes the newly added 🤖 AUTOMAT step live in the game to clear the room,
        walks the character back to the starting position where F2 was pressed, and returns to IDLE
        so the user can press F1 to record the next movement step.
        """
        if self.state != BotState.IDLE:
            self.log("⚠️ Bot is not currently IDLE.")
            return

        self._stop_bot_event.clear()
        self._recovery_requested = None
        self._in_recorded_combat_run = False
        self._in_automat_assist_combat = False
        self._in_live_puzzle_automat = True

        self.bot_start_time = time.perf_counter()
        self.detector.reload_templates()

        def _live_worker():
            revive_file = self.get_run_filepath("revive")
            reconnect_file = self.get_run_filepath("reconnect")
            server_reconnect_file = self.get_run_filepath("server_reconnect")
            lobby_file = self.get_run_filepath("lobby")
            exit_file = self.get_run_filepath("exit")

            self._play_sound("run_start")
            self.log(f"🤖 Live Puzzle step [{step_name}] engaged! Clearing room and returning to origin marker...")

            try:
                while not self._stop_bot_event.is_set():
                    finished = self._execute_puzzle_automat_step(step_label=step_name, return_to_origin=True)
                    if self._recovery_requested and self._recovery_requested != "automat_assist":
                        rec_type = self._recovery_requested
                        self._recovery_requested = None
                        self.log(f"⏸️ Live Puzzle Auto-Mob paused for recovery ({rec_type})...")
                        self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                        if self._stop_bot_event.is_set() or rec_type == "dungeon_complete":
                            break
                        self.log("🔄 Recovery finished -> Completing live room clear...")
                        time.sleep(0.6)
                        continue
                    if finished:
                        self._play_sound("victory")
                        self.log(
                            f"✅ [{step_name}] complete! Room is clear and character is back at marker. "
                            f"You can now press [F1] to record your next movement step!"
                        )
                    break
            finally:
                self._in_live_puzzle_automat = False
                self.replayer.release_all_inputs()
                self._set_state(BotState.IDLE, f"{step_name} completed (press F1 for next step).")

        self._bot_thread = threading.Thread(target=_live_worker, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._bot_thread.start()
        self._watchdog_thread.start()

    def _run_loop(self):
        main_file = self.get_run_filepath("main")
        revive_file = self.get_run_filepath("revive")
        reconnect_file = self.get_run_filepath("reconnect")
        server_reconnect_file = self.get_run_filepath("server_reconnect")
        lobby_file = self.get_run_filepath("lobby")
        exit_file = self.get_run_filepath("exit")
        combat_name = self.config.get("selected_combat_run", "predvoleny_run")

        run_data = config.load_combat_run_data(main_file)
        is_segmented = bool(run_data.get("is_segmented") and run_data.get("segments"))
        segments = run_data.get("segments", []) if is_segmented else []
        main_events = run_data.get("events", [])

        if is_segmented:
            self.is_segmented_run = True
            self.total_steps = len(segments)
            self.log(f"🧩 Loaded Puzzle Run [{combat_name}] s {len(segments)} steps.")
        else:
            self.is_segmented_run = False
            self.total_steps = 1
            self.current_step_index = 0
            self.current_step_name = combat_name

        start_delay = float(self.config.get("start_delay", 3.0))

        self.log(f"⚡ Automatic bot started with profile [{combat_name}]! Initial countdown: {start_delay:.1f}s")

        # Initial countdown
        if start_delay > 0:
            delay_start = time.perf_counter()
            while time.perf_counter() - delay_start < start_delay:
                if self._stop_bot_event.is_set():
                    self._set_state(BotState.IDLE, "Stopped.")
                    return
                if self._recovery_requested:
                    break
                remaining = max(0.0, start_delay - (time.perf_counter() - delay_start))
                self._set_state(BotState.COUNTDOWN, f"Starting in {remaining:.1f}s - switch to game!")
                time.sleep(0.05)

        self.paused_run_index = 0
        self.paused_step_index = 0

        while not self._stop_bot_event.is_set():
            if self._recovery_requested:
                rec_type = self._recovery_requested
                self._recovery_requested = None
                if rec_type == "automat_assist":
                    self._execute_automat_assist_combat()
                    if self._stop_bot_event.is_set():
                        break
                    continue
                self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                if self._stop_bot_event.is_set():
                    break
                time.sleep(1.2)
                continue

            # Reload run data in case user updated segments
            run_data = config.load_combat_run_data(main_file)
            is_segmented = bool(run_data.get("is_segmented") and run_data.get("segments"))
            segments = run_data.get("segments", []) if is_segmented else []
            self.is_segmented_run = is_segmented
            self.total_steps = len(segments) if is_segmented else 1

            if is_segmented:
                # --- PUZZLE RUN (STEP BY STEP) ---
                start_step = self.paused_step_index
                start_evt = self.paused_run_index

                if start_step == 0 and start_evt == 0:
                    self.loop_count += 1
                    self.log(f"⚔️ [Cycle #{self.loop_count}] Starting Puzzle Run [{combat_name}] ({len(segments)} steps)...")
                    self._play_sound("run_start")
                else:
                    self.log(f"⚔️ [Cyklus #{self.loop_count}] Resuming Puzzle Run from Step {start_step + 1}/{len(segments)} (action #{start_evt})...")

                cycle_interrupted = False

                for step_idx in range(start_step, len(segments)):
                    if self._stop_bot_event.is_set() or self._recovery_requested or is_hardware_esc_pressed():
                        if is_hardware_esc_pressed():
                            self._stop_bot_event.set()
                        break

                    seg = segments[step_idx]
                    seg_type = seg.get("type", "recorded")
                    self.current_step_index = step_idx
                    self.current_step_name = seg.get("name", f"Krok {step_idx + 1}")

                    # --- CASE A: PUZZLE '🤖 AUTOMAT' ROOM-CLEAR STEP ---
                    if seg_type == "automat":
                        self.log(
                            f"🤖 [Cyklus #{self.loop_count}] Krok {step_idx + 1}/{len(segments)}: "
                            f"[{self.current_step_name}] -> Clearing room and returning to marker..."
                        )
                        prev_recorded_flag = self._in_recorded_combat_run
                        self._in_recorded_combat_run = False
                        try:
                            finished = self._execute_puzzle_automat_step(
                                step_label=f"Krok {step_idx + 1}/{len(segments)}: {self.current_step_name}",
                                return_to_origin=True
                            )
                        finally:
                            self._in_recorded_combat_run = prev_recorded_flag

                        if self._recovery_requested:
                            rec_type = self._recovery_requested
                            self._recovery_requested = None
                            if rec_type == "automat_assist":
                                continue

                            if rec_type in ("death", "disconnect", "server_reconnect", "lobby"):
                                if rec_type == "death":
                                    rec_label, rec_done = "DEATH (Angel)", "Revive"
                                elif rec_type == "disconnect":
                                    rec_label, rec_done = "LOST CONNECTION", "Reconnect"
                                elif rec_type == "server_reconnect":
                                    rec_label, rec_done = "SERVER DISCONNECT", "Server Reconnected"
                                else:
                                    rec_label, rec_done = "TOWN / LOBBY RETURN", "Lobby Return"

                                self.paused_step_index = step_idx
                                self.paused_run_index = 0
                                self.log(
                                    f"⏸️ Puzzle AUTOMAT Krok {step_idx + 1}/{len(segments)} [{self.current_step_name}] "
                                    f"PAUSED ({rec_label}). After recovery, 🤖 AUTO-MOB will resume in this room!"
                                )
                            else:
                                self.paused_step_index = 0
                                self.paused_run_index = 0

                            self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                            if self._stop_bot_event.is_set():
                                break

                            if rec_type in ("death", "disconnect", "server_reconnect", "lobby"):
                                self.log(
                                    f"✅ {rec_done} completed! Returning directly to 🤖 AUTO-MOB Step "
                                    f"{self.paused_step_index + 1}/{len(segments)} [{self.current_step_name}], "
                                    f"clearing room and resuming run!"
                                )
                                cycle_interrupted = True
                                break
                            elif rec_type == "dungeon_complete":
                                self.log("🚪 Dungeon completion finished! Starting new combat cycle.")
                                cycle_interrupted = True
                                break
                            else:
                                cycle_interrupted = True
                                break

                        if not finished or self._stop_bot_event.is_set():
                            self.paused_step_index = 0
                            self.paused_run_index = 0
                            self.log("⏹ Run interrupted by user.")
                            cycle_interrupted = True
                            break

                        self.log(f"✅ Step {step_idx + 1}/{len(segments)}: [{self.current_step_name}] completed (room clear, character at marker)!")
                        continue

                    # --- CASE B: RECORDED MOVEMENT / COMBAT PUZZLE STEP ---
                    seg_events = seg.get("events", [])
                    total_seg_evts = len(seg_events)
                    
                    cur_evt_start = start_evt if step_idx == start_step else 0

                    if cur_evt_start > 0:
                        pct = int((cur_evt_start / total_seg_evts) * 100) if total_seg_evts > 0 else 0
                        self._set_state(
                            BotState.EXECUTING_RUN,
                            f"🧩 Krok {step_idx + 1}/{len(segments)}: {self.current_step_name} ({pct}% - od #{cur_evt_start}/{total_seg_evts})"
                        )
                    else:
                        self._set_state(
                            BotState.EXECUTING_RUN,
                            f"🧩 Krok {step_idx + 1}/{len(segments)}: {self.current_step_name}"
                        )
                    self.log(f"🧩 [Loop #{self.loop_count}] Step {step_idx + 1}/{len(segments)}: [{self.current_step_name}] ({seg.get('duration', 0)}s, {total_seg_evts} actions)...")

                    prev_segs_dur = sum(float(segments[i].get("duration", 0.0)) for i in range(step_idx))
                    evt_offset = float(seg_events[cur_evt_start].get("time", 0.0)) if (0 <= cur_evt_start < total_seg_evts) else 0.0
                    cycle_elapsed_offset = prev_segs_dur + evt_offset

                    finished, next_idx = self.replayer.play(
                        seg_events,
                        start_index=cur_evt_start,
                        is_combat_run=True,
                        cycle_elapsed_offset=cycle_elapsed_offset,
                        config_dict=self.config
                    )

                    # Interrupted by Watchdog (Death / Exit / Disconnect / Server Reconnect / Lobby / Automat Assist)
                    if self._recovery_requested:
                        rec_type = self._recovery_requested
                        self._recovery_requested = None

                        if rec_type == "automat_assist":
                            self.paused_step_index = step_idx
                            self.paused_run_index = next_idx
                            self.log(f"⏸️ Puzzle Step {step_idx + 1}/{len(segments)} paused at action #{next_idx}/{total_seg_evts} -> Auto-Mob eliminating mobs on spot...")
                            self._execute_automat_assist_combat()
                            if self._stop_bot_event.is_set():
                                break
                            # If a real recovery was triggered during assist combat, let the top of the loop handle it
                            cycle_interrupted = True
                            break

                        if rec_type in ("death", "disconnect", "server_reconnect", "lobby"):
                            if rec_type == "death":
                                rewind = float(self.config.get("death_rewind_seconds", 3.0))
                                rec_label = "DEATH (Angel)"
                            elif rec_type == "disconnect":
                                rewind = float(self.config.get("disconnect_rewind_seconds", 3.0))
                                rec_label = "LOST CONNECTION"
                            elif rec_type == "server_reconnect":
                                rewind = float(self.config.get("server_reconnect_rewind_seconds", 3.0))
                                rec_label = "SERVER DISCONNECT"
                            elif rec_type == "lobby":
                                rewind = float(self.config.get("lobby_rewind_seconds", 0.0))
                                rec_label = "LOBBY RETURN"

                            rewound_idx = config.find_rewind_index(seg_events, next_idx, rewind) if rewind > 0 else next_idx
                            self.paused_step_index = step_idx
                            self.paused_run_index = rewound_idx
                            if rewind > 0:
                                self.log(f"⏸️ Combat run PAUSED ({rec_label}) at Step {step_idx + 1}/{len(segments)} action #{next_idx}. ⏪ Rewound by {rewind:.1f}s to action #{rewound_idx}/{total_seg_evts}.")
                            else:
                                self.log(f"⏸️ Combat run PAUSED ({rec_label}) at Step {step_idx + 1}/{len(segments)} action #{next_idx}/{total_seg_evts}.")
                        else:
                            self.paused_step_index = 0
                            self.paused_run_index = 0

                        self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                        if self._stop_bot_event.is_set():
                            break

                        if rec_type in ("death", "disconnect", "server_reconnect", "lobby"):
                            if rec_type == "death": rec_done = "Revive"
                            elif rec_type == "disconnect": rec_done = "Znovupripojenie"
                            elif rec_type == "server_reconnect": rec_done = "Znovupripojenie k serveru"
                            elif rec_type == "lobby": rec_done = "Lobby Return"
                            self.log(f"✅ {rec_done} completed! Resuming combat from Step {self.paused_step_index + 1} (action #{self.paused_run_index})...")
                            cycle_interrupted = True
                            break

                        elif rec_type == "dungeon_complete":
                            self.log("🚪 Dungeon completion finished! Starting new combat cycle.")
                            cycle_interrupted = True
                            break
                        else:
                            self.log("🔄 Restarting combat cycle from the beginning...")
                            cycle_interrupted = True
                            break

                    if not finished or self._stop_bot_event.is_set():
                        self.paused_step_index = 0
                        self.paused_run_index = 0
                        self.log("⏹ Run interrupted by user.")
                        cycle_interrupted = True
                        break

                if cycle_interrupted:
                    if self._stop_bot_event.is_set():
                        break
                    time.sleep(1.0)
                    continue

                # All segments finished completely!
                self.paused_step_index = 0
                self.paused_run_index = 0
                self.log(f"✅ [Loop #{self.loop_count}] All puzzle steps of run [{combat_name}] completed successfully.")

            else:
                # --- STANDARD CONTINUOUS RUN ---
                start_idx = self.paused_run_index
                total_evts = len(main_events)
                self.current_step_index = 0
                self.current_step_name = combat_name

                if start_idx > 0 and start_idx < total_evts:
                    pct = int((start_idx / total_evts) * 100)
                    self._set_state(BotState.EXECUTING_RUN, f"Resuming combat ({pct}% - action #{start_idx}/{total_evts})...")
                    self.log(f"⚔️ [Loop #{self.loop_count}] Resuming combat run from action #{start_idx} of {total_evts}...")
                else:
                    self.loop_count += 1
                    start_idx = 0
                    self.paused_run_index = 0
                    self._set_state(BotState.EXECUTING_RUN, f"Cyklus #{self.loop_count} [{combat_name}]...")
                    self.log(f"⚔️ [Cycle #{self.loop_count}] Starting run [{combat_name}]...")
                    self._play_sound("run_start")

                cycle_elapsed_offset = float(main_events[start_idx].get("time", 0.0)) if (0 < start_idx < total_evts) else 0.0

                finished, next_idx = self.replayer.play(
                    main_events,
                    start_index=start_idx,
                    is_combat_run=True,
                    cycle_elapsed_offset=cycle_elapsed_offset,
                    config_dict=self.config
                )

                # Check if interrupted by death, disconnect, or Automat Assist
                if self._recovery_requested:
                    rec_type = self._recovery_requested
                    self._recovery_requested = None

                    if rec_type == "automat_assist":
                        self.paused_run_index = next_idx
                        pct = int((next_idx / total_evts) * 100) if total_evts > 0 else 0
                        self.log(f"⏸️ Combat run paused at action #{next_idx}/{total_evts} ({pct}%) -> Auto-Mob eliminating mobs on spot...")
                        self._execute_automat_assist_combat()
                        if self._stop_bot_event.is_set():
                            break
                        continue

                    if rec_type in ("death", "disconnect", "server_reconnect", "lobby"):
                        if rec_type == "death":
                            rewind = float(self.config.get("death_rewind_seconds", 3.0))
                            rec_label = "DEATH (Angel)"
                        elif rec_type == "disconnect":
                            rewind = float(self.config.get("disconnect_rewind_seconds", 3.0))
                            rec_label = "LOST CONNECTION"
                        elif rec_type == "server_reconnect":
                            rewind = float(self.config.get("server_reconnect_rewind_seconds", 3.0))
                            rec_label = "SERVER DISCONNECT"
                        elif rec_type == "lobby":
                            rewind = float(self.config.get("lobby_rewind_seconds", 0.0))
                            rec_label = "LOBBY RETURN"

                        rewound_idx = config.find_rewind_index(main_events, next_idx, rewind) if rewind > 0 else next_idx
                        self.paused_run_index = rewound_idx
                        pct = int((rewound_idx / total_evts) * 100) if total_evts > 0 else 0
                        if rewind > 0:
                            self.log(f"⏸️ Combat run PAUSED ({rec_label}) at action #{next_idx}. ⏪ Rewound by {rewind:.1f}s to action #{rewound_idx}/{total_evts} ({pct}%).")
                        else:
                            self.log(f"⏸️ Combat run PAUSED ({rec_label}) at action #{next_idx}/{total_evts} ({pct}%).")
                    else:
                        self.paused_run_index = 0

                    self._execute_recovery(rec_type, revive_file, reconnect_file, exit_file, server_reconnect_file, lobby_file)
                    if self._stop_bot_event.is_set():
                        break

                    if rec_type in ("death", "disconnect", "server_reconnect", "lobby") and self.paused_run_index < total_evts:
                        if rec_type == "death": rec_done = "Revive"
                        elif rec_type == "disconnect": rec_done = "Znovupripojenie"
                        elif rec_type == "server_reconnect": rec_done = "Znovupripojenie k serveru"
                        elif rec_type == "lobby": rec_done = "Lobby Return"
                        self.log(f"✅ {rec_done} completed! Resuming combat from action #{self.paused_run_index}...")

                    elif rec_type == "dungeon_complete":
                        self.log("🚪 Dungeon completion finished! Starting new combat cycle.")
                    else:
                        self.log("🔄 Restarting combat cycle from the beginning...")

                    time.sleep(1.0)
                    continue

                if not finished or self._stop_bot_event.is_set():
                    self.paused_run_index = 0
                    self.log("⏹ Run interrupted by user.")
                    break

                # Run completely finished!
                self.paused_run_index = 0
                self.log(f"✅ [Loop #{self.loop_count}] Run [{combat_name}] completed successfully.")

            # Clean cycle transition: release all inputs and give brief pause
            self.replayer.release_all_inputs()
            time.sleep(0.3)

            if self._recovery_requested:
                continue

            if self._stop_bot_event.is_set():
                break

        self.paused_run_index = 0
        self.paused_step_index = 0
        self._set_state(BotState.IDLE, "Bot stopped.")
        self.log(f"⏹ Automatic bot stopped. Total loops completed: {self.loop_count}.")

    def play_single_segment(self, segment_events: list, segment_name: str = "Step"):
        """Plays only a single segment 1x for testing."""
        if self.state != BotState.IDLE:
            self.log("⚠️ Cannot play step, bot is not IDLE.")
            return

        def _play_thread():
            try:
                self._set_state(BotState.EXECUTING_RUN, f"Test: 🧩 {segment_name}...")
                self.log(f"▶ Starting test replay of segment: [{segment_name}] ({len(segment_events)} actions)...")
                self.replayer.play(segment_events, start_index=0)
            except Exception as e:
                self.log(f"❌ Error playing segment: {e}")
            finally:
                self._set_state(BotState.IDLE, "Test completed.")
                self.log(f"⏹ Step testing [{segment_name}] completed.")

        threading.Thread(target=_play_thread, daemon=True).start()

    def _execute_recovery(self, rec_type: str, revive_file: str, reconnect_file: str, exit_file: str, server_reconnect_file: str = None, lobby_file: str = None):
        """Executes the specific recovery run when death, disconnect, server disconnect, lobby or dungeon complete is detected."""
        if server_reconnect_file is None:
            server_reconnect_file = self.get_run_filepath("server_reconnect")
        if lobby_file is None:
            lobby_file = self.get_run_filepath("lobby")

        if rec_type == "dungeon_complete":
            self._play_sound("victory")
            self.exit_count += 1
            self._set_state(BotState.RECOVERING_EXIT, f"🚪 Dungeon Complete (#{self.exit_count}) - Exit Run...")
            target_file = exit_file
            desc = f"Exit Run (#{self.exit_count})"
        elif rec_type == "death":
            self._play_sound("alarm")
            self.revive_count += 1
            self._set_state(BotState.RECOVERING_DEATH, f"👼 Death Recovery (#{self.revive_count}) - Revive Run...")
            target_file = revive_file
            desc = f"Revive Run (#{self.revive_count})"
        elif rec_type == "server_reconnect":
            self._play_sound("alarm")
            self.server_reconnect_count += 1
            self._set_state(BotState.RECOVERING_SERVER_RECONNECT, f"🌐 Server Reconnect (#{self.server_reconnect_count}) - Reconnect Run...")
            target_file = server_reconnect_file
            desc = f"Server Reconnect Run (#{self.server_reconnect_count})"
        elif rec_type == "lobby":
            self._play_sound("run_start")
            self.lobby_count += 1
            self._set_state(BotState.RECOVERING_LOBBY, f"🏰 Town / Lobby Return (#{self.lobby_count}) - Lobby Run...")
            target_file = lobby_file
            desc = f"Lobby Run (#{self.lobby_count})"
        else: # disconnect
            self._play_sound("alarm")
            self.disconnect_count += 1
            self._set_state(BotState.RECOVERING_DISCONNECT, f"🔌 Connection Lost (#{self.disconnect_count}) - Reconnect Run...")
            target_file = reconnect_file
            desc = f"Reconnect Run (#{self.disconnect_count})"

        self.log(f"🛡️ Running {desc} from file '{target_file}'...")

        if not os.path.exists(target_file):
            self.log(f"⚠️ File '{target_file}' does not exist! Recovery run could not be executed.")
            time.sleep(2.0)
            return

        try:
            rec_events = self.replayer.load_run(target_file)
            finished, _ = self.replayer.play(rec_events, start_index=0)
            if finished:
                self.log(f"✅ {desc} completed successfully!")
            else:
                self.log(f"⏹ {desc} was interrupted.")
        except Exception as e:
            self.log(f"❌ Error executing {desc}: {e}")

        self._last_death_incident_time = time.perf_counter()
        time.sleep(1.5)

    def stop_bot_loop(self):
        if self._bot_thread and self._bot_thread.is_alive():
            self.log("⏹ Stopping automatic bot...")
            self._stop_bot_event.set()
            self.replayer.stop()
            self.paused_run_index = 0
            self._play_sound("stop")
            try:
                self._bot_thread.join(timeout=1.0)
            except Exception:
                pass
            self._set_state(BotState.IDLE, "Bot stopped.")

    def emergency_stop(self):
        """Emergency stop for ANY active operation."""
        self.log("🛑 EMERGENCY STOP TRIGGERED!")
        self._stop_bot_event.set()
        self.replayer.stop()
        self.paused_run_index = 0
        self.paused_step_index = 0
        self.recording_segment_target = None
        if self.state == BotState.RECORDING:
            self.recorder.stop()
        self._play_sound("stop")
        self._set_state(BotState.IDLE, "Stopped via emergency key.")
