# QQ SparkFlow

QQ 自动续火花系统。基于 [douyin-sparkflow](https://github.com/halfwaystudent/douyin-sparkflow) 改造：把浏览器自动化核心替换为 **NapCatQQ + OneBot v11**，保留多账号管理、消息模板、定时调度与 Web 控制台。

QQ 的“好友互动标识”（火花）需要双方持续互发消息。本系统每天定时向你配置的好友私聊发送一条续火花消息，并监听好友回复，在控制台上展示“今日已发 / 今日已回”。

> 风险提示：使用自动化工具操作 QQ 可能触发风控（异地登录、频繁消息、掉登录态）。请使用小号先行验证，自行承担风险。本工具只做低频、每日一次的发送。

## 特性

- 多 QQ 账号，每个账号独立好友列表与发送策略
- 每日定点发送 + 启动抖动 + 好友间随机间隔
- 消息模板多选 + 一言（Hitokoto）API + 节日祝福
- OneBot 回执强确认：`retcode == 0` 且有 `message_id` 才算“已发送”
- WebSocket 监听私聊回复，概览页展示“今日已回复”
- 多用户 Web 控制台（管理员 + 普通用户 + 账号隔离）
- Docker Compose 一键安装，装完只需扫码登录

## 快速开始

在 Linux 服务器（Debian/Ubuntu/CentOS）上执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/lucky1889/QQ-SparkFlow/main/deploy/install-server.sh)
```

脚本会询问 / 使用环境变量：

```bash
QQ_ACCOUNT_COUNT=1 WEB_PORT=8787 DEFAULT_SEND_TIME=10:00 \
  bash <(curl -fsSL https://raw.githubusercontent.com/lucky1889/QQ-SparkFlow/main/deploy/install-server.sh)
```

安装完成后：

1. 打开 `http://<服务器IP>:8787`，首次设置管理员账号密码。
2. 按脚本摘要逐账号建立 SSH 隧道，打开 NapCat WebUI 扫码登录 QQ。
3. 回到 Web UI → 账号管理 → 添加好友 QQ 号。

扫码隧道示例（账号 1）：

```bash
ssh -L 6099:127.0.0.1:6099 user@<服务器IP>
# 然后浏览器打开 http://127.0.0.1:6099/webui
```

## 架构

```
浏览器 ──> web (FastAPI, :8787) ── 账号/好友/发送控制
           scheduler (cron_runner + reply_listener)
           napcat-1..N (NapCatQQ, OneBot HTTP:3000 / WS:3001)
```

- `web`：Web 控制台，多用户认证、账号管理、概览与发送控制。
- `scheduler`：轮询 crontab 触发每日发送；为每个账号维护一条 OneBot WebSocket 长连接监听回复。
- `napcat-N`：每个 QQ 账号一个 NapCat 容器，登录态持久化在 `state/napcat/<N>/QQ`。

## 目录

```
qq-sparkflow/
├── deploy/install-server.sh              # 一键安装 / 更新
├── deploy/compose-napcat.template.yml    # NapCat 服务生成模板
├── docker-compose.yml                    # web + scheduler
├── .env.example
└── QQSparkFlow/
    ├── main.py                           # CLI: --doTask / --listen / --web
    ├── core/onebot.py                    # OneBot v11 HTTP 客户端
    ├── core/reply_listener.py            # WS 回复监听
    ├── core/tasks.py                     # 每日发送主流程
    ├── core/accounts.py                  # 账号增删改查
    ├── core/msg_builder.py               # 模板/一言/节日
    ├── core/send_state.py                # 已发/已回状态
    ├── scripts/cron_runner.py            # crontab 轮询触发
    ├── scripts/setup_napcat.py           # 预写 OneBot 配置与账号骨架
    ├── utils/                            # config / hitokoto / logger
    ├── webui/                            # FastAPI Web 控制台
    └── tests/
```

## 配置

- `QQSparkFlow/config.json`：消息模板、发送策略、每日时刻、一言分类、节日模式（首次运行自动生成）。
- `QQSparkFlow/usersData.json`：账号列表与好友列表（由安装脚本生成骨架，Web UI 填写好友）。

账号数据结构：

```json
{
  "account_ref": "acc-1",
  "unique_id": "",
  "username": "账号1",
  "enabled": true,
  "onebot": {
    "service": "napcat-1",
    "http_url": "http://napcat-1:3000",
    "ws_url": "ws://napcat-1:3001",
    "access_token": "<token>"
  },
  "targets": [{"user_id": "123456789", "remark": "小明"}],
  "message_history": {}
}
```

## 更新与扩容

```bash
ACTION=update bash /opt/qq-sparkflow/deploy/install-server.sh
```

新增第 3 个 QQ 账号：

```bash
QQ_ACCOUNT_COUNT=3 ACTION=update bash /opt/qq-sparkflow/deploy/install-server.sh
```

更新会备份并还原 `.env`、`config.json`、`usersData.json`，登录态在 `state/` 卷中保持不变。

## 测试

```bash
cd QQSparkFlow
python -m unittest discover -s tests -v
```

## 已知限制

- OneBot 无法读取 QQ 火花天数；系统保证“我方每日发送”，回复监听用于推断展示。
- 火花需要双方互动才增长，单方发送不保证一定续上。
- NapCat 配置 Schema 随版本可能变化；核心协议封装集中在 `core/onebot.py`。

