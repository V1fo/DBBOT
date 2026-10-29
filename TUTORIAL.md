# ⚔️ Dungeon Blitz Bot - Complete User Tutorial

Welcome to the comprehensive walkthrough for the **Dungeon Blitz Auto-Bot**. This guide walks you through setting up, recording your first modular dungeon run, calibrating the vision detectors, and optimizing combat rotations for maximum efficiency.

---

## 📋 Table of Contents
1. [Prerequisites & Initial Setup](#1-prerequisites--initial-setup)
2. [Game Window Alignment](#2-game-window-alignment)
3. [Building a Modular Dungeon Run (The Puzzle System)](#3-building-a-modular-dungeon-run-the-puzzle-system)
4. [Autonomous Auto-Mob Configuration](#4-autonomous-auto-mob-configuration)
5. [Auto-Heal & Skill 2 Calibration](#5-auto-heal--skill-2-calibration)
6. [Failure Recovery Setup (Angel, Reconnect, Lobby, Exit)](#6-failure-recovery-setup-angel-reconnect-lobby-exit)
7. [In-Game Hotkeys & Emergency Stop](#7-in-game-hotkeys--emergency-stop)
8. [Troubleshooting & Tips](#8-troubleshooting--tips)

---

## 1. Prerequisites & Initial Setup

1. **System Requirements**: Windows 10 or Windows 11 (64-bit).
2. **Python**: Python 3.10 or higher installed. (If not already installed, download it from [python.org](https://www.python.org/) and make sure to check **"Add Python to PATH"** during installation).
3. **Launching the Bot**:
   - Simply double-click **`START_BOT.exe`** (or `START_BOT.bat`).
   - The launcher will automatically check whether the required libraries are installed. If any are missing, it will automatically install them via pip.
   - The bot GUI will open in dark mode.

---

## 2. Game Window Alignment

The bot supports both full-screen displays and standard browser windows (Chrome, Firefox, Edge, Brave):
- Make sure the game canvas is visible and unobstructed by other windows while the bot is active.
- If playing in a browser (e.g. `dungeonblitzr.theminesa.studio/web`), ensure browser zoom is set to **100%** (press `Ctrl + 0`).
- The bot automatically locates the player health globe, mana bar, and skill icons regardless of standard letterboxing or browser window offsets.

---

## 3. Building a Modular Dungeon Run (The Puzzle System)

Traditional macros record one continuous 5-minute video-like replay. If a door doesn't open or you mistime a jump at minute 4, the entire recording fails. 

With the **Puzzle System**, your dungeon run is divided into independent, modular steps:

```
[ Step 1: Movement ] ➔ [ Step 2: Auto-Mob ] ➔ [ Step 3: Parkour ] ➔ [ Step 4: Boss Auto-Mob ]
```

### In-Game Live Recording Process:
1. **Enter Dungeon**: Stand right at the entrance of the dungeon.
2. **Start Movement Step**: Press **`[F1]`**.
   - A floating HUD appears on your screen: `🔴 RECORDING: Step 1 (Movement)`.
   - Run forward, navigate stairs, and stop just before entering the monster room.
3. **Engage Auto-Mob**: Press **`[F2]`**.
   - The bot automatically saves Step 1 into your puzzle.
   - It inserts **`Step 2: 🤖 AUTO-MOB`** into the puzzle list.
   - The bot immediately takes over controls live in the game, clears all monsters in the room using your skills, and walks back to the spot where you pressed `[F2]`.
4. **Continue Movement**:
   - Press **`[F1]`** again. The live Auto-Mob finishes and the bot immediately starts recording **Step 3 (Movement)**.
   - Move through the cleared room, jump over platforms, and stop at the next room or boss door.
5. **Clear Boss Room**:
   - Press **`[F2]`** at the boss room to insert another Auto-Mob step.
6. **Save**:
   - Press **`[F1]`** to stop recording once the dungeon is complete.
7. **Run the Loop**:
   - Press **`[F8]`** at the dungeon entrance. The bot will execute your entire sequence, clearing rooms and navigating obstacles flawlessly in an infinite loop!

### Editing Steps in the GUI:
- **✋ Drag-and-Drop**: Click and hold any step card in the Puzzle list, drag it to a new position, and release. The steps reorder instantly.
- **✂️ Trim (`✂`)**: Remove dead waiting time from the beginning or end of a step without losing active attack states.
- **✏️ Rename (`✏`)**: Label steps (e.g. "Goblin Corridor", "Bridge Jump", "Dragon Boss").
- **🗑️ Delete (`🗑`)**: Remove an outdated step.

---

## 4. Autonomous Auto-Mob Configuration

Inside the **Auto-Mob** tab, you can fine-tune combat behaviors:

- **Advance Direction**:
  - `D (Right)`: Automatically walks right while shooting.
  - `A (Left)`: Automatically walks left while shooting.
  - `Stand (Hold Position)`: Character holds position (does not walk left or right) and attacks approaching enemies. Perfect for stationary defense or narrow ledges.
- **AoE Mob Threshold & Memory**:
  - `Mobs >= 3`: When 3 or more mob health bars appear on screen, the bot switches to AoE mode.
  - `Memory = 20s`: The bot remembers that an enemy pack is present for 20 seconds, conserving mana exclusively for **Skill 3 (AoE burst)** instead of draining it with single-target skills.
  - Against single mobs, it spams **Skill 1** to conserve mana.
- **Skills 4 & 5**:
  - Cast on cooldown automatically.
  - **Skill 5 (Shield) Cooldown Guard**: Sets a minimum delay (e.g. 15s) so pressing Skill 5 twice does not accidentally toggle the shield off.
- **Shoot Angle & Spread**:
  - `Angle`: Angle of aim (`0°` = straight forward, positive = angled upward for flying mobs, negative = downward).
  - `Spread`: Oscillation range (`±12°`) to sweep attacks vertically across enemies.

---

## 5. Auto-Heal & Skill 2 Calibration

In the **Heal** tab:
- **Enable Auto-Heal**: Keep checked.
- **HP Threshold %**: Default `40%`. When your health globe drops below 40%, the bot triggers your heal skill.
- **Heal Skill Key**: Set to your character's healing key (default `2`).
- **Save Mana for Heal**: When HP drops below `50%`, the bot stops using offensive skills to ensure enough mana is available for the heal spell.
- **Test Detection**: Click **`🔍 Test Current HP Level and Skill 2 Status`** while in-game. The diagnostic box will display the detected HP % and whether Skill 2 is ready to cast.

---

## 6. Failure Recovery Setup (Angel, Reconnect, Lobby, Exit)

The bot features 5 dedicated recovery subsystems under their respective tabs:

1. **👼 Revive (Death Recovery)**:
   - When you die, the combat macro pauses at that exact millisecond.
   - Go to the **Revive** tab, click **`🔴 Record Revive Run`** (or press `F7`), switch to the game, click the Angel's `REVIVE` button, run back to the room, and press `F7` to save.
   - When active, the bot automatically revives, rewinds 3 seconds to re-align, and resumes combat smoothly.
2. **🔌 Reconnect (Lost Connection)**:
   - Records the mouse click on the game's reconnect/reload prompt.
3. **🌐 Server Reconnect**:
   - Records clicking the "Play Again" button after a server-level drop.
4. **🏰 Lobby (Town Return)**:
   - If accidentally spawned back in town, records walking into the dungeon portal.
5. **🚪 Exit (Dungeon Complete)**:
   - When all mobs die and the end-of-dungeon scoreboard appears, the bot pauses combat, runs your recorded Exit macro (clicks `Exit Dungeon` and re-enters the dungeon portal), then starts a fresh run from Step 1.

---

## 7. In-Game Hotkeys & Emergency Stop

| Key | Purpose |
|---|---|
| **`[F1]`** | Start / Stop Movement Step recording |
| **`[F2]`** | Save Movement Step & trigger live Auto-Mob Room Clear |
| **`[F7]`** | Record active profile or recovery run |
| **`[F8]`** | Start / Pause automated bot loop |
| **`[F9]`** or **`[ESC]`** | **🛑 EMERGENCY STOP**: Immediately aborts all operations, releases mouse buttons, and clears overlays |

> **Pro Tip**: Even if the operating system is heavily loaded, hardware-level `[ESC]` detection is permanently active. Pressing `[ESC]` will always immediately halt the bot.

---

## 8. Troubleshooting & Tips

- **Bot is not finding mob health bars**:
  - Open the **Auto-Mob** tab and click **`🔍 Test Mob HP Bars, Mana & Skills Detection`**. Ensure the game window is not covered by any translucent overlay.
- **Skills are not triggering**:
  - Check the **Keybinds** tab and make sure your skill keys match your in-game setup (`1, 2, 3, 4, 5`).
- **Smooth mouse movements causing lag**:
  - If your PC is experiencing performance drops, uncheck **"Record smooth mouse movement"** in the main window to store only critical click/key events.
- **Accidental double shield toggle**:
  - In the Auto-Mob tab, increase **"Min interval for Skill 5 (Shield)"** to 15–20 seconds.
