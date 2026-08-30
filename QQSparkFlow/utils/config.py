import json
import logging
import os
import secrets
import sys
import tempfile
from copy import deepcopy
from enum import Enum
from pathlib import Path

from utils.logger import setup_logger


logger = setup_logger(level=logging.DEBUG)

DEBUG = False
CONFIGFILE = "config.json"
USERDATAFILE = "usersData.json"
APPSETTINGSFILE = "webui_settings.json"

# QQ SparkFlow no longer ships Douyin-specific keys: browser automation,
# protocol sender, friend-list scanning and persistent browser profiles are gone.
DEFAULT_CONFIG = {
    "messageTemplate": "🤩今日火花+1",
    "saveDebugArtifacts": False,
    "sendStrategy": {
        "shuffleTargets": True,
        "accountStartDelaySecondsMin": 15,
        "accountStartDelaySecondsMax": 60,
        "messageIntervalSecondsMin": 25,
        "messageIntervalSecondsMax": 70,
        "messageVariants": [
            "🤩今日火花+1",
            "今天来补个火花",
            "给你续一下今天的火花",
            "路过给你加个小火花",
        ],
    },
    "dailySendTime": "10:00",
    "dailySendJitterMinutes": 20,
    "imageMode": {
        "enabled": False,
        "images": [],
    },
    "hitokotoTypes": [
        "文学",
        "影视",
        "诗词",
        "哲学",
    ],
    "happyNewYear": {
        "enabled": False,
        "messageTemplate": "[data] [API]",
    },
}

DEFAULT_APP_SETTINGS = {
    "admin_username": "admin",
    "admin_password_hash": "",
    "session_secret": "",
    "session_max_age_seconds": 8 * 60 * 60,
    "compose_root": "",
    "ui_host": "0.0.0.0",
    "ui_port": 8787,
    "ops_log_file": "/var/log/qq-sparkflow.log",
}

config = None
userData = None
appSettings = None


class Environment(Enum):
    GITHUBACTION = "GITHUB_ACTION"
    LOCAL = "LOCAL"
    PACKED = "PACKED"

    def __str__(self):
        return self.value


def get_environment():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Environment.PACKED
    if os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.GITHUBACTION
    return Environment.LOCAL


def repo_root():
    return Path(__file__).resolve().parents[1]


def _runtime_root():
    env = get_environment()
    if env == Environment.PACKED:
        return Path(sys.executable).resolve().parent
    return repo_root()


def config_path():
    return _runtime_root() / CONFIGFILE


def users_data_path():
    return _runtime_root() / USERDATAFILE


def app_settings_path():
    return _runtime_root() / APPSETTINGSFILE


def default_compose_root():
    root = repo_root()
    parent = root.parent
    if (parent / "docker-compose.yml").exists():
        return str(parent)
    return str(root)


def _merge_defaults(data, defaults):
    merged = deepcopy(defaults)
    for key, value in data.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _load_json_file(path, defaults=None):
    if not path.exists():
        if defaults is None:
            raise FileNotFoundError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        return deepcopy(defaults)

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return deepcopy(defaults) if defaults is not None else None

    data = json.loads(text)
    if defaults is None:
        return data
    if not isinstance(data, dict) or not isinstance(defaults, dict):
        return data
    return _merge_defaults(data, defaults)


def _save_json_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def get_config(force_reload=False):
    global config
    if config is None or force_reload:
        config = _load_json_file(config_path(), DEFAULT_CONFIG)
    return deepcopy(config)


def save_config(new_config):
    global config
    config = _merge_defaults(new_config, DEFAULT_CONFIG)
    _save_json_file(config_path(), config)
    return deepcopy(config)


def get_userData(force_reload=False):
    global userData
    if userData is not None and not force_reload:
        return deepcopy(userData)

    env = get_environment()
    if env == Environment.GITHUBACTION:
        raw = os.getenv("USER_DATA", "")
        if not raw:
            logger.error("Environment variable USER_DATA is not set")
            raise RuntimeError("USER_DATA is required in GITHUB_ACTIONS mode")
        userData = json.loads(raw)
    else:
        userData = _load_json_file(users_data_path(), [])

    return deepcopy(userData)


def save_userData(accounts):
    global userData
    normalized = list(accounts)
    userData = normalized
    _save_json_file(users_data_path(), normalized)
    return deepcopy(userData)


def normalize_unique_id(unique_id):
    if not unique_id:
        return ""
    digits = "".join(ch for ch in str(unique_id) if ch.isdigit())
    return digits or str(unique_id).strip()


def get_app_settings(force_reload=False):
    global appSettings
    if appSettings is None or force_reload:
        appSettings = _load_json_file(app_settings_path(), DEFAULT_APP_SETTINGS)
        if not appSettings.get("session_secret"):
            appSettings["session_secret"] = secrets.token_urlsafe(32)
        if not appSettings.get("compose_root"):
            appSettings["compose_root"] = default_compose_root()
        _save_json_file(app_settings_path(), appSettings)
    return deepcopy(appSettings)


def save_app_settings(new_settings):
    global appSettings
    appSettings = _merge_defaults(new_settings, DEFAULT_APP_SETTINGS)
    if not appSettings.get("session_secret"):
        appSettings["session_secret"] = secrets.token_urlsafe(32)
    if not appSettings.get("compose_root"):
        appSettings["compose_root"] = default_compose_root()
    _save_json_file(app_settings_path(), appSettings)
    return deepcopy(appSettings)
