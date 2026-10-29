import os
import json
import re
import time

CONFIG_FILE = "config.json"
RUNS_DIR = "runs"
DEFAULT_REVIVE_RUN_FILE = "revive_run.json"
DEFAULT_RECONNECT_RUN_FILE = "reconnect_run.json"
DEFAULT_SERVER_RECONNECT_RUN_FILE = "server_reconnect_run.json"
DEFAULT_LOBBY_RUN_FILE = "lobby_run.json"
DEFAULT_EXIT_RUN_FILE = "exit_run.json"

DEFAULT_HOTKEYS = {
    "record_active": "f7",       # Start / Stop recording for active tab
    "bot_toggle": "f8",          # Start / Pause bot loop
    "emergency_stop": "f9",      # Emergency stop
    "puzzle_record_step": "f1",  # In-game Puzzle: Record movement step (Start/Stop)
    "puzzle_automat_step": "f2", # In-game Puzzle: Add & immediately run 🤖 AUTO-MOB step
    "record_main": "f7",         # Direct record: Main combat run
    "record_revive": "",         # Direct record: Revive run (optional)
    "record_reconnect": "",      # Direct record: Reconnect run (optional)
    "record_server_reconnect": "", # Direct record: Server Reconnect run (optional)
    "record_lobby": "",          # Direct record: Lobby run (optional)
    "record_exit": ""            # Direct record: Exit run (optional)
}

DEFAULT_CONFIG = {
    # Active combat run profile name (saved in runs/<name>.json)
    "selected_combat_run": "predvoleny_run",

    # Recovery run files
    "revive_run_file": DEFAULT_REVIVE_RUN_FILE,
    "reconnect_run_file": DEFAULT_RECONNECT_RUN_FILE,
    "server_reconnect_run_file": DEFAULT_SERVER_RECONNECT_RUN_FILE,
    "lobby_run_file": DEFAULT_LOBBY_RUN_FILE,
    "exit_run_file": DEFAULT_EXIT_RUN_FILE,

    # Timing
    "wait_between_runs": 0.0,   # Čas čakania medzi runmi (vypnuté na požiadanie)
    "start_delay": 3.0,         # Oneskorenie pred 1. runom

    # Recovery options
    "enable_death_recovery": True,
    "enable_disconnect_recovery": True,
    "enable_server_reconnect_recovery": True,
    "enable_lobby_recovery": True,
    "enable_dungeon_complete_recovery": True,
    "death_threshold": 0.75,
    "disconnect_threshold": 0.75,
    "server_reconnect_threshold": 0.75,
    "lobby_threshold": 0.75,
    "dungeon_complete_threshold": 0.75,
    "death_rewind_seconds": 3.0,        # Vrátenie bojového runu dozadu po oživení v sekundách
    "disconnect_rewind_seconds": 3.0,   # Vrátenie bojového runu dozadu po výpadku v sekundách
    "server_reconnect_rewind_seconds": 3.0, # Vrátenie bojového runu dozadu po výpadku servera
    "lobby_rewind_seconds": 0.0,        # Posun pri návrate z lobby

    # Auto-Heal (Liečenie / Auto Potion)
    "enable_auto_heal": True,           # Automatické liečenie pri nízkom HP
    "heal_key": "2",                    # Kláves pre heal skill (predvolene 2)
    "heal_hp_threshold": 40.0,          # Aktivovať liečenie ak HP klesne pod X %
    "heal_cooldown_seconds": 2.0,       # Minimálny odstup medzi stlačeniami liečenia v sekundách
    "heal_save_mana_enabled": True,     # Šetriť manu na Heal (Skill 2) a nemíňať na Skill 1 (a 3), keď HP klesne pod limit
    "heal_save_mana_hp_threshold": 50.0, # Pod koľko % života šetriť manu na Heal (predvolene 50 %)

    # Constant Attack (Neustále útočenie / Držanie ľavého tlačidla na postave)
    "enable_constant_attack": True,     # Neustále mierenie na postavu a držanie ľavého tlačidla počas bojového runu
    "constant_attack_delay": 5.0,       # Počet sekúnd od začiatku bojového runu, kedy sa neútočí (predvolene 5.0 s)
    "constant_attack_x": 960,           # X súradnica postavy v strede obrazovky
    "constant_attack_y": 575,           # Y súradnica postavy v strede obrazovky

    # Automat (Autonómne vyhľadávanie mobov cez HP bar, pohyb D/A a skilly 1, 3, 4, 5)
    "automat_use_on_f8": False,         # Ak je zapnuté, F8 priamo spúšťa režim Automat namiesto nahraného runu
    "enable_automat_assist": False,     # Spolupráca nahraného runu s Automatom (keď zbadá mobov, preruší run, zabije ich a pokračuje)
    "automat_move_key": "d",            # Smer postupu: 'd' (doprava) alebo 'a' (doľava)
    "automat_combat_linger_seconds": 3.0, # Dojazd boja po zmiznutí mobov pred ďalším postupom [s]
    "automat_jump_interval": 10.0,      # Interval vyskočenia (W) počas postupu vpred [s] (0 = vypnuté)
    "automat_aoe_mob_threshold": 3,     # Od koľkých mobov používať plošný Skill 3 (pri menej moboch spamuje Skill 1)
    "automat_aoe_memory_seconds": 20.0, # Ako dlho si pamätať zistenú skupinku mobov a šetriť manu na Skill 3 [s]
    "automat_shoot_angle": 0.0,         # Stredový uhol streľby pri behu dopredu v stupňoch (+ nahor, - nadol, 0 = rovno)
    "automat_shoot_spread": 12.0,       # Rozptyl (kývanie) uhla streľby pri behu dopredu v stupňoch (0 = bez kývania)
    "automat_skill_cooldown": 0.55,     # Minimálny odstup medzi stláčaním bojových skillov [s]
    "automat_skill_5_min_interval": 15.0, # Minimálny odstup medzi aktiváciami Skillu 5 (štítu), aby sa nevypol 2. stlačením [s]
    "automat_skill_1_key": "1",
    "automat_skill_3_key": "3",
    "automat_skill_4_key": "4",
    "automat_skill_5_key": "5",

    # Input & Audio
    "record_mouse_move": True,
    "sound_enabled": True,

    # Keybindings dictionary
    "hotkeys": DEFAULT_HOTKEYS.copy()
}

