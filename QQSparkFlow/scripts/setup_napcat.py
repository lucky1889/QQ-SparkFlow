"""Prepare NapCat OneBot11 config and usersData.json account skeletons.

Usage (from the repository root):
    python scripts/setup_napcat.py --count 2 --token <token> --state-dir state

This writes, for each account i = 1..count:
    <state-dir>/napcat/<i>/config/onebot11.json   (OneBot HTTP+WS servers)
and merges a matching account skeleton into usersData.json without touching
existing targets / login state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def napcat_service_name(index: int) -> str:
    return f"napcat-{index}"


def onebot11_config(token: str) -> dict:
    return {
        "network": {
            "httpServers": [
                {
                    "name": "httpServer",
                    "enable": True,
                    "port": 3000,
                    "host": "0.0.0.0",
                    "token": token,
                    "postUrls": [],
                    "postEventFormat": "json",
                }
            ],
            "websocketServers": [
                {
                    "name": "wsServer",
                    "enable": True,
                    "port": 3001,
                    "host": "0.0.0.0",
                    "token": token,
                }
            ],
            "websocketClients": [],
        },
        "musicSignUrl": "",
        "enableLocalFile2Url": False,
        "parseMultMsg": False,
    }


def account_skeleton(index: int, token: str, users_data: list[dict]) -> list[dict]:
    service = napcat_service_name(index)
    for account in users_data:
        if str((account.get("onebot") or {}).get("service")) == service:
            return users_data
    users_data.append(
        {
            "account_ref": f"acc-{index}",
            "unique_id": "",
            "username": f"账号{index}",
            "enabled": True,
            "onebot": {
                "service": service,
                "http_url": f"http://{service}:3000",
                "ws_url": f"ws://{service}:3001",
                "access_token": token,
            },
            "targets": [],
            "message_history": {},
            "online": False,
            "last_error": "",
        }
    )
    return users_data


def write_onebot_config(state_dir: Path, index: int, token: str) -> None:
    config_dir = state_dir / "napcat" / str(index) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / "onebot11.json"
    if not target.exists():
        target.write_text(json.dumps(onebot11_config(token), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_users_data(state_dir: Path, count: int, token: str, users_path: Path) -> None:
    del state_dir
    users_data = []
    if users_path.exists():
        try:
            loaded = json.loads(users_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                users_data = loaded
        except json.JSONDecodeError:
            users_data = []
    for index in range(1, count + 1):
        users_data = account_skeleton(index, token, users_data)
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(json.dumps(users_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--token", default="")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--users-data", default="QQSparkFlow/usersData.json")
    args = parser.parse_args(argv)

    count = max(1, args.count)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    for index in range(1, count + 1):
        write_onebot_config(state_dir, index, args.token)
        (state_dir / "napcat" / str(index) / "QQ").mkdir(parents=True, exist_ok=True)

    merge_users_data(state_dir, count, args.token, Path(args.users_data))
    return 0


if __name__ == "__main__":
    sys.exit(main())

