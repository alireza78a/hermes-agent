"""Tests for agent.execution_verifier — post-tool-call verification."""

import json
import os
import tempfile

import pytest

from agent.execution_verifier import (
    VerificationResult,
    verify_tool_result,
    _verify_terminal,
    _verify_write_file,
    _verify_patch,
)


# ===================================================================
# VerificationResult
# ===================================================================

class TestVerificationResult:
    def test_to_dict_success(self):
        vr = VerificationResult(
            verified=True, tool_name="terminal", check="git_clone_dir_exists",
        )
        d = vr.to_dict()
        assert d["verified"] is True
        assert d["tool"] == "terminal"
        assert d["check"] == "git_clone_dir_exists"
        assert "message" not in d  # empty message excluded

    def test_to_dict_failure_includes_message(self):
        vr = VerificationResult(
            verified=False, tool_name="write_file", check="file_written",
            message="VERIFICATION FAILED: file missing",
            details={"expected_path": "/tmp/foo.py", "exists": False},
        )
        d = vr.to_dict()
        assert d["verified"] is False
        assert "VERIFICATION FAILED" in d["message"]
        assert d["details"]["exists"] is False


# ===================================================================
# Terminal verifier
# ===================================================================

class TestTerminalVerifier:
    def test_git_clone_with_explicit_dir_exists(self, tmp_path):
        target = tmp_path / "myrepo"
        target.mkdir()
        args = {"command": f"git clone https://github.com/user/repo.git {target}"}
        result_data = {"output": "Cloning...", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is True
        assert vr.check == "git_clone_dir_exists"

    def test_git_clone_with_explicit_dir_missing(self, tmp_path):
        target = tmp_path / "nonexistent"
        args = {"command": f"git clone https://github.com/user/repo.git {target}"}
        result_data = {"output": "Cloning...", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is False
        assert "VERIFICATION FAILED" in vr.message

    def test_git_clone_inferred_dir_exists(self, tmp_path):
        # Simulate: git clone https://github.com/user/my-project.git
        # Should infer dir name "my-project" relative to workdir
        target = tmp_path / "my-project"
        target.mkdir()
        args = {
            "command": "git clone https://github.com/user/my-project.git",
            "workdir": str(tmp_path),
        }
        result_data = {"output": "Cloning...", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is True

    def test_git_clone_inferred_dir_missing(self, tmp_path):
        args = {
            "command": "git clone https://github.com/user/my-project.git",
            "workdir": str(tmp_path),
        }
        result_data = {"output": "Cloning...", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is False

    def test_git_clone_nonzero_exit_skipped(self):
        args = {"command": "git clone https://github.com/user/repo.git /tmp/x"}
        result_data = {"output": "fatal: ...", "exit_code": 128, "error": "clone failed"}
        vr = _verify_terminal(args, result_data)
        assert vr is None  # no verification on failure

    def test_mkdir_exists(self, tmp_path):
        target = tmp_path / "newdir"
        target.mkdir()
        args = {"command": f"mkdir -p {target}"}
        result_data = {"output": "", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is True
        assert vr.check == "mkdir_dir_exists"

    def test_mkdir_missing(self, tmp_path):
        target = tmp_path / "ghost"
        args = {"command": f"mkdir {target}"}
        result_data = {"output": "", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is False

    def test_unrelated_command_returns_none(self):
        args = {"command": "ls -la"}
        result_data = {"output": "total 0", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is None

    def test_git_clone_with_flags(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        args = {"command": f"git clone --depth 1 --branch main https://github.com/user/repo.git {target}"}
        result_data = {"output": "Cloning...", "exit_code": 0, "error": None}
        vr = _verify_terminal(args, result_data)
        assert vr is not None
        assert vr.verified is True


# ===================================================================
# write_file verifier
# ===================================================================

class TestWriteFileVerifier:
    def test_file_exists_and_nonempty(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')")
        args = {"path": str(f)}
        result_data = {"bytes_written": 14}
        vr = _verify_write_file(args, result_data)
        assert vr is not None
        assert vr.verified is True
        assert vr.details["size_bytes"] == 14

    def test_file_missing(self, tmp_path):
        args = {"path": str(tmp_path / "missing.py")}
        result_data = {"bytes_written": 10}
        vr = _verify_write_file(args, result_data)
        assert vr is not None
        assert vr.verified is False
        assert "VERIFICATION FAILED" in vr.message

    def test_file_exists_but_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        args = {"path": str(f)}
        result_data = {"bytes_written": 0}
        vr = _verify_write_file(args, result_data)
        assert vr is not None
        assert vr.verified is False
        assert "empty" in vr.message.lower()

    def test_skipped_on_error_result(self):
        args = {"path": "/some/file.py"}
        result_data = {"error": "Permission denied"}
        vr = _verify_write_file(args, result_data)
        assert vr is None

    def test_skipped_on_no_path(self):
        args = {}
        result_data = {"bytes_written": 10}
        vr = _verify_write_file(args, result_data)
        assert vr is None


# ===================================================================
# patch verifier
# ===================================================================

class TestPatchVerifier:
    def test_patched_file_exists(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("x = 1")
        args = {"path": str(f), "old_string": "x = 1", "new_string": "x = 2"}
        result_data = {"success": True, "diff": "...", "files_modified": [str(f)]}
        vr = _verify_patch(args, result_data)
        assert vr is not None
        assert vr.verified is True

    def test_patched_file_missing(self, tmp_path):
        missing = str(tmp_path / "gone.py")
        args = {"path": missing}
        result_data = {"success": True, "diff": "...", "files_modified": [missing]}
        vr = _verify_patch(args, result_data)
        assert vr is not None
        assert vr.verified is False
        assert "missing" in vr.message.lower()

    def test_replace_mode_fallback_to_path_arg(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text("const x = 1;")
        args = {"path": str(f), "old_string": "const x = 1;", "new_string": "const x = 2;"}
        result_data = {"success": True, "diff": "..."}
        # No files_modified or files_created in result (replace mode)
        vr = _verify_patch(args, result_data)
        assert vr is not None
        assert vr.verified is True

    def test_skipped_on_failure(self):
        args = {"path": "/tmp/foo.py"}
        result_data = {"success": False, "error": "Could not find old_string"}
        vr = _verify_patch(args, result_data)
        assert vr is None


# ===================================================================
# Integration: verify_tool_result
# ===================================================================

class TestVerifyToolResult:
    def test_augments_terminal_result(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        args = {"command": f"git clone https://github.com/x/repo.git {target}"}
        original = json.dumps({"output": "done", "exit_code": 0, "error": None})
        result = verify_tool_result("terminal", args, original)
        parsed = json.loads(result)
        assert "_verification" in parsed
        assert parsed["_verification"]["verified"] is True
        assert "_warning" not in parsed  # no warning on success

    def test_augments_write_file_result(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("data")
        args = {"path": str(f)}
        original = json.dumps({"bytes_written": 4})
        result = verify_tool_result("write_file", args, original)
        parsed = json.loads(result)
        assert "_verification" in parsed
        assert parsed["_verification"]["verified"] is True
        assert "_warning" not in parsed  # no warning on success

    def test_no_verifier_returns_unchanged(self):
        original = json.dumps({"results": [1, 2, 3]})
        result = verify_tool_result("web_search", {}, original)
        assert result == original

    def test_non_json_returns_unchanged(self):
        raw = "not valid json at all"
        result = verify_tool_result("terminal", {"command": "ls"}, raw)
        assert result == raw

    def test_unrelated_terminal_command_returns_unchanged(self):
        original = json.dumps({"output": "hello", "exit_code": 0, "error": None})
        result = verify_tool_result("terminal", {"command": "echo hello"}, original)
        parsed = json.loads(result)
        # No _verification because echo doesn't trigger any verifier
        assert "_verification" not in parsed

    def test_failure_propagates_warning_message(self, tmp_path):
        missing = str(tmp_path / "nope")
        args = {"command": f"git clone https://github.com/x/repo.git {missing}"}
        original = json.dumps({"output": "done", "exit_code": 0, "error": None})
        result = verify_tool_result("terminal", args, original)
        parsed = json.loads(result)
        assert parsed["_verification"]["verified"] is False
        assert "VERIFICATION FAILED" in parsed["_verification"]["message"]
        # Top-level _warning must be present and prominent
        assert "_warning" in parsed
        assert "VERIFICATION FAILED" in parsed["_warning"]
        assert "Do not assume this step succeeded" in parsed["_warning"]

    def test_write_file_missing_has_top_level_warning(self, tmp_path):
        args = {"path": str(tmp_path / "gone.py")}
        original = json.dumps({"bytes_written": 10})
        result = verify_tool_result("write_file", args, original)
        parsed = json.loads(result)
        assert parsed["_verification"]["verified"] is False
        assert "_warning" in parsed
        assert "VERIFICATION FAILED" in parsed["_warning"]

    def test_patch_missing_has_top_level_warning(self, tmp_path):
        missing = str(tmp_path / "deleted.py")
        args = {"path": missing}
        original = json.dumps({"success": True, "diff": "...", "files_modified": [missing]})
        result = verify_tool_result("patch", args, original)
        parsed = json.loads(result)
        assert parsed["_verification"]["verified"] is False
        assert "_warning" in parsed
        assert "Do not assume this step succeeded" in parsed["_warning"]