def sanitize_filename(name: str) -> str:
    """Replaces invalid characters with underscores."""
    s = re.sub(r'[\\/*?:"<>| ]', '_', name.strip())
    return s if s else "run"

def get_combat_run_path(run_name: str) -> str:
    """Returns absolute or relative path to runs/<name>.json."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    clean_name = sanitize_filename(run_name.replace(".json", ""))
    return os.path.join(RUNS_DIR, f"{clean_name}.json")

def list_combat_runs() -> list:
    """Lists all available combat run names in runs/."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    files = [f[:-5] for f in os.listdir(RUNS_DIR) if f.lower().endswith(".json")]
    if not files:
        # Create initial default run
        def_path = os.path.join(RUNS_DIR, "default_run.json")
        if not os.path.exists(def_path):
            with open(def_path, "w", encoding="utf-8") as f:
                json.dump({"name": "default_run", "created_at": "", "events": []}, f)
        files = ["default_run"]
    return sorted(files)

def create_combat_run(run_name: str) -> str:
    """Creates a new empty combat run in runs/."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    clean_name = sanitize_filename(run_name.replace(".json", ""))
    path = os.path.join(RUNS_DIR, f"{clean_name}.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "name": clean_name,
                "version": 1,
                "created_at": "",
                "duration": 0.0,
                "event_count": 0,
                "events": []
            }, f, indent=2)
    return clean_name

def delete_combat_run(run_name: str) -> bool:
    """Deletes a combat run file from runs/."""
    path = get_combat_run_path(run_name)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False

# --- PUZZLE / SEGMENTED COMBAT RUN MANAGEMENT ---
def load_combat_run_data(run_name_or_path: str) -> dict:
    """Loads a combat run file and guarantees consistent structure with segment support."""
    if os.path.exists(run_name_or_path):
        filepath = run_name_or_path
    else:
        filepath = get_combat_run_path(run_name_or_path)

    if not os.path.exists(filepath):
        return {
            "name": os.path.basename(filepath).replace(".json", ""),
            "version": 2,
            "created_at": "",
            "duration": 0.0,
            "event_count": 0,
            "events": [],
            "is_segmented": False,
            "segments": []
        }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("name", os.path.basename(filepath).replace(".json", ""))
    data.setdefault("version", 2)
    data.setdefault("created_at", "")
    data.setdefault("events", [])
    data.setdefault("is_segmented", False)
    data.setdefault("segments", [])
    data["event_count"] = len(data.get("events", []))

    # Ensure any segment or flat run with an orphaned initial mouse_up has mouse_down at t=0.0
    if data["events"]:
        data["events"] = _ensure_initial_held_mouse_down([], data["events"])
        data["event_count"] = len(data["events"])
        data["duration"] = round(data["events"][-1].get("time", 0.0), 3)
    else:
        data.setdefault("duration", 0.0)

    for seg in data.get("segments", []):
        seg.setdefault("type", "recorded")
        if seg.get("type") == "automat":
            seg["events"] = []
            seg["event_count"] = 0
            seg["duration"] = 0.0
            continue
        seg_evts = seg.get("events", [])
        if seg_evts:
            fixed_evts = _ensure_initial_held_mouse_down([], seg_evts)
            seg["events"] = fixed_evts
            seg["event_count"] = len(fixed_evts)
            seg["duration"] = round(fixed_evts[-1].get("time", 0.0), 3)

    return data

def save_combat_run_data(run_name_or_path: str, data: dict):
    """Saves combat run data to JSON."""
    if os.path.exists(run_name_or_path) or run_name_or_path.endswith(".json"):
        filepath = run_name_or_path
    else:
        filepath = get_combat_run_path(run_name_or_path)

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _ensure_initial_held_mouse_down(prior_events: list, norm_chunk: list) -> list:
    """
    Checks if any mouse button was held down prior to the slice cut (in prior_events)
    or if the first button event in norm_chunk is a 'mouse_up' without a preceding 'mouse_down'.
    If so, injects a 'mouse_down' event at time=0.0 at the start of norm_chunk.
    """
    if not norm_chunk:
        return norm_chunk

    held_state = {}
    last_pos = {}
    for ev in prior_events:
        if "x" in ev and "y" in ev:
            last_pos["x"] = ev["x"]
            last_pos["y"] = ev["y"]
        et = ev.get("type")
        if et in ("mouse_down", "mouse_up"):
            btn = ev.get("button", "left").lower().strip()
            held_state[btn] = (et == "mouse_down")

    # Also detect orphan mouse_up at the start of norm_chunk
    seen_in_chunk = set()
    for ev in norm_chunk:
        et = ev.get("type")
        if et in ("mouse_down", "mouse_up"):
            btn = ev.get("button", "left").lower().strip()
            if btn not in seen_in_chunk:
                seen_in_chunk.add(btn)
                if et == "mouse_up":
                    held_state[btn] = True

    first_x = norm_chunk[0].get("x", last_pos.get("x", 960))
    first_y = norm_chunk[0].get("y", last_pos.get("y", 575))
    for ev in norm_chunk:
        if "x" in ev and "y" in ev:
            first_x = ev["x"]
            first_y = ev["y"]
            break

    injected = []
    for btn, is_held in held_state.items():
        if is_held:
            already_has = any(
                e.get("time", 0.0) == 0.0 and e.get("type") == "mouse_down" and e.get("button", "left").lower().strip() == btn
                for e in norm_chunk[:5]
            )
            if not already_has:
                injected.append({
                    "type": "mouse_down",
                    "button": btn,
                    "x": int(first_x),
                    "y": int(first_y),
                    "time": 0.0
                })

    return injected + norm_chunk

def add_segment_to_run(run_name: str, segment_name: str, events: list) -> dict:
    """Appends a new puzzle segment to the combat run."""
    data = load_combat_run_data(run_name)
    data["is_segmented"] = True

    # Normalize events to start at 0.0
    norm_events = []
    base_time = events[0].get("time", 0.0) if events else 0.0
    for evt in events:
        cp = evt.copy()
        cp["time"] = max(0.0, round(cp.get("time", 0.0) - base_time, 4))
        norm_events.append(cp)

    norm_events = _ensure_initial_held_mouse_down([], norm_events)
    duration = norm_events[-1]["time"] if norm_events else 0.0
    seg_id = f"seg_{int(time.time() * 1000)}"

    new_segment = {
        "id": seg_id,
        "type": "recorded",
        "name": segment_name.strip() if segment_name else f"Step {len(data['segments']) + 1}",
        "duration": round(duration, 3),
        "event_count": len(norm_events),
        "events": norm_events
    }
    data["segments"].append(new_segment)
    save_combat_run_data(run_name, data)
    return data

def add_automat_segment_to_run(run_name: str, segment_name: str = "") -> dict:
    """Appends an autonomous room-clearing '🤖 AUTOMAT' step to the combat run's Puzzle."""
    data = load_combat_run_data(run_name)
    if not data.get("is_segmented") and not data.get("segments") and data.get("events"):
        data = convert_flat_run_to_puzzle(run_name, step_name="Step 1 (Base)")
    data["is_segmented"] = True

    step_num = len(data["segments"]) + 1
    seg_id = f"seg_auto_{int(time.time() * 1000)}"
    new_segment = {
        "id": seg_id,
        "type": "automat",
        "name": segment_name.strip() if segment_name else f"🤖 AUTO-MOB (Step {step_num})",
        "duration": 0.0,
        "event_count": 0,
        "events": []
    }
    data["segments"].append(new_segment)
    save_combat_run_data(run_name, data)
    return data

