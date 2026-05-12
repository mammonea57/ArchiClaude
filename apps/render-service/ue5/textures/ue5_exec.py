"""Tiny CLI to send Python code to a running UE5 editor via the
PythonScriptPlugin Remote Execution protocol.

Requires the project's `Python > Enable Remote Execution` toggle to be on
(no UE5 restart needed). The editor advertises itself over UDP multicast
on 239.0.0.1:6766 ; we discover it, open a unicast command channel, send
the script, and stream output back.

Usage :
    python ue5_exec.py --script "path/to/script_to_run.py"          # run a file
    python ue5_exec.py --inline  "print('hello from UE5')"          # run inline
    python ue5_exec.py --probe                                       # just list nodes
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Force UTF-8 stdout so Windows cp1252 doesn't choke on log glyphs
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# remote_execution.py lives next to this script (copied from UE5 plugin)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import remote_execution as rex  # type: ignore  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--script", type=Path, help="Python file to run inside UE5.")
    g.add_argument("--inline", type=str, help="Python statement(s) to run inline.")
    g.add_argument("--probe", action="store_true", help="Just discover nodes.")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="Seconds to wait for the editor's response.")
    p.add_argument("--exec-mode", default="ExecuteFile",
                   choices=["ExecuteFile", "ExecuteStatement", "EvaluateStatement"],
                   help="How UE5 should execute the payload.")
    args = p.parse_args()

    cfg = rex.RemoteExecutionConfig()
    re_client = rex.RemoteExecution(cfg)
    try:
        re_client.start()
        # Give the discovery loop a moment to catch the editor's broadcast
        deadline = time.monotonic() + 5
        nodes = []
        while time.monotonic() < deadline:
            nodes = re_client.remote_nodes
            if nodes:
                break
            time.sleep(0.2)
        if not nodes:
            print("[ue5_exec] No UE5 nodes discovered. Make sure the editor is "
                  "running with Python > Enable Remote Execution turned on.")
            return 2
        node = nodes[0]
        node_id = node.get("node_id") or node.get("nodeId")
        # The exact field set varies between UE versions — print it all
        # in probe mode to make discovery easy.
        print(f"[ue5_exec] Found UE5 node : {node_id}")

        if args.probe:
            for n in nodes:
                print(f"  - {n}")
            return 0

        re_client.open_command_connection(node["node_id"])
        if args.script:
            payload = str(args.script.resolve())
            mode = "ExecuteFile"
        else:
            payload = args.inline
            mode = args.exec_mode if args.exec_mode != "ExecuteFile" else "ExecuteStatement"
        print(f"[ue5_exec] Sending ({mode}) → {payload[:80]}{'…' if len(payload) > 80 else ''}")
        result = re_client.run_command(
            payload,
            unattended=False,
            exec_mode=mode,
            raise_on_failure=False,
        )
        out = result.get("output", []) if isinstance(result, dict) else []
        for entry in out:
            kind = entry.get("type", "Log")
            text = entry.get("output", "")
            print(f"  [{kind}] {text}")
        if result.get("success"):
            print("[ue5_exec] ✓ Command succeeded")
            return 0
        print("[ue5_exec] ✗ Command reported failure")
        return 1
    finally:
        try:
            re_client.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
