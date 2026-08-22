import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from utils import config as config_module

from core import send_state
from core.send_state import (
    history_entry_is_strong_confirmed_today,
    history_entry_is_today,
    mark_replied_in_account,
    replied_today,
    target_is_strong_confirmed_today,
)


NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone(timedelta(hours=8)))


class SendStateTests(unittest.TestCase):
    def test_strong_confirmed_requires_status_and_message_id(self):
        confirmed = {"sentAt": NOW.isoformat(), "status": "confirmed", "message_id": 12345}
        no_message_id = {"sentAt": NOW.isoformat(), "status": "confirmed"}
        self.assertTrue(history_entry_is_strong_confirmed_today(confirmed, NOW))
        self.assertFalse(history_entry_is_strong_confirmed_today(no_message_id, NOW))

    def test_cross_day_entry_is_not_confirmed_today(self):
        yesterday = (NOW - timedelta(days=1)).isoformat()
        entry = {"sentAt": yesterday, "status": "confirmed", "message_id": 1}
        self.assertFalse(history_entry_is_strong_confirmed_today(entry, NOW))
        self.assertFalse(history_entry_is_today(entry, NOW))

    def test_target_is_strong_confirmed_today(self):
        account = {"message_history": {"20001": {"sentAt": NOW.isoformat(), "status": "confirmed", "message_id": 9}}}
        self.assertTrue(target_is_strong_confirmed_today(account, "20001", NOW))
        self.assertFalse(target_is_strong_confirmed_today(account, "20002", NOW))

    def test_reply_mark_and_read(self):
        account = {"message_history": {}}
        updated = mark_replied_in_account(account, "20001", NOW)
        self.assertTrue(replied_today(updated, "20001", NOW))
        self.assertFalse(replied_today(updated, "20002", NOW))

    def test_reply_does_not_survive_next_day(self):
        account = {"message_history": {"20001": {"repliedToday": True, "repliedAt": NOW.isoformat()}}}
        tomorrow = NOW + timedelta(days=1)
        self.assertFalse(replied_today(account, "20001", tomorrow))

    def test_mark_replied_today_persists(self):
        account = {"account_ref": "acc-1", "unique_id": "", "message_history": {}}
        with patch.object(config_module, "get_userData", return_value=[account]) as get, patch.object(config_module, "save_userData") as save:
            result = send_state.mark_replied_today(account, "20001", NOW)
        self.assertTrue(result)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()


