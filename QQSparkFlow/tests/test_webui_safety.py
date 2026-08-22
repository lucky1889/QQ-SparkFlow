import errno
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from core import tasks
from webui import app as app_module
from webui import ops


class WebUiSafetyTests(unittest.TestCase):
    def test_windows_invalid_pid_probe_is_treated_as_dead(self):
        error = OSError(errno.EINVAL, "invalid pid")
        error.winerror = 87
        with patch.object(ops.os, "kill", side_effect=error):
            self.assertFalse(ops._pid_is_alive(999999))
        with patch.object(tasks.os, "kill", side_effect=error):
            self.assertFalse(tasks._pid_is_alive(999999))

    def test_missing_optional_runtime_tools_do_not_log_warnings(self):
        missing_cron = Path(tempfile.mkdtemp()) / "missing" / "root"
        with (
            patch.object(ops.subprocess, "run", side_effect=FileNotFoundError("missing")),
            patch.object(ops, "cron_file_path", return_value=missing_cron),
            patch.object(ops.logger, "warning") as warning,
            patch.object(ops.logger, "debug") as debug,
        ):
            result = ops.run_command(["docker", "ps"])
            self.assertEqual(1, result.returncode)
            ops.read_crontab()

        warning.assert_not_called()
        self.assertGreaterEqual(debug.call_count, 2)

    def test_stale_lock_inspection_does_not_delete_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "logs" / "task.run.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("99999999\n", encoding="utf-8")
            old = time.time() - 10800
            os.utime(lock_path, (old, old))

            with patch.object(ops, "repo_root", return_value=root):
                status = ops.task_run_lock_status()

            self.assertTrue(lock_path.exists())
            self.assertTrue(status["stale"])
            self.assertFalse(status["running"])
            self.assertEqual("owner_pid_missing", status["staleReason"])

    def test_overview_snapshot_excludes_sensitive_payloads(self):
        send_console = {
            "now": "2026-08-22T10:00:00+08:00",
            "summary": {
                "enabled_accounts": 1,
                "total_targets": 2,
                "today_confirmed_targets": 1,
                "today_replied_targets": 1,
                "today_failed_targets": 0,
                "today_pending_targets": 1,
                "today_attention_targets": 1,
                "serverReceipt": {"secret": True},
            },
            "accounts": [
                {
                    "unique_id": "acc-1",
                    "account_ref": "acc-1",
                    "username": "Account",
                    "online": True,
                    "enabled": True,
                    "total_targets": 2,
                    "confirmed_count": 1,
                    "replied_count": 1,
                    "failed_count": 0,
                    "pending_count": 1,
                    "message": "secret message",
                    "reason": "secret reason",
                    "serverReceipt": {"secret": True},
                    "cookies": "secret cookies",
                }
            ],
        }

        with (
            patch.object(ops, "get_send_console_snapshot", return_value=send_console),
            patch.object(ops, "get_schedule_snapshot", return_value={"label": "10:00", "nextTriggerAt": ""}),
            patch.object(ops, "task_run_lock_status", return_value={"running": False, "stale": False, "ageSeconds": 0}),
        ):
            payload = ops.get_overview_snapshot()

        serialized = repr(payload)
        self.assertNotIn("secret message", serialized)
        self.assertNotIn("cookies", serialized)
        self.assertNotIn("serverReceipt", serialized)
        self.assertNotIn("secret reason", serialized)

    def test_primary_pages_and_local_icons_render(self):
        with TestClient(app_module.app, raise_server_exceptions=False) as client:
            self.assertEqual(200, client.get("/login").status_code)
            self.assertEqual(200, client.get("/static/lucide.min.js").status_code)

            with patch.object(app_module, "current_user", return_value="admin"):
                for path in ("/", "/ops/send-console", "/ops/logs"):
                    response = client.get(path)
                    self.assertEqual(200, response.status_code, path)


if __name__ == "__main__":
    unittest.main()
