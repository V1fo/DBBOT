# ⚔️ Dungeon Blitz - Autonomous Bot & Modular Puzzle Replayer

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![UI CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-2563EB.svg)](https://github.com/TomSchimansky/CustomTkinter)
[![Computer Vision OpenCV](https://img.shields.io/badge/Vision-OpenCV%20%2B%20MSS-5C5C2F.svg)](https://opencv.org/)

An advanced, computer-vision driven automation suite and modular macro framework for **Dungeon Blitz** (compatible with browser servers, private servers such as `dungeonblitzr.theminesa.studio/web`, and desktop clients).

Designed to eliminate tedious dungeon grinding with high-precision movement replication, autonomous mob hunting, live screen diagnostics, and seamless pause-and-resume crash/death recovery.

---

## 🌟 Highlights & Core Features

### 🧩 1. In-Game Modular Puzzle Builder (Record While You Play)
Say goodbye to rigid, fragile 5-minute single-take macros. If you miss a jump at minute 4, you no longer have to throw away the entire recording.
- **`[F1]` Record Movement Step**: Start or stop recording precision parkour, jumping, and door transitions.
- **`[F2]` Save & Clear Room**: Instantly saves your movement segment, appends an autonomous `🤖 AUTO-MOB` step to your Puzzle, and immediately lets the AI take over to clear the room live in-game before returning your character to the exact starting marker!
- **✋ Drag-and-Drop Reordering**: Rearrange steps visually in the GUI with real-time slot animations and drag-and-drop mechanics.
- **✂️ Slice & Trim**: Cut long runs by seconds or trim dead air at the beginning/end while preserving held attack states.

### 🤖 2. Autonomous Auto-Mob AI
- **Multi-Scale Mob HP Bar Tracking**: Uses computer vision to locate enemies anywhere on screen in real time across browser windows and full-screen modes.
- **Configurable Advance Behaviors**:
  - `D (Right)` or `A (Left)`: Walks forward while auto-targeting enemies.
  - `Stand (Hold Position)`: Acts as a stationary sniper turret (clears enemies from spot, then immediately hands control back to the movement run).
- **Smart Mana & AoE Skill Logic**:
  - **Skills 4 & 5**: Fired immediately whenever off cooldown.
  - **Skill 5 (Shield) Safety Guard**: Enforces an anti-cancel delay so a second press does not disable your protective barrier.
  - **AoE Mob Memory**: When $\ge 3$ enemies are spotted, the bot remembers the pack for 20 seconds and conserves mana exclusively for **Skill 3 (AoE Burst)**. Against single targets, it conserves mana with **Skill 1**.
  - **Combat Linger & Oscillation Spread**: Shoots ahead at adjustable angles with multi-directional sweeping to hit flying or crouching mobs.

### 🧪 3. Real-Time Auto-Heal (Potion & Skills)
- Continuously scans the red elixir level in the player's bottom-left HP globe.
- Verifies whether **Skill 2 (Heal)** is fully colored (off cooldown) before casting.
- **Zero-Disruption Execution**: Casts healing instantly on the fly without interrupting moving or swinging.
- **Mana Conservation**: Prioritizes saving mana for emergency heals when HP drops below 50%.

### 🛡 4. 5-Tier Watchdog & Automatic Recovery
If something goes wrong, the bot never blindly flails into a wall:
1. **👼 Death Recovery (Angel Revive)**: Pauses the combat macro at the exact millisecond, releases input keys, runs your Revive macro, rewinds 3 seconds to ensure safety, and resumes combat seamlessly from the exact spot.
2. **🔌 Lost Connection Recovery**: Detects disconnection popups and executes a reconnect sequence.
3. **🌐 Server Reconnect**: Recovers automatically from "Play Again" server disconnect screens.
4. **🏰 Town / Lobby Recovery**: Detects accidental town transitions ("Enter Dungeon") and walks back into the portal.
5. **🚪 Dungeon Complete (Exit Run)**: Detects the victory score screen, pauses combat so you don't swing into thin air, executes your exit/re-enter sequence, and resets the loop fresh from Step 1.

### 🖥 5. Browser Window & Multi-Resolution Support
- Native support for playing directly inside modern web browsers (Chrome, Firefox, Brave, Edge).
- Automatically handles custom browser scaling, letterboxing, offsets, and high-DPI scaling.

---

## ⌨️ Default Keybindings

| Keybind | Function | Description |
|---|---|---|
| **`F1`** | **🧩 Record Movement Step** | In-game hotkey to start or stop recording a parkour/movement step |
| **`F2`** | **🤖 Auto-Mob Room Clear** | Saves current movement, inserts `🤖 AUTO-MOB` step, and clears the room live |
| **`F7`** | **🔴 Record Active Tab** | Starts/stops recording for whichever profile or recovery tab is currently open |
| **`F8`** | **⚡ Start / Pause Bot** | Toggles the automated infinite combat loop |
| **`F9`** or **`ESC`** | **🛑 Emergency Stop** | Instantly aborts all macros, releases mouse/keyboard hooks, and closes overlays |

> All keybindings can be fully remapped in the **Keybinds** tab.

---

## 🚀 Quickstart Guide

### Option A: 1-Click Launch (Recommended)
1. Download or clone this repository.
2. Double-click **`START_BOT.exe`** (or run `START_BOT.bat`).
3. The launcher automatically detects your Python environment, verifies dependencies, and launches the GUI with zero command-line fuss.

### Option B: Manual Terminal Launch
```bash
git clone https://github.com/your-username/dungeon-blitz-bot.git
cd dungeon-blitz-bot

# Install requirements
pip install -r requirements.txt

# Launch bot GUI
python main.py
```

---

## 📖 How to Build Your First Dungeon Run (In 2 Minutes)

1. **Launch Bot & Game**:
   - Open Dungeon Blitz in your browser or desktop window.
   - Open the Bot GUI. You will see the **Combat** tab with the **Puzzle Builder**.
2. **Enter Dungeon**: Stand at the dungeon entrance.
3. **Record Step 1 (Movement)**:
   - Press **`[F1]`**. The floating HUD overlay appears on your screen (`🔴 RECORDING: Step 1`).
   - Run through the door, do your parkour, and stop right before the mob room.
4. **Insert Room Clear**:
   - Press **`[F2]`**. The bot immediately saves Step 1, inserts **`🤖 AUTO-MOB (Step 2)`**, and takes over controls to kill all monsters in the room. Once the room is clear, it automatically returns your character to where you pressed `[F2]`.
5. **Record Step 3 (Next Corridor)**:
   - Press **`[F1]`** again to record your movement to the next room or boss.
6. **Start Farm Loop**:
   - Press **`[F8]`** to let the bot run your complete custom dungeon cycle automatically in an infinite loop!

---

## 🛠 Tech Stack & Architecture

- **GUI**: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) modern dark-mode responsive desktop interface.
- **Screen Capture**: [MSS](https://github.com/BoboTiG/python-mss) for ultra-fast, ultra-low-latency screen grabbing (60+ FPS).
- **Vision Pipeline**: [OpenCV](https://opencv.org/) template matching, adaptive thresholding, and multi-scale contour analysis for health globes, status effects, and mob detection.
- **Input Simulation**: Hardware-level mouse & keyboard automation via `pynput` and `PyDirectInput`.
- **Launcher**: C# compiled `.NET` stub (`START_BOT.exe`) with auto-install fallback.

---

## ⚖️ Disclaimer

This software is developed strictly for educational and personal experimentation purposes. Use responsibly in accordance with relevant terms of service. The developers assume no liability for account penalties or unintended consequences resulting from third-party game automation.
