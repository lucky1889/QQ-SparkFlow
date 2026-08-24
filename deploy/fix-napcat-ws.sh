#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/qq-sparkflow}"
QQ_ACCOUNT_COUNT="${QQ_ACCOUNT_COUNT:-1}"
cd "$APP_ROOT"

if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

run_root() {
  if [ -n "$SUDO" ]; then
    sudo "$@"
  else
    "$@"
  fi
}

for account_index in $(seq 1 "$QQ_ACCOUNT_COUNT"); do
  config_host="$(ls state/napcat/${account_index}/config/onebot11_*.json 2>/dev/null | grep -v '/onebot11.json$' | head -1 || true)"
  if [ -z "$config_host" ]; then
    echo "[fix-napcat-ws] account ${account_index}: no logged-in onebot config yet; scan QR first and rerun"
    continue
  fi

  config_rel="${config_host#"$APP_ROOT"/}"
  onebot_token="$(grep '^ONEBOT_ACCESS_TOKEN=' .env | tail -1 | cut -d= -f2-)"
  echo "[fix-napcat-ws] patching ${config_rel}"

  run_root docker run --rm -v "$APP_ROOT":/work -w /work python:3.11-slim python - "$config_rel" "$onebot_token" <<'PY'
import json
import sys

path = "/work/" + sys.argv[1]
token = sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
data["network"]["websocketServers"] = [
    {
        "name": "wsServer",
        "enable": True,
        "host": "0.0.0.0",
        "port": 3001,
        "token": token,
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "debug": False,
        "heartInterval": 30000,
    }
]
with open(path, "w", encoding="utf-8") as handle:
    handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print("patched", path)
PY
done

qq_number="$(grep -o '"unique_id": "[0-9]*"' QQSparkFlow/usersData.json | head -1 | grep -o '[0-9]*' || true)"
if [ -n "$qq_number" ]; then
  run_root sed -i "s/ACCOUNT: .*/ACCOUNT: \"$qq_number\"/" docker-compose.override.yml
  echo "[fix-napcat-ws] set ACCOUNT=$qq_number"
fi

run_root docker compose up -d napcat-1 scheduler
echo "[fix-napcat-ws] done; wait 15s then run: docker compose logs --tail=30 napcat-1"
