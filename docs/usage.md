# 使用说明

## 1. 安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/lucky1889/QQ-SparkFlow/main/deploy/install-server.sh)
```

默认参数：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QQ_ACCOUNT_COUNT` | `1` | QQ 账号数量（对应 napcat-1..N） |
| `WEB_PORT` | `8787` | Web 控制台端口 |
| `DEFAULT_SEND_TIME` | `10:00` | 每日发送时刻 |
| `ONEBOT_ACCESS_TOKEN` | 自动生成 | OneBot HTTP/WS 鉴权令牌 |

## 2. 初始化管理员

浏览器打开 `http://<服务器IP>:8787`，按页面提示设置管理员用户名与密码。

## 3. 扫码登录 QQ

NapCat WebUI 默认只监听 `127.0.0.1`，需要通过 SSH 隧道访问：

```bash
ssh -L 6099:127.0.0.1:6099 user@<服务器IP>
```

然后本地浏览器打开 `http://127.0.0.1:6099/webui`，扫码登录。

- 账号 1 使用端口 `6099`，账号 2 使用 `6100`，依次类推（`6098 + i`）。
- 登录态保存在服务器 `state/napcat/<i>/QQ`，重启后仍有效。

> 安全说明：不要把 NapCat WebUI 端口暴露到公网。如需远程直接访问，必须配合防火墙 / VPN，并自行承担风险。

## 4. 添加好友 QQ 号

1. Web UI 顶部「账号管理」。
2. 在对应账号卡片填写好友 QQ 号（逗号分隔）。
3. 可点击「拉取好友列表校验」，系统会调用 OneBot `get_friend_list` 检查目标是否仍是好友。
4. 保存后，每日定时任务会向这些好友发送续火花消息。

## 5. 发送与状态

- 概览页：展示每个账号在线状态、今日已发、今日已回。
- 发送控制台：可手动「立即执行」「补发未发」「重发失败」。
- 回复监听：好友向你私聊发送消息后，对应目标会标记为“今日已回复”。

## 6. 修改发送时间 / 模板

Web UI → 运行配置：

- `每日发送时刻`：例如 `10:00`（同时写入 crontab，40 分钟后自动补发一轮）。
- `启动抖动`：到点后随机延迟 0~N 分钟，避免每天同一秒发送。
- `消息间隔`：同一账号好友间随机等待的最小/最大秒数。
- `消息模板变体`：每行一条，每日随机选择并避免与昨日重复。
- `图片模式`：填写每行一个图片 URL 并开启开关后，每日定时任务只发送图片，不发送文字（图片地址需为 QQ/NapCat 可访问的 HTTP/HTTPS URL）。
- `一言分类`：`[API]` 模板占位符使用。

## 7. 更新与扩容

```bash
ACTION=update bash /opt/qq-sparkflow/deploy/install-server.sh
```

扩容到 3 个账号：

```bash
QQ_ACCOUNT_COUNT=3 ACTION=update bash /opt/qq-sparkflow/deploy/install-server.sh
```

## 8. 常见问题

**账号显示掉线？**
NapCat 登录态可能失效或 QQ 被顶号。重新执行扫码登录，必要时在 NapCat WebUI 中重启服务。

**好友没收到消息？**
查看「运行日志」页；确认 OneBot 服务在线、好友 QQ 号正确且仍是好友。

**提示 `get_login_info` 失败？**
NapCat 容器可能未启动或 OneBot 端口未开启。检查 `docker ps` 与 `state/napcat/<i>/config/onebot11.json`。

## 9. 风险提示

QQ 对自动化操作有风控机制，异地登录、频繁发消息、异常频率都可能触发验证码或封禁。建议：

- 用小号先行验证，稳定后再上主号。
- 保持每日一次的低频发送，不要调成分钟级。
- 使用固定服务器 IP 长期挂机，减少异地登录触发。
- 本项目仅供学习交流，使用后果自负。

