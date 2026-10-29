import time
import json
import os
import threading
import ctypes
import ctypes.wintypes
from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode

user32 = ctypes.windll.user32

class InputRecorder:
    def __init__(self):
        self.is_recording = False
        self.events = []
        self.start_time = 0.0
        self.record_mouse_move = True
        
        self._last_move_time = 0.0
        self._last_x = None
        self._last_y = None
        
        self._kb_listener = None
        self._mouse_listener = None
        self._lock = threading.Lock()

    def _normalize_key(self, key) -> str:
        if isinstance(key, KeyCode):
            if key.char is not None and key.char != "":
                return key.char.lower()
            if key.vk is not None:
                # Numpad mapping
                if 96 <= key.vk <= 105:
                    return str(key.vk - 96)
                return f"vk_{key.vk}"
            return str(key)
        
        if isinstance(key, Key):
            name = key.name.lower()
            if name.startswith("shift"):
                return "shift"
            if name.startswith("ctrl"):
                return "ctrl"
            if name.startswith("alt"):
                return "alt"
            return name
        
        return str(key).lower()

    def _add_event(self, event_data: dict):
        if not self.is_recording:
            return
        t = round(time.perf_counter() - self.start_time, 4)
        event_data["time"] = max(0.0, t)
        with self._lock:
            self.events.append(event_data)

    def _on_key_press(self, key):
        k_str = self._normalize_key(key)
        self._add_event({"type": "key_down", "key": k_str})

    def _on_key_release(self, key):
        k_str = self._normalize_key(key)
        self._add_event({"type": "key_up", "key": k_str})

    def _on_mouse_move(self, x, y):
        if not self.record_mouse_move:
            return
        now = time.perf_counter()
        # Throttle mouse movement to ~60 FPS (approx 16ms) and require at least 2 pixels distance
        if now - self._last_move_time < 0.016:
            return
        if self._last_x is not None and self._last_y is not None:
            if abs(x - self._last_x) < 2 and abs(y - self._last_y) < 2:
                return
        
        self._last_move_time = now
        self._last_x = int(x)
        self._last_y = int(y)
        self._add_event({"type": "mouse_move", "x": int(x), "y": int(y)})

    def _on_mouse_click(self, x, y, button, pressed):
        b_name = getattr(button, "name", "left")
        evt_type = "mouse_down" if pressed else "mouse_up"
        self._add_event({"type": evt_type, "button": b_name, "x": int(x), "y": int(y)})

    def _on_mouse_scroll(self, x, y, dx, dy):
        self._add_event({"type": "mouse_scroll", "dx": int(dx), "dy": int(dy), "x": int(x), "y": int(y)})

    def start(self, record_mouse_move: bool = True):
        # Fetch current cursor position at start
        cur_x, cur_y = 0, 0
        try:
            pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cur_x = int(pt.x)
            cur_y = int(pt.y)
        except Exception:
            pass

        with self._lock:
            self.events = []
            self.record_mouse_move = record_mouse_move
            self.start_time = time.perf_counter()
            self._last_move_time = self.start_time
            self._last_x = cur_x
            self._last_y = cur_y
            self.is_recording = True

            # If user is already holding left or right mouse button when recording starts, capture it immediately at t=0.0
            try:
                VK_LBUTTON = 0x01
                VK_RBUTTON = 0x02
                if user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                    self.events.append({"type": "mouse_down", "button": "left", "x": cur_x, "y": cur_y, "time": 0.0})
                if user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000:
                    self.events.append({"type": "mouse_down", "button": "right", "x": cur_x, "y": cur_y, "time": 0.0})
            except Exception:
                pass

        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )

        self._kb_listener.start()
        self._mouse_listener.start()

    def stop(self, stop_hotkey: str = None) -> list:
        if not self.is_recording:
            return self.events

        self.is_recording = False
        
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

        with self._lock:
            # Filter out trailing stop_hotkey events so pressing e.g. F7 to stop doesn't get recorded
            if stop_hotkey and self.events:
                normalized_stop = stop_hotkey.lower()
                filtered = []
                for evt in self.events:
                    if evt.get("type") in ("key_down", "key_up") and evt.get("key") == normalized_stop:
                        continue
                    filtered.append(evt)
                self.events = filtered
                
            return list(self.events)

    def save_run(self, filepath: str) -> dict:
        with self._lock:
            events_to_save = list(self.events)

        duration = events_to_save[-1]["time"] if events_to_save else 0.0
        data = {
            "version": 1,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": round(duration, 3),
            "event_count": len(events_to_save),
            "events": events_to_save
        }

        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return {
            "duration": round(duration, 3),
            "event_count": len(events_to_save),
            "file": filepath
        }