def trim_segment_in_run(run_name: str, index: int, start_sec: float, end_sec: float = None) -> dict:
    """Trims a specific puzzle segment between start_sec and end_sec while preserving held mouse buttons."""
    data = load_combat_run_data(run_name)
    if 0 <= index < len(data.get("segments", [])):
        seg = data["segments"][index]
        seg_events = seg.get("events", [])
        t_start = max(0.0, float(start_sec))
        t_end = float(end_sec) if (end_sec is not None and float(end_sec) > t_start) else float("inf")

        prior_events = [e for e in seg_events if e.get("time", 0.0) < t_start]
        chunk = [e for e in seg_events if (e.get("time", 0.0) >= t_start and (t_end == float("inf") or e.get("time", 0.0) <= t_end))]
        if chunk:
            norm_chunk = []
            base = chunk[0].get("time", 0.0)
            for evt in chunk:
                cp = evt.copy()
                cp["time"] = max(0.0, round(cp.get("time", 0.0) - base, 4))
                norm_chunk.append(cp)
            norm_chunk = _ensure_initial_held_mouse_down(prior_events, norm_chunk)
            seg["events"] = norm_chunk
            seg["event_count"] = len(norm_chunk)
            seg["duration"] = round(norm_chunk[-1]["time"], 3) if norm_chunk else 0.0
            save_combat_run_data(run_name, data)
    return data

