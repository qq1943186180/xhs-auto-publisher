"""
PyInstaller build script
Generates single-file EXE with all dependencies
"""
import os
import sys
import shutil
import subprocess


def _get_version():
    """从 src/__init__.py 读取版本号"""
    init_path = os.path.join("src", "__init__.py")
    if os.path.exists(init_path):
        with open(init_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    return "1.0.0"


def _cleanup():
    """清理构建中间产物"""
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            print(f"Cleaning: {d}/")
            shutil.rmtree(d, ignore_errors=True)

    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)
            print(f"Cleaning: {f}")


def build():
    """Execute build"""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    version = _get_version()
    print("=" * 50)
    print(f"XHS Auto Publisher v{version} - Build Tool")
    print("=" * 50)

    # Clean old build files
    _cleanup()

    # PyInstaller arguments
    exe_name = f"xhs-auto-publisher-{version}" if sys.platform == "win32" else f"xhs-auto-publisher-{version}"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        f"--name={exe_name}",
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

    try:
        result = subprocess.run(cmd, capture_output=False)
    except Exception as e:
        print(f"\n[FAIL] Build process error: {e}")
        _cleanup()
        sys.exit(1)

    if result.returncode == 0:
        exe_ext = ".exe" if sys.platform == "win32" else ""
        exe_path = os.path.join("dist", f"{exe_name}{exe_ext}")
        print(f"\n[OK] Build successful!")
        print(f"Output: {os.path.abspath('dist')}")
        print(f"File: {os.path.abspath(exe_path)}")

        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"Size: {size_mb:.1f} MB")
    else:
        print(f"\n[FAIL] Build failed, exit code: {result.returncode}")
        _cleanup()
        sys.exit(1)

    # Clean build intermediates on success
    _cleanup()
    print("\nDone.")


if __name__ == "__main__":
    build()
