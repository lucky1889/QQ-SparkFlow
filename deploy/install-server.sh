#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/lucky1889/QQ-SparkFlow.git}"
BRANCH="${BRANCH:-main}"
APP_ROOT="${APP_ROOT:-/opt/qq-sparkflow}"
ACTION="${ACTION:-install}"
QQ_ACCOUNT_COUNT="${QQ_ACCOUNT_COUNT:-1}"
WEB_PORT="${WEB_PORT:-8787}"
DEFAULT_SEND_TIME="${DEFAULT_SEND_TIME:-10:00}"
ONEBOT_ACCESS_TOKEN="${ONEBOT_ACCESS_TOKEN:-}"

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

log() {
  printf '\n[install-server] %s\n' "$*"
}

install_base_tools() {
  if command -v curl >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    run_root apt-get update
    run_root apt-get install -y ca-certificates curl git
  elif command -v yum >/dev/null 2>&1; then
    run_root yum install -y ca-certificates curl git
  else
    echo "Install curl, git, and ca-certificates first." >&2
    exit 1
  fi
}

install_docker_debian() {
  . /etc/os-release
  local docker_id="${ID}"
  if [ "$docker_id" = "debian" ] || [ "$docker_id" = "ubuntu" ]; then
    run_root install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${docker_id}/gpg" | run_root tee /etc/apt/keyrings/docker.asc >/dev/null
    run_root chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${docker_id} ${VERSION_CODENAME} stable" | run_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    run_root apt-get update
    run_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    run_root apt-get install -y docker.io docker-compose-plugin
  fi
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  log "Installing Docker and Compose plugin"
  if command -v apt-get >/dev/null 2>&1; then
    install_docker_debian
  elif command -v yum >/dev/null 2>&1; then
    run_root yum install -y docker docker-compose-plugin
  else
    echo "Docker is not installed. Please install Docker with the Compose plugin first." >&2
    exit 1
  fi
  run_root systemctl enable --now docker || true
}

prepare_repo() {
  run_root mkdir -p "$(dirname "$APP_ROOT")"
  local config_backup="" users_backup="" env_backup=""
  if [ -f "$APP_ROOT/QQSparkFlow/config.json" ]; then
    config_backup="$(mktemp)"
    run_root cp "$APP_ROOT/QQSparkFlow/config.json" "$config_backup"
  fi
  if [ -f "$APP_ROOT/QQSparkFlow/usersData.json" ]; then
    users_backup="$(mktemp)"
    run_root cp "$APP_ROOT/QQSparkFlow/usersData.json" "$users_backup"
  fi
  if [ -f "$APP_ROOT/.env" ]; then
    env_backup="$(mktemp)"
    run_root cp "$APP_ROOT/.env" "$env_backup"
  fi

  if [ -d "$APP_ROOT/.git" ]; then
    log "Updating existing repository at $APP_ROOT"
    run_root git -C "$APP_ROOT" fetch origin "$BRANCH"
    run_root git -C "$APP_ROOT" checkout -B "$BRANCH" "origin/$BRANCH"
    run_root git -C "$APP_ROOT" reset --hard "origin/$BRANCH"
  else
    if [ -e "$APP_ROOT" ]; then
      echo "$APP_ROOT exists but is not a git checkout. Back up runtime data and move the directory aside before installing." >&2
      exit 1
    fi
    log "Cloning $REPO_URL#$BRANCH into $APP_ROOT"
    run_root git clone --branch "$BRANCH" "$REPO_URL" "$APP_ROOT"
  fi

  run_root mkdir -p "$APP_ROOT/QQSparkFlow"
  if [ -n "$config_backup" ]; then
    run_root cp "$config_backup" "$APP_ROOT/QQSparkFlow/config.json"
    rm -f "$config_backup"
    log "Restored runtime config.json after repository update"
  fi
  if [ -n "$users_backup" ]; then
    run_root cp "$users_backup" "$APP_ROOT/QQSparkFlow/usersData.json"
    rm -f "$users_backup"
    log "Restored runtime usersData.json after repository update"
  fi
  if [ -n "$env_backup" ]; then
    run_root cp "$env_backup" "$APP_ROOT/.env"
    rm -f "$env_backup"
    log "Restored .env after repository update"
  fi
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  tmp_file="$(mktemp)"
  if [ -f "$file" ]; then
    awk -v key="$key" -v value="$value" '
      BEGIN { replaced = 0 }
      $0 ~ "^" key "=" { print key "=" value; replaced = 1; next }
      { print }
      END { if (!replaced) print key "=" value }
    ' "$file" > "$tmp_file"
  else
    printf '%s=%s\n' "$key" "$value" > "$tmp_file"
  fi
  run_root cp "$tmp_file" "$file"
  rm -f "$tmp_file"
}

read_env_value() {
  local file="$1"
  local key="$2"
  if [ ! -f "$file" ]; then
    return 0
  fi
  grep -E "^${key}=" "$file" | tail -n 1 | cut -d= -f2- || true
}

generate_override() {
  local override_file="$APP_ROOT/docker-compose.override.yml"
  local tmp_file i webui_port
  tmp_file="$(mktemp)"
  for i in $(seq 1 "$QQ_ACCOUNT_COUNT"); do
    webui_port=$((6098 + i))
    sed "s/\${I}/$i/g; s/\${WEBUI_PORT}/$webui_port/g" "$APP_ROOT/deploy/compose-napcat.template.yml" >> "$tmp_file"
    printf '\n' >> "$tmp_file"
  done
  run_root cp "$tmp_file" "$override_file"
  rm -f "$tmp_file"
  log "Generated napcat services 1..$QQ_ACCOUNT_COUNT"
}

