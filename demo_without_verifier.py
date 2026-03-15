#!/usr/bin/env python3
"""
Demo: Raw tool output WITHOUT Execution Integrity Layer.

Shows the same 8 scenarios as demo_execution_verifier.py but returns
raw tool output with NO _verification or _warning fields — this is
what the model sees when the verifier is disabled.

Compare side-by-side:
    python3 demo_without_verifier.py   # raw output (before)
    python3 demo_execution_verifier.py # augmented output (after)
"""

import json
import os
import tempfile
from pathlib import Path


def _pp(label: str, result_json: str):
    """Pretty-print a raw tool result."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    try:
        data = json.loads(result_json)
        print(json.dumps(data, indent=2))
    except json.JSONDecodeError:
        print(result_json)


def main():
    print("Raw Tool Output — No Verification (Before)")
    print("Same 8 scenarios, but the model gets ONLY the tool's own JSON.\n")

    with tempfile.TemporaryDirectory(prefix="hermes-demo-") as tmpdir:

        # ── 1. git clone — SUCCESS ─────────────────────────────────────
        clone_dir = os.path.join(tmpdir, "my-project")
        os.makedirs(clone_dir)  # simulate successful clone

        result = json.dumps({"output": "Cloning into 'my-project'...\ndone.", "exit_code": 0, "error": None})
        _pp("1. git clone — directory EXISTS (no verification)", result)

        # ── 2. git clone — FAILURE ─────────────────────────────────────
        result = json.dumps({"output": "Cloning into 'ghost-repo'...\ndone.", "exit_code": 0, "error": None})
        _pp("2. git clone — directory MISSING (no verification)", result)

        # ── 3. write_file — SUCCESS ────────────────────────────────────
        written_file = os.path.join(tmpdir, "hello.py")
        Path(written_file).write_text("print('hello world')\n")

        result = json.dumps({"bytes_written": 21})
        _pp("3. write_file — file EXISTS and non-empty (no verification)", result)

        # ── 4. write_file — EMPTY FILE ─────────────────────────────────
        empty_file = os.path.join(tmpdir, "empty.txt")
        Path(empty_file).write_text("")

        result = json.dumps({"bytes_written": 0})
        _pp("4. write_file — file EXISTS but EMPTY (no verification)", result)

        # ── 5. write_file — MISSING FILE ───────────────────────────────
        result = json.dumps({"bytes_written": 3})
        _pp("5. write_file — file MISSING after write (no verification)", result)

        # ── 6. patch — SUCCESS ─────────────────────────────────────────
        patched_file = os.path.join(tmpdir, "app.py")
        Path(patched_file).write_text("x = 2\n")

        result = json.dumps({"success": True, "diff": "- x = 1\n+ x = 2", "files_modified": [patched_file]})
        _pp("6. patch — modified file EXISTS (no verification)", result)

        # ── 7. patch — MISSING AFTER PATCH ──────────────────────────────
        deleted_path = os.path.join(tmpdir, "deleted.py")
        result = json.dumps({"success": True, "diff": "...", "files_modified": [deleted_path]})
        _pp("7. patch — modified file MISSING (no verification)", result)

        # ── 8. Unrelated tool — passthrough ─────────────────────────────
        result = json.dumps({"results": [{"title": "asyncio docs", "url": "https://..."}]})
        _pp("8. web_search — passthrough (no verification)", result)

    print(f"\n{'='*60}")
    print("  Demo complete. Notice: NO _verification or _warning fields.")
    print("  The model has no signal that scenarios 2, 4, 5, 7 failed.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