def update_segment_in_run(run_name: str, index: int, new_events: list = None, new_name: str = None) -> dict:
    """Updates an existing segment's events or name."""
    data = load_combat_run_data(run_name)
    if 0 <= index < len(data["segments"]):
        seg = data["segments"][index]
        if new_name is not None and new_name.strip():
            seg["name"] = new_name.strip()
        if new_events is not None:
            norm_events = []
            base_time = new_events[0].get("time", 0.0) if new_events else 0.0
            for evt in new_events:
                cp = evt.copy()
                cp["time"] = max(0.0, round(cp.get("time", 0.0) - base_time, 4))
                norm_events.append(cp)
            norm_events = _ensure_initial_held_mouse_down([], norm_events)
            seg["events"] = norm_events
            seg["event_count"] = len(norm_events)
            seg["duration"] = round(norm_events[-1]["time"], 3) if norm_events else 0.0

        save_combat_run_data(run_name, data)
    return data

def delete_segment_from_run(run_name: str, index: int) -> dict:
    """Deletes a segment at index."""
    data = load_combat_run_data(run_name)
    if 0 <= index < len(data["segments"]):
        data["segments"].pop(index)
        if not data["segments"]:
            data["is_segmented"] = False
        save_combat_run_data(run_name, data)
    return data

