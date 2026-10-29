import sys
import os

# Safe output initialization when running windowless (pythonw / START_BOT.exe)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 1. Fast dependency check (0ms instant startup via marker cache)
from installer import ensure_dependencies
try:
    ensure_dependencies()
except Exception:
    pass

# 2. Safe imports after verifying dependencies
import ctypes
try:
    import keyboard
    import config
    from gui import DungeonBlitzBotGUI
except ImportError:
    marker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deps_ok")
    if os.path.exists(marker_path):
        try:
            os.remove(marker_path)
        except Exception:
            pass
    ensure_dependencies()
    import keyboard
    import config
    from gui import DungeonBlitzBotGUI

def set_dpi_awareness():
    """Ensures 1:1 pixel coordinate matching on Windows."""
    try:
        # Per-monitor DPI aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def main():
    set_dpi_awareness()

    # Boost Windows timer resolution to 1ms for sub-millisecond input precision
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    app = DungeonBlitzBotGUI()

    # Configure application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
    if os.path.exists(icon_path):
        try:
            app.iconbitmap(icon_path)
        except Exception:
            pass

    def on_closing():
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        app.emergency_stop()
        app.destroy()
        sys.exit(0)

    app.protocol("WM_DELETE_WINDOW", on_closing)
    app.mainloop()

if __name__ == "__main__":
    main()
