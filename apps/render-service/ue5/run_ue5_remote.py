"""Send the import_scene_to_ue5.py script to a running UE5 editor via the
PythonScriptPlugin Remote Execution protocol, with the env vars our
script expects.

This is the "warm" version of run_ue5_headless.py : it reuses an already
open editor instead of spawning a fresh UnrealEditor-Cmd (which conflicts
with an opened editor through the project lock).

Usage :
    python run_ue5_remote.py --usda /path/scene.usda --output /path/out.png

Exit codes :
    0 — script ran and PNG exists
    1 — script ran but PNG missing
    2 — USDA missing
    3 — no UE5 editor responding to Remote Execution
    other — propagated from the editor side
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# remote_execution.py lives under textures/ (copied from the engine plugin)
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent / "textures"))
import remote_execution as rex  # type: ignore  # noqa: E402


def log(msg: str) -> None:
    print(f"[ue5_remote] {msg}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--usda", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--width", type=int, default=2048)
    p.add_argument("--height", type=int, default=2048)
    p.add_argument("--script", type=Path,
                   default=_THIS.parent / "import_scene_to_ue5.py")
    p.add_argument("--timeout", type=float, default=600.0)
    args = p.parse_args()

    if not args.usda.exists():
        log(f"!! USDA not found : {args.usda}")
        return 2
    if not args.script.exists():
        log(f"!! script not found : {args.script}")
        return 5

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Wipe a stale output so we can tell whether the render actually wrote one
    if args.output.exists():
        args.output.unlink()

    re_client = rex.RemoteExecution(rex.RemoteExecutionConfig())
    try:
        re_client.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not re_client.remote_nodes:
            time.sleep(0.2)
        if not re_client.remote_nodes:
            log("!! No UE5 editor responding to Remote Execution.")
            log("   Open UE5 with the archi project and check Project Settings >")
            log("   Python > Enable Remote Execution.")
            return 3
        node = re_client.remote_nodes[0]
        node_id = node.get("node_id") or node.get("nodeId")
        log(f"node : {node_id} ({node.get('project_name')})")
        re_client.open_command_connection(node_id)

        # Push env vars + invoke the import script, all in one inline statement
        # so it's atomic on the UE5 side.
        inline = (
            "import os, runpy;"
            f"os.environ['UE5_USDA_PATH'] = r'{args.usda}';"
            f"os.environ['UE5_OUTPUT_PNG'] = r'{args.output}';"
            f"os.environ['UE5_OUTPUT_WIDTH'] = '{args.width}';"
            f"os.environ['UE5_OUTPUT_HEIGHT'] = '{args.height}';"
            f"runpy.run_path(r'{args.script}', run_name='__main__')"
        )
        log(f"sending script : {args.script.name}")
        result = re_client.run_command(
            inline,
            unattended=False,
            exec_mode="ExecuteStatement",
            raise_on_failure=False,
        )
        out_log = result.get("output", []) if isinstance(result, dict) else []
        for entry in out_log:
            kind = entry.get("type", "Log")
            text = entry.get("output", "")
            print(f"  [{kind}] {text}")

        if not result.get("success"):
            log("✗ remote command reported failure")
            return 10

        if not args.output.exists():
            log(f"!! script finished but no PNG at {args.output}")
            return 1
        log(f"✓ render complete → {args.output} ({args.output.stat().st_size:,} bytes)")
        return 0
    finally:
        try:
            re_client.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
