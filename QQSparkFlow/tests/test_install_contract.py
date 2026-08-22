import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class InstallContractTests(unittest.TestCase):
    def setUp(self):
        self.install = REPO_ROOT / "deploy" / "install-server.sh"
        self.template = REPO_ROOT / "deploy" / "compose-napcat.template.yml"
        self.env_example = REPO_ROOT / ".env.example"

    def test_install_script_and_template_exist(self):
        self.assertTrue(self.install.is_file())
        self.assertTrue(self.template.is_file())

    def test_install_script_references_template(self):
        text = self.install.read_text(encoding="utf-8")
        self.assertIn("compose-napcat.template.yml", text)
        self.assertIn("setup_napcat.py", text)

    def test_template_port_rule_matches_summary(self):
        template_text = self.template.read_text(encoding="utf-8")
        install_text = self.install.read_text(encoding="utf-8")
        self.assertIn('127.0.0.1:${WEBUI_PORT}:6099', template_text)
        self.assertIn("webui_port=$((6098 + i))", install_text)
        self.assertIn("/webui", install_text)

    def test_env_example_covers_script_keys(self):
        env_text = self.env_example.read_text(encoding="utf-8")
        for key in (
            "APP_ROOT",
            "TZ",
            "WEB_PORT",
            "SPARKFLOW_SESSION_COOKIE_SECURE",
            "QQ_ACCOUNT_COUNT",
            "DEFAULT_SEND_TIME",
            "ONEBOT_ACCESS_TOKEN",
            "PIP_INDEX_URL",
            "PIP_TRUSTED_HOST",
        ):
            self.assertIn(f"{key}=", env_text)


if __name__ == "__main__":
    unittest.main()
