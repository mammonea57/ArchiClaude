"""Cross-platform launcher : starts UnrealEditor-Cmd with our Python script,
passes env vars for USDA input + PNG output, waits for completion, returns exit code.

Auto-detects UE5 install location on Windows / Linux / macOS.
Falls back to a user-supplied --ue5-bin path.

Usage :
    python run_ue5_headless.py \\
        --usda /path/to/scene.usda \\
        --output /path/to/out.png \\
        --project /path/to/ArchiClaude.uproject \\
        [--width 2048] [--height 2048] \\
        [--ue5-bin "C:\\Program Files\\Epic Games\\UE_5.4\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe"]
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ── Default UE5 install locations to probe ──────────────────────────
WINDOWS_CANDIDATES = [
    r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    r"C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    r"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    r"C:\Program Files\Epic Games\UE_5.4\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    r"D:\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    r"D:\Epic Games\UE_5.4\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
]
LINUX_CANDIDATES = [
    "/workspace/UnrealEngine/Engine/Binaries/Linux/UnrealEditor-Cmd",
    "/opt/UnrealEngine/Engine/Binaries/Linux/UnrealEditor-Cmd",
    str(Path.home() / "UnrealEngine/Engine/Binaries/Linux/UnrealEditor-Cmd"),
]
MAC_CANDIDATES = [
    "/Users/Shared/Epic Games/UE_5.4/Engine/Binaries/Mac/UnrealEditor-Cmd",
    "/Applications/Epic Games/UE_5.4/Engine/Binaries/Mac/UnrealEditor-Cmd",
]


def find_ue5_binary(override: Optional[str] = None) -> Optional[Path]:
    if override:
        p = Path(override)
        if p.exists():
            return p
        print(f"!! Override path not found : {override}")
        return None
    system = platform.system()
    candidates = {
        "Windows": WINDOWS_CANDIDATES,
        "Linux":   LINUX_CANDIDATES,
        "Darwin":  MAC_CANDIDATES,
    }.get(system, [])
    for c in candidates:
        if Path(c).exists():
            return Path(c)
    return None


def find_default_project() -> Optional[Path]:
    """Look for the ArchiClaude UE5 project in common locations.

    Probes both `ArchiClaude.uproject` (canonical name) and `archi.uproject`
    (short name used on the MSI render station). On Windows the project is
    deliberately kept out of `Documents` because that folder is OneDrive-synced
    on many setups and ruins UE5 perf — `C:\\UnrealProjects\\` is preferred.
    """
    project_names = ("ArchiClaude.uproject", "archi.uproject")
    project_dirs = [
        Path.cwd() / "ArchiClaudeUE5",
        Path.cwd(),
        Path("C:/UnrealProjects/ArchiClaude"),
        Path("C:/UnrealProjects/archi"),
        Path.home() / "Documents" / "Unreal Projects" / "ArchiClaude",
        Path.home() / "Documents" / "Unreal Projects" / "archi",
    ]
    for d in project_dirs:
        for name in project_names:
            candidate = d / name
            if candidate.exists():
                return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usda", type=Path, required=True,
                        help="Path to the .usda scene file to import.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Path where the rendered PNG should be written.")
    parser.add_argument("--project", type=Path, default=None,
                        help="Path to the UE5 .uproject (auto-detected if omitted).")
    parser.add_argument("--ue5-bin", default=None,
                        help="Override UE5 binary path.")
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument("--script", type=Path, default=None,
                        help="Override the Python script (default: ./import_scene_to_ue5.py)")
    args = parser.parse_args()

    if not args.usda.exists():
        print(f"!! USDA not found : {args.usda}")
        return 2

    ue5 = find_ue5_binary(args.ue5_bin)
    if ue5 is None:
        print("!! UnrealEditor-Cmd binary not found.")
        print("   Provide --ue5-bin <path> or install UE5 to a standard location.")
        return 3

    project = args.project or find_default_project()
    if project is None or not project.exists():
        print("!! No .uproject file found. Provide --project <path>.")
        return 4

    script = args.script or Path(__file__).resolve().parent / "import_scene_to_ue5.py"
    if not script.exists():
        print(f"!! Python script not found : {script}")
        return 5

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Try Remote Execution first : if UE5 is already open with the project
    # and Python > Enable Remote Execution is on, we can drive that editor
    # over UDP/TCP instead of cold-starting a separate UnrealEditor-Cmd
    # process (which would conflict on the project lock). Exit code 3 from
    # the remote helper means "no UE5 found" — in that case we fall back
    # to the cold-start path below.
    remote_helper = Path(__file__).resolve().parent / "run_ue5_remote.py"
    if remote_helper.exists():
        remote_cmd = [
            sys.executable, str(remote_helper),
            "--usda", str(args.usda),
            "--output", str(args.output),
            "--width", str(args.width),
            "--height", str(args.height),
        ]
        if args.script is not None:
            remote_cmd += ["--script", str(args.script)]
        print(f"Trying Remote Execution : {' '.join(remote_cmd)}")
        remote_proc = subprocess.run(remote_cmd)
        if remote_proc.returncode == 0:
            return 0
        if remote_proc.returncode != 3:
            # Real error from the remote path — don't mask it by cold-starting.
            return remote_proc.returncode
        print("Remote Execution unavailable — falling back to cold-start UnrealEditor-Cmd.")

    # Build the UE5 command. The Python script picks up paths via env vars.
    env = os.environ.copy()
    env["UE5_USDA_PATH"] = str(args.usda)
    env["UE5_OUTPUT_PNG"] = str(args.output)
    env["UE5_OUTPUT_WIDTH"] = str(args.width)
    env["UE5_OUTPUT_HEIGHT"] = str(args.height)
    env["UE5_QUIT_ON_DONE"] = "1"

    cmd = [
        str(ue5),
        str(project),
        f'-ExecutePythonScript="{script}"',
        "-Unattended",
        "-NoLogTimes",
        "-NullRHI" if platform.system() == "Linux" and not os.environ.get("DISPLAY") else "",
        "-AllowStdOutLogVerbosity",
    ]
    cmd = [c for c in cmd if c]   # strip empty

    print("=" * 60)
    print("Launching UnrealEditor headless")
    print("=" * 60)
    print(f"UE5 bin : {ue5}")
    print(f"Project : {project}")
    print(f"Script  : {script}")
    print(f"USDA    : {args.usda}")
    print(f"Output  : {args.output}")
    print(f"Size    : {args.width}×{args.height}")
    print(f"Command : {' '.join(cmd)}")
    print()

    proc = subprocess.run(cmd, env=env)
    if proc.returncode != 0:
        print(f"!! UE5 process exited with code {proc.returncode}")
        return proc.returncode

    if not args.output.exists():
        print(f"!! UE5 finished but output PNG not produced : {args.output}")
        return 6

    print(f"✓ UE5 render saved → {args.output} ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
