"""
PyInstaller build script
Generates single-file EXE with all dependencies
"""
import os
import sys
import shutil
import subprocess


def build():
    """Execute build"""
    # Change to project directory
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)
    
    print("=" * 50)
    print("XHS Auto Publisher - Build Tool")
    print("=" * 50)

    # Clean old build files
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            print(f"Cleaning: {d}/")
            shutil.rmtree(d)

    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)
            print(f"Cleaning: {f}")

    # PyInstaller arguments
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name=xhs-auto-publisher",
        "--icon=NONE",
        "--add-data=README.md;.",
        "--hidden-import=sqlalchemy",
        "--hidden-import=sqlalchemy.sql.default_comparator",
        "--hidden-import=sqlalchemy.ext.baked",
        "--hidden-import=PIL",
        "--hidden-import=PyQt5",
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui",
        "--collect-all=sqlalchemy",
        "main.py",
    ]

    # Windows uses semicolon, Linux/Mac uses colon
    if sys.platform != "win32":
        cmd = [c.replace(";", ":") for c in cmd]

    print(f"\nRunning:\n{' '.join(cmd)}\n")
    print("Building, please wait...\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        exe_name = "xhs-auto-publisher.exe" if sys.platform == "win32" else "xhs-auto-publisher"
        exe_path = os.path.join("dist", exe_name)
        print(f"\n[OK] Build successful!")
        print(f"Output: {os.path.abspath('dist')}")
        print(f"File: {os.path.abspath(exe_path)}")

        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"Size: {size_mb:.1f} MB")
    else:
        print(f"\n[FAIL] Build failed, exit code: {result.returncode}")
        sys.exit(1)

    # Clean build intermediates
    if os.path.exists("build"):
        shutil.rmtree("build")
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)

    print("\nCleanup done.")


if __name__ == "__main__":
    build()
