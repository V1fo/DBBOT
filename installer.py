import os
import sys
import subprocess
import importlib.util

# Mapping from importable module name to pip package requirement
REQUIRED_PACKAGES = {
    "customtkinter": "customtkinter>=5.2.0",
    "keyboard": "keyboard>=0.13.5",
    "mss": "mss>=9.0.0",
    "numpy": "numpy>=1.24.0",
    "cv2": "opencv-python>=4.8.0",
    "PIL": "pillow>=10.0.0",
    "pydirectinput": "PyDirectInput>=1.0.4",
    "pynput": "pynput>=1.7.6",
}

def get_missing_packages() -> list:
    """Returns a list of pip package specifications that are not yet installed."""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_name)
    return missing

def ensure_dependencies() -> bool:
    """
    Checks if all required packages are installed.
    If any are missing, automatically downloads and installs them via pip.
    Uses a marker file for instant 0ms check on subsequent startups.
    """
    marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deps_ok")
    if os.path.exists(marker):
        return True

    missing = get_missing_packages()
    if not missing:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("ok")
        except Exception:
            pass
        return True

    print("=" * 65)
    print(" [DEPENDENCY CHECK]")
    print(f" Missing libraries detected ({len(missing)}):")
    for pkg in missing:
        print(f"   • {pkg}")
    print()
    print(" Automatically downloading and installing via pip...")
    print("=" * 65)
    print()

    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")

    try:
        if os.path.exists(req_file) and len(missing) == len(REQUIRED_PACKAGES):
            cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
        else:
            cmd = [sys.executable, "-m", "pip", "install"] + missing

        subprocess.check_call(cmd)
        print()
        print("=" * 65)
        print(" All required libraries have been successfully installed!")
        print("=" * 65)
        print()
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("ok")
        except Exception:
            pass
        return True
    except subprocess.CalledProcessError as e:
        err_msg = f"Error installing libraries via pip (Exit code: {e.returncode}). Please check your internet connection."
        try:
            print(f"\n❌ {err_msg}")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, err_msg, "DBBOT - Dependency Error", 0x10)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        err_msg = f"Unexpected error installing dependencies: {e}"
        try:
            print(f"\n❌ {err_msg}")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, err_msg, "DBBOT - Dependency Error", 0x10)
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    ensure_dependencies()