def move_segment_in_run(run_name: str, index: int, direction: int) -> dict:
    """Moves a segment up (-1) or down (+1)."""
    data = load_combat_run_data(run_name)
    target = index + direction
    if 0 <= index < len(data["segments"]) and 0 <= target < len(data["segments"]):
        data["segments"][index], data["segments"][target] = data["segments"][target], data["segments"][index]
        save_combat_run_data(run_name, data)
    return data

def reorder_segment_in_run(run_name: str, from_index: int, to_index: int) -> dict:
    """Moves a segment from from_index to to_index (for drag-and-drop reordering)."""
    data = load_combat_run_data(run_name)
    segs = data.get("segments", [])
    if 0 <= from_index < len(segs) and 0 <= to_index < len(segs) and from_index != to_index:
        item = segs.pop(from_index)
        segs.insert(to_index, item)
        save_combat_run_data(run_name, data)
    return data

def find_rewind_index(events: list, current_index: int, rewind_seconds: float) -> int:
    """
    Finds the event index to rewind back by rewind_seconds from current_index.
    Ensures safe boundary checking and returns integer index >= 0.
    """
    if not events:
        return 0
    if current_index <= 0 or rewind_seconds <= 0:
        return max(0, min(current_index, len(events) - 1))

    cur_idx = min(current_index, len(events) - 1)
    t_interrupt = events[cur_idx].get("time", 0.0)
    target_time = max(0.0, t_interrupt - float(rewind_seconds))

    rewound_idx = 0
    for i in range(cur_idx, -1, -1):
        if events[i].get("time", 0.0) <= target_time:
            rewound_idx = i
            break

    return rewound_idx

def split_run_into_segments(run_name: str, split_seconds: list) -> dict:
    """Splits a continuous run into multiple segments based on timestamp seconds."""
    data = load_combat_run_data(run_name)
    all_events = data.get("events", [])
    if not all_events and data.get("segments"):
        # If already segmented, gather all events to allow re-splitting
        cumulative = 0.0
        for s in data["segments"]:
            for evt in s.get("events", []):
                cp = evt.copy()
                cp["time"] = round(cumulative + cp.get("time", 0.0), 4)
                all_events.append(cp)
            cumulative += s.get("duration", 0.0)

    if not all_events:
        return data

    splits = sorted(list(set([float(s) for s in split_seconds if float(s) > 0])))
    if not splits:
        return data

    boundaries = [0.0] + splits + [float("inf")]
    new_segments = []

    for i in range(len(boundaries) - 1):
        t_start = boundaries[i]
        t_end = boundaries[i + 1]

        prior_events = [e for e in all_events if e.get("time", 0.0) < t_start]
        chunk = [e for e in all_events if (e.get("time", 0.0) >= t_start and (t_end == float("inf") or e.get("time", 0.0) < t_end))]
        if chunk:
            norm_chunk = []
            base = chunk[0].get("time", 0.0)
            for evt in chunk:
                cp = evt.copy()
                cp["time"] = max(0.0, round(cp.get("time", 0.0) - base, 4))
                norm_chunk.append(cp)

            norm_chunk = _ensure_initial_held_mouse_down(prior_events, norm_chunk)

            duration = norm_chunk[-1]["time"] if norm_chunk else 0.0
            range_desc = f"{int(t_start)}s - {int(t_end)}s" if t_end != float("inf") else f"od {int(t_start)}s"
            new_segments.append({
                "id": f"seg_{int(time.time() * 1000)}_{i}",
                "name": f"Step {i + 1} ({range_desc})",
                "duration": round(duration, 3),
                "event_count": len(norm_chunk),
                "events": norm_chunk
            })

    if new_segments:
        data["is_segmented"] = True
        data["segments"] = new_segments
        save_combat_run_data(run_name, data)

    return data

