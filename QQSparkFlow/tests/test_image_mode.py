import unittest

from core.msg_builder import build_message_candidates, build_messages_for_targets


class ImageModeTests(unittest.TestCase):
    def test_enabled_image_mode_returns_cq_image_candidates(self):
        config = {
            "imageMode": {
                "enabled": True,
                "images": ["https://example.com/one.png", "https://example.com/two.png"],
            },
            "sendStrategy": {"messageVariants": []},
        }
        self.assertEqual(
            ["[CQ:image,file=https://example.com/one.png]", "[CQ:image,file=https://example.com/two.png]"],
            build_message_candidates(config),
        )

    def test_disabled_image_mode_uses_text_candidates(self):
        config = {
            "imageMode": {"enabled": False, "images": ["https://example.com/one.png"]},
            "messageTemplate": "hello",
            "sendStrategy": {"messageVariants": []},
        }
        self.assertEqual(["hello"], build_message_candidates(config))

    def test_image_mode_plans_messages_for_targets(self):
        config = {
            "imageMode": {"enabled": True, "images": ["https://example.com/one.png"]},
            "sendStrategy": {"shuffleTargets": False, "messageVariants": []},
        }
        planned = build_messages_for_targets(["123", "456"], {}, config)
        self.assertEqual("[CQ:image,file=https://example.com/one.png]", planned["123"])
        self.assertEqual("[CQ:image,file=https://example.com/one.png]", planned["456"])


if __name__ == "__main__":
    unittest.main()
