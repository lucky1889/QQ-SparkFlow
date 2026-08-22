import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core import reply_listener


ACCOUNT = {
    "account_ref": "acc-1",
    "unique_id": "10001",
    "username": "me",
    "enabled": True,
    "targets": [{"user_id": "20001", "remark": "小明"}, {"user_id": "20002", "remark": "小红"}],
    "message_history": {},
}


def private_event(user_id="20001", self_id="10001"):
    return {
        "post_type": "message",
        "message_type": "private",
        "user_id": user_id,
        "self_id": self_id,
        "sender": {"user_id": user_id, "nickname": "friend"},
        "message": "hi",
    }


class ReplyListenerTests(unittest.TestCase):
    def test_private_message_from_target_matches(self):
        self.assertTrue(reply_listener.event_matches_account(ACCOUNT, private_event()))

    def test_group_message_is_ignored(self):
        event = private_event()
        event["message_type"] = "group"
        self.assertFalse(reply_listener.event_matches_account(ACCOUNT, event))

    def test_non_target_user_is_ignored(self):
        self.assertFalse(reply_listener.event_matches_account(ACCOUNT, private_event("99999")))

    def test_self_id_mismatch_is_ignored(self):
        self.assertFalse(reply_listener.event_matches_account(ACCOUNT, private_event(self_id="66666")))

    def test_handle_event_persists_reply(self):
        with patch.object(reply_listener, "mark_replied_today", return_value=True) as mark:
            now = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
            result = reply_listener.handle_event(ACCOUNT, private_event(), now)
        self.assertTrue(result)
        mark.assert_called_once()

    def test_handle_event_ignores_other_messages(self):
        with patch.object(reply_listener, "mark_replied_today") as mark:
            result = reply_listener.handle_event(ACCOUNT, private_event("99999"))
        self.assertFalse(result)
        mark.assert_not_called()

    def test_backoff_caps_at_sixty(self):
        self.assertEqual(1, reply_listener.backoff_seconds(0))
        self.assertEqual(2, reply_listener.backoff_seconds(1))
        self.assertEqual(4, reply_listener.backoff_seconds(2))
        self.assertEqual(60, reply_listener.backoff_seconds(100))


if __name__ == "__main__":
    unittest.main()
