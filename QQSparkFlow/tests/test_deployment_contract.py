import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "QQSparkFlow"


class DeploymentContractTests(unittest.TestCase):
    def test_compose_contains_only_fixed_services(self):
        text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("web:", text)
        self.assertIn("scheduler:", text)
        for removed in ("proxy:", "login-desktop:", "task:", "mihomo"):
            self.assertNotIn(removed, text)

    def test_compose_web_builds_slim_image(self):
        text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("context: ./QQSparkFlow", text)
        self.assertIn("dockerfile: Dockerfile.server", text)
        self.assertIn("state/cron:/host-spool-cron", text)
        self.assertIn("networks: [sparkflow]", text)

    def test_scheduler_runs_cron_and_reply_listener(self):
        text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("cron_runner.py", text)
        self.assertIn("main.py --listen", text)

    def test_napcat_template_is_least_privilege(self):
        text = (REPO_ROOT / "deploy" / "compose-napcat.template.yml").read_text(encoding="utf-8")
        self.assertIn("mlikiowa/napcat-docker", text)
        self.assertIn('127.0.0.1:${WEBUI_PORT}:6099', text)
        self.assertIn("./state/napcat/${I}/QQ:/app/.config/QQ", text)
        self.assertIn("./state/napcat/${I}/config:/app/napcat/config", text)

    def test_runtime_files_are_gitignored(self):
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for path in ("state/", "docker-compose.override.yml", "QQSparkFlow/usersData.json", "QQSparkFlow/config.json"):
            self.assertIn(path, gitignore)


if __name__ == "__main__":
    unittest.main()