def convert_flat_run_to_puzzle(run_name: str, step_name: str = "Step 1 (Base)") -> dict:
    """Converts a flat linear run into a 1-segment puzzle run so user can append/edit steps."""
    data = load_combat_run_data(run_name)
    all_events = data.get("events", [])
    if all_events:
        norm_events = []
        base = all_events[0].get("time", 0.0)
        for evt in all_events:
            cp = evt.copy()
            cp["time"] = max(0.0, round(cp.get("time", 0.0) - base, 4))
            norm_events.append(cp)

        duration = norm_events[-1]["time"] if norm_events else data.get("duration", 0.0)
        data["is_segmented"] = True
        data["segments"] = [{
            "id": f"seg_{int(time.time() * 1000)}",
            "name": step_name.strip() if step_name else "Step 1",
            "duration": round(duration, 3),
            "event_count": len(norm_events),
            "events": norm_events
        }]
        save_combat_run_data(run_name, data)
    return data

def merge_segments_to_single_run(run_name: str) -> dict:
    """Merges all segments into a single linear event list."""
    data = load_combat_run_data(run_name)
    segments = data.get("segments", [])
    if not segments:
        data["is_segmented"] = False
        save_combat_run_data(run_name, data)
        return data

    merged_events = []
    cumulative_time = 0.0

    for seg in segments:
        seg_events = seg.get("events", [])
        if not seg_events:
            continue
        for evt in seg_events:
            cp = evt.copy()
            cp["time"] = round(cumulative_time + cp.get("time", 0.0), 4)
            merged_events.append(cp)
        cumulative_time += seg.get("duration", 0.0)

    data["events"] = merged_events
    data["event_count"] = len(merged_events)
    data["duration"] = round(cumulative_time, 3)
    data["is_segmented"] = False
    save_combat_run_data(run_name, data)
    return data

def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"Chyba pri načítavaní {CONFIG_FILE}: {e}")

    # Ensure hotkeys dict exists and is complete
    if "hotkeys" not in config or not isinstance(config["hotkeys"], dict):
        config["hotkeys"] = DEFAULT_HOTKEYS.copy()
    else:
        # Backwards compatibility check
        merged_hotkeys = DEFAULT_HOTKEYS.copy()
        if "hotkey_record" in config and config["hotkey_record"]:
            merged_hotkeys["record_active"] = config["hotkey_record"]
        if "hotkey_bot" in config and config["hotkey_bot"]:
            merged_hotkeys["bot_toggle"] = config["hotkey_bot"]
        if "hotkey_stop" in config and config["hotkey_stop"]:
            merged_hotkeys["emergency_stop"] = config["hotkey_stop"]

        merged_hotkeys.update(config["hotkeys"])
        config["hotkeys"] = merged_hotkeys

    # Ensure selected combat run exists
    available = list_combat_runs()
    if config["selected_combat_run"] not in available:
        config["selected_combat_run"] = available[0]

    return config

def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Chyba pri ukladaní {CONFIG_FILE}: {e}")
