import time
import json
import os
import threading
import ctypes
import ctypes.wintypes
import pydirectinput
from pynput.keyboard import Controller as KeyboardController, KeyCode, Key

# Configure pydirectinput
pydirectinput.PAUSE = 0.0
pydirectinput.FAILSAFE = False

# Windows user32 constants
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
VK_ESCAPE = 0x1B

user32 = ctypes.windll.user32

def is_hardware_esc_pressed() -> bool:
    """Directly queries OS kernel hardware key state for ESC (immune to hook lag)."""
    try:
        return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
    except Exception:
        return False

class InputReplayer:
    def __init__(self):
        self.is_playing = False
        self.stop_event = threading.Event()
        self.currently_pressed_keys = set()
        self.currently_pressed_mouse = set()
        self._fallback_kb = KeyboardController()
        self.last_played_index = 0

    def load_run(self, filepath: str) -> list:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Run file '{filepath}' does not exist.")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("events", [])

    def _execute_mouse_move(self, x: int, y: int):
        user32.SetCursorPos(int(x), int(y))
        if self.currently_pressed_mouse:
            user32.mouse_event(0x0001, 0, 0, 0, 0)  # MOUSEEVENTF_MOVE to update drag/aim in game engine

    def _execute_mouse_button(self, button: str, is_down: bool, x: int = None, y: int = None):
        btn = button.lower().strip() if button else "left"
        if btn not in ("left", "right", "middle"):
            btn = "left"

        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))

        if btn == "left":
            flags = MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP
        elif btn == "right":
            flags = MOUSEEVENTF_RIGHTDOWN if is_down else MOUSEEVENTF_RIGHTUP
        elif btn == "middle":
            flags = MOUSEEVENTF_MIDDLEDOWN if is_down else MOUSEEVENTF_MIDDLEUP
        else:
            flags = MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP

        # Windows user32.mouse_event (universal native injection, never blocked by UIPI)
        user32.mouse_event(flags, 0, 0, 0, 0)

        if is_down:
            self.currently_pressed_mouse.add(btn)
        else:
            self.currently_pressed_mouse.discard(btn)

    def _execute_mouse_scroll(self, dx: int, dy: int, x: int = None, y: int = None):
        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
        wheel_delta = int(dy * 120)
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)

    def _execute_key(self, key_str: str, is_down: bool):
        k = key_str.lower().strip()
        sk_top_row = {
            "+": "1", "ľ": "2", "š": "3", "č": "4", "ť": "5",
            "ž": "6", "ý": "7", "á": "8", "í": "9", "é": "0"
        }
        if k in sk_top_row:
            k = sk_top_row[k]
        
        # Check if pydirectinput supports this key directly
        if k in pydirectinput.KEYBOARD_MAPPING:
            try:
                if is_down:
                    pydirectinput.keyDown(k)
                    self.currently_pressed_keys.add(k)
                else:
                    pydirectinput.keyUp(k)
                    self.currently_pressed_keys.discard(k)
                return
            except Exception:
                pass

        # Handle numeric vk_ codes
        if k.startswith("vk_"):
            try:
                vk_code = int(k.replace("vk_", ""))
                char_candidate = chr(vk_code).lower()
                if char_candidate in pydirectinput.KEYBOARD_MAPPING:
                    if is_down:
                        pydirectinput.keyDown(char_candidate)
                        self.currently_pressed_keys.add(char_candidate)
                    else:
                        pydirectinput.keyUp(char_candidate)
                        self.currently_pressed_keys.discard(char_candidate)
                    return
            except Exception:
                pass

        # Fallback to pynput keyboard controller
        try:
            if hasattr(Key, k):
                target_key = getattr(Key, k)
            else:
                target_key = KeyCode.from_char(k)
            
            if is_down:
                self._fallback_kb.press(target_key)
                self.currently_pressed_keys.add(k)
            else:
                self._fallback_kb.release(target_key)
                self.currently_pressed_keys.discard(k)
        except Exception:
            pass

    def release_all_inputs(self):
        """Emergency release for all held keys and mouse buttons."""
        # 1. Unconditionally force release mouse buttons via mouse_event (never stuck across cycles)
        for flags in (MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_MIDDLEUP):
            user32.mouse_event(flags, 0, 0, 0, 0)

        for btn in ("left", "right", "middle"):
            try:
                pydirectinput.mouseUp(button=btn)
            except Exception:
                pass
        self.currently_pressed_mouse.clear()

        # 2. Release all pressed keyboard keys
        for k in list(self.currently_pressed_keys):
            try:
                if k in pydirectinput.KEYBOARD_MAPPING:
                    pydirectinput.keyUp(k)
                elif hasattr(Key, k):
                    self._fallback_kb.release(getattr(Key, k))
                else:
                    self._fallback_kb.release(KeyCode.from_char(k))
            except Exception:
                pass
        self.currently_pressed_keys.clear()

    def play(
        self,
        events: list,
        start_index: int = 0,
        speed: float = 1.0,
        callback=None,
        is_combat_run: bool = False,
        cycle_elapsed_offset: float = 0.0,
        config_dict: dict = None
    ) -> tuple:
        """
        Replays recorded events with high precision timing, starting from start_index.
        Supports Constant Attack mode during combat runs (after configurable delay).
        Returns: (completed: bool, next_index_to_play: int)
        """
        if not events:
            return (True, 0)
        
        if start_index >= len(events):
            return (True, len(events))

        self.is_playing = True
        self.stop_event.clear()

        # Position cursor at first target event
        first_x, first_y = None, None
        for ev in events[start_index:]:
            if "x" in ev and "y" in ev:
                first_x = ev["x"]
                first_y = ev["y"]
                break

        if first_x is not None and first_y is not None:
            user32.SetCursorPos(int(first_x), int(first_y))
            time.sleep(0.02)

        # Restore held mouse buttons & movement keys when resuming from start_index (after Revive / Reconnect / Lobby)
        # or when a sliced segment begins while a button was already held down
        held_mouse_buttons = {}
        held_movement_keys = {}
        seen_in_prefix = set()
        for ev in events[:start_index]:
            et = ev.get("type")
            if et in ("mouse_down", "mouse_up"):
                btn = ev.get("button", "left").lower().strip()
                seen_in_prefix.add(btn)
                held_mouse_buttons[btn] = (et == "mouse_down")
            elif et in ("key_down", "key_up"):
                k = ev.get("key", "").lower().strip()
                if k in ("w", "a", "s", "d", "up", "down", "left", "right"):
                    held_movement_keys[k] = (et == "key_down")

        # Also check if the very first button event from start_index onward is mouse_up
        seen_in_suffix = set()
        for ev in events[start_index:]:
            et = ev.get("type")
            if et in ("mouse_down", "mouse_up"):
                btn = ev.get("button", "left").lower().strip()
                if btn not in seen_in_suffix:
                    seen_in_suffix.add(btn)
                    if et == "mouse_up" and btn not in seen_in_prefix:
                        held_mouse_buttons[btn] = True

        for btn, is_held in held_mouse_buttons.items():
            if is_held:
                self._execute_mouse_button(btn, is_down=True, x=first_x, y=first_y)

        for k, is_held in held_movement_keys.items():
            if is_held:
                self._execute_key(k, is_down=True)

        # Base time offset for accurate relative playback when resuming
        base_offset = events[start_index].get("time", 0.0)
        start_time = time.perf_counter()
        completed = True
        next_index = start_index

        ca_active = False
        last_ca_refresh = -1.0

        def _update_constant_attack(now_sec: float) -> bool:
            nonlocal ca_active, last_ca_refresh
            if not is_combat_run or config_dict is None:
                return False

            enabled = bool(config_dict.get("enable_constant_attack", True))
            delay_sec = max(0.0, float(config_dict.get("constant_attack_delay", 5.0)))
            total_cycle_sec = cycle_elapsed_offset + now_sec

            if enabled and total_cycle_sec >= delay_sec:
                ca_x = int(config_dict.get("constant_attack_x", 960))
                ca_y = int(config_dict.get("constant_attack_y", 575))
                if not ca_active:
                    user32.SetCursorPos(ca_x, ca_y)
                    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    user32.mouse_event(0x0001, 0, 0, 0, 0)
                    self.currently_pressed_mouse.add("left")
                    ca_active = True
                    last_ca_refresh = now_sec
                elif (now_sec - last_ca_refresh) >= 0.15:
                    user32.SetCursorPos(ca_x, ca_y)
                    if "left" not in self.currently_pressed_mouse:
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        self.currently_pressed_mouse.add("left")
                    user32.mouse_event(0x0001, 0, 0, 0, 0)
                    last_ca_refresh = now_sec
                return True
            else:
                if ca_active:
                    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                    self.currently_pressed_mouse.discard("left")
                    ca_active = False
                return False

        try:
            for idx in range(start_index, len(events)):
                if self.stop_event.is_set() or is_hardware_esc_pressed():
                    self.stop_event.set()
                    next_index = idx
                    completed = False
                    break

                event = events[idx]
                target_time = (event.get("time", 0.0) - base_offset) / speed
                
                # Precision waiting
                while True:
                    if self.stop_event.is_set() or is_hardware_esc_pressed():
                        self.stop_event.set()
                        next_index = idx
                        completed = False
                        break
                    now = time.perf_counter() - start_time
                    _update_constant_attack(now)
                    remaining = target_time - now
                    if remaining <= 0:
                        break
                    if remaining > 0.003:
                        sleep_chunk = min(remaining - 0.002, 0.025)
                        if self.stop_event.wait(sleep_chunk):
                            next_index = idx
                            completed = False
                            break
                    else:
                        pass # Spin wait for the last 1-2 ms for microsecond accuracy

                if self.stop_event.is_set() or is_hardware_esc_pressed():
                    self.stop_event.set()
                    next_index = idx
                    completed = False
                    break

                now = time.perf_counter() - start_time
                holding_ca = _update_constant_attack(now)

                # Dispatch event
                evt_type = event.get("type")
                if evt_type in ("mouse_move", "mouse_down", "mouse_up"):
                    if holding_ca:
                        # Keep cursor on character and left button held down during Constant Attack
                        pass
                    elif evt_type == "mouse_move":
                        self._execute_mouse_move(event["x"], event["y"])
                    elif evt_type == "mouse_down":
                        self._execute_mouse_button(event["button"], is_down=True, x=event.get("x"), y=event.get("y"))
                    elif evt_type == "mouse_up":
                        self._execute_mouse_button(event["button"], is_down=False, x=event.get("x"), y=event.get("y"))
                elif evt_type == "mouse_scroll":
                    self._execute_mouse_scroll(event.get("dx", 0), event.get("dy", 0), x=event.get("x"), y=event.get("y"))
                elif evt_type == "key_down":
                    self._execute_key(event["key"], is_down=True)
                elif evt_type == "key_up":
                    self._execute_key(event["key"], is_down=False)

                next_index = idx + 1

            if not self.stop_event.is_set() and next_index >= len(events):
                completed = True

        finally:
            self.release_all_inputs()
            self.is_playing = False
            self.last_played_index = next_index

        return (completed, next_index)

    def stop(self):
        """Signals the replayer to stop immediately."""
        self.stop_event.set()
        self.release_all_inputs()