run_setup_napcat() {
  log "Running setup_napcat.py with python:3.11-slim"
  run_root docker run --rm -v "$APP_ROOT":/work -w /work python:3.11-slim \
    python QQSparkFlow/scripts/setup_napcat.py --count "$QQ_ACCOUNT_COUNT" \
    --token "$ONEBOT_ACCESS_TOKEN" --state-dir /work/state \
    --users-data /work/QQSparkFlow/usersData.json
}

cron_line_for() {
  local hour="$1" minute="$2" fallback_hour="$3" fallback_minute="$4"
  printf '%s %s * * * cd /app && python main.py --doTask >> /app/logs/app.log 2>&1\n' "$minute" "$hour"
  printf '%s %s * * * cd /app && env SPARKFLOW_MANUAL_RUN=1 SPARKFLOW_MANUAL_UNSENT_ONLY=1 PYTHONUNBUFFERED=1 python main.py --doTask >> /app/logs/app.log 2>&1\n' "$fallback_minute" "$fallback_hour"
}

write_default_cron() {
  local cron_file="$APP_ROOT/state/cron/root"
  if [ -s "$cron_file" ]; then
    return
  fi
  local hour minute fallback_hour fallback_minute total
  hour="${DEFAULT_SEND_TIME%%:*}"
  minute="${DEFAULT_SEND_TIME##*:}"
  hour=$((10#$hour))
  minute=$((10#$minute))
  total=$((hour * 60 + minute + 40))
  fallback_hour=$(((total / 60) % 24))
  fallback_minute=$((total % 60))
  hour="$(printf '%02d' "$hour")"
  minute="$(printf '%02d' "$minute")"
  {
    echo "# QQ SparkFlow daily send"
    cron_line_for "$hour" "$minute" "$fallback_hour" "$fallback_minute"
  } | run_root tee "$cron_file" >/dev/null
}

prepare_runtime_files() {
  local env_file="$APP_ROOT/.env"
  if [ ! -f "$env_file" ]; then
    run_root cp "$APP_ROOT/.env.example" "$env_file"
  fi

  if [ -z "$ONEBOT_ACCESS_TOKEN" ]; then
    ONEBOT_ACCESS_TOKEN="$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    log "Generated a random ONEBOT_ACCESS_TOKEN"
  fi

  set_env_value "$env_file" "APP_ROOT" "$APP_ROOT"
  set_env_value "$env_file" "TZ" "${TZ:-Asia/Shanghai}"
  set_env_value "$env_file" "WEB_PORT" "$WEB_PORT"
  set_env_value "$env_file" "SPARKFLOW_SESSION_COOKIE_SECURE" "${SPARKFLOW_SESSION_COOKIE_SECURE:-0}"
  set_env_value "$env_file" "QQ_ACCOUNT_COUNT" "$QQ_ACCOUNT_COUNT"
  set_env_value "$env_file" "DEFAULT_SEND_TIME" "$DEFAULT_SEND_TIME"
  set_env_value "$env_file" "ONEBOT_ACCESS_TOKEN" "$ONEBOT_ACCESS_TOKEN"
  set_env_value "$env_file" "PIP_INDEX_URL" "${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
  set_env_value "$env_file" "PIP_TRUSTED_HOST" "${PIP_TRUSTED_HOST:-pypi.tuna.tsinghua.edu.cn}"

  run_root mkdir -p \
    "$APP_ROOT/state/cron" \
    "$APP_ROOT/QQSparkFlow/logs"

  generate_override
  run_setup_napcat
  write_default_cron
}

compose_up() {
  cd "$APP_ROOT"
  log "Building and starting containers (this can take a few minutes)"
  run_root env DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose up -d --build

  local tries=0
  while [ "$tries" -lt 30 ]; do
    if curl -fsS "http://127.0.0.1:$WEB_PORT/login" -o /dev/null 2>/dev/null; then
      log "Web UI is reachable on port $WEB_PORT"
      break
    fi
    tries=$((tries + 1))
    sleep 2
  done
}

print_summary() {
  local host_ip
  host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  host_ip="${host_ip:-127.0.0.1}"

  echo
  echo "QQ SparkFlow is running."
  echo "Web UI: http://${host_ip}:${WEB_PORT}          （首次打开设置管理员账号密码）"
  echo
  echo "接下来扫码登录 QQ（本地终端执行隧道命令，再打开浏览器）："
  local i webui_port
  for i in $(seq 1 "$QQ_ACCOUNT_COUNT"); do
    webui_port=$((6098 + i))
    echo "  账号$i: ssh -L ${webui_port}:127.0.0.1:${webui_port} user@${host_ip}  -> 浏览器打开 http://127.0.0.1:${webui_port}/webui"
  done
  echo "扫码登录成功后回到 Web UI -> 账号管理 -> 添加好友 QQ 号即可。"
  echo
  echo "更新到最新版: ACTION=update bash $APP_ROOT/deploy/install-server.sh"
}

main() {
  case "$ACTION" in
    install|update) ;;
    *) echo "ACTION must be install or update" >&2; exit 1 ;;
  esac
  install_base_tools
  ensure_docker
  prepare_repo
  prepare_runtime_files
  compose_up
  print_summary
}

main "$@"



