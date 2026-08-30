"""FastAPI Web UI for QQ SparkFlow.

Keeps the original multi-user/auth skeleton while replacing every
Douyin-specific route (login desktop, browser workspace, proxy control) with
the NapCat/OneBot account model.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core import accounts as accounts_module
from core.send_state import mark_replied_today  # noqa: F401  (kept available for future API)
from utils.config import get_app_settings, get_config, get_userData, save_config
from webui.auth import (
    bootstrap_admin_password,
    clear_session,
    csrf_token,
    current_principal,
    current_user,
    is_admin,
    is_bootstrapped,
    is_https_request,
    issue_session,
    update_admin_password,
    validate_csrf,
    verify_password,
)
from webui.ops import (
    get_overview_snapshot,
    get_send_console_snapshot,
    get_schedule_snapshot,
    persist_schedule_config,
    read_log_tail,
    run_failed_retry_now,
    run_task_now,
    run_unsent_retry_now,
    sync_daily_schedule_from_config,
    task_run_lock_status,
)
from webui.users import (
    UserStoreError,
    account_by_unique_id,
    can_access_account,
    create_web_user,
    delete_web_user,
    ensure_account_refs,
    get_web_users,
    remove_account_refs_from_users,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_targets_from_form(form):
    raw = str(form.get("targets") or "").replace(",", "\n").replace("，", "\n")
    return _dedupe(raw.splitlines())


def _form_bool(form, key):
    return str(form.get(key) or "").strip() in ("1", "true", "on", "yes")


def create_app():
    settings = get_app_settings()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            ensure_account_refs(get_userData(force_reload=True))
        except Exception as exc:
            logger.warning("ensure_account_refs failed: %s", exc)
        try:
            sync_daily_schedule_from_config()
        except Exception as exc:
            logger.warning("Failed to synchronize the configured daily schedule: %s", exc)
        yield

    secure_cookie = str(os.getenv("SPARKFLOW_SESSION_COOKIE_SECURE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    app = FastAPI(title="QQ SparkFlow Admin", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings["session_secret"],
        max_age=settings["session_max_age_seconds"],
        same_site="lax",
        https_only=secure_cookie,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return PlainTextResponse("Internal Server Error", status_code=500, headers={"Cache-Control": "no-store"})

    def render_template(request, template_name, context=None, status_code=200):
        base_context = dict(context or {})
        base_context.update(
            {
                "request": request,
                "current_user": current_user(request),
                "csrf_token": csrf_token(request) if current_user(request) else "",
                "is_https": is_https_request(request),
                "principal": current_principal(request),
                "is_admin": bool(current_principal(request) and current_principal(request).get("role") == "admin"),
            }
        )
        return templates.TemplateResponse(
            request,
            template_name,
            base_context,
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    def redirect(path="/", status_code=303):
        return RedirectResponse(url=path, status_code=status_code)

    def principal(request):
        resolved = current_principal(request)
        if resolved:
            return resolved
        legacy_user = current_user(request)
        admin_username = str(get_app_settings().get("admin_username", "admin")).strip() or "admin"
        if legacy_user and str(legacy_user).casefold() == admin_username.casefold():
            return {"username": admin_username, "role": "admin", "account_refs": [], "session_id": "", "enabled": True}
        return None

    def require_user(request):
        if not principal(request):
            return redirect("/login")
        return None

    def require_admin(request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        if principal(request).get("role") != "admin":
            return PlainTextResponse("Forbidden", status_code=403)
        return None

    def principal_account_refs(request):
        current = principal(request)
        if not current or current.get("role") == "admin":
            return None
        return list(current.get("account_refs", []))

    def scoped_accounts(request):
        accounts, _ = ensure_account_refs(get_userData(force_reload=True))
        refs = principal_account_refs(request)
        if refs is None:
            return accounts
        return [account for account in accounts if account.get("account_ref") in set(refs)]

    def account_for_request(request, unique_id):
        accounts = scoped_accounts(request)
        account = account_by_unique_id(accounts, unique_id)
        if not account:
            return accounts, None, PlainTextResponse("Account not found", status_code=404)
        if not can_access_account(principal(request), account):
            return accounts, None, PlainTextResponse("Forbidden", status_code=403)
        return accounts, account, None

    def flash(request, message, level="info"):
        request.session["flash"] = {"message": message, "level": level}

    def pop_flash(request):
        return request.session.pop("flash", None)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if current_user(request):
            return redirect("/")
        return render_template(
            request,
            "login.html",
            {"bootstrapped": is_bootstrapped(), "flash": pop_flash(request)},
        )

    @app.post("/login")
    async def login_action(request: Request):
        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        if not is_bootstrapped():
            return redirect("/login")
        user = verify_login(username, password)
        if not user:
            flash(request, "用户名或密码错误", "error")
            return redirect("/login")
        issue_session(request, user["username"], role=user.get("role", "user"), account_refs=user.get("account_refs", []))
        return redirect("/")

    @app.post("/bootstrap")
    async def bootstrap_action(request: Request):
        form = await request.form()
        if is_bootstrapped():
            return redirect("/login")
        username = str(form.get("username") or "admin").strip() or "admin"
        password = str(form.get("password") or "")
        confirm = str(form.get("confirm_password") or "")
        if len(password) < 6:
            flash(request, "密码至少 6 位", "error")
            return redirect("/login")
        if password != confirm:
            flash(request, "两次输入的密码不一致", "error")
            return redirect("/login")
        bootstrap_admin_password(password, username=username)
        flash(request, "管理员已创建，请登录", "success")
        return redirect("/login")

    @app.post("/logout")
    async def logout_action(request: Request):
        clear_session(request)
        return redirect("/login")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        refs = principal_account_refs(request)
        context = {
            "send_console": get_send_console_snapshot(account_refs=refs),
            "schedule": get_schedule_snapshot(),
            "accounts": scoped_accounts(request),
            "config": get_config(),
            "web_users": get_web_users() if is_admin(request) else [],
            "flash": pop_flash(request),
        }
        return render_template(request, "dashboard.html", context)

    @app.get("/ops/send-console", response_class=HTMLResponse)
    async def send_console_page(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        refs = principal_account_refs(request)
        return render_template(
            request,
            "send_console.html",
            {"send_console": get_send_console_snapshot(account_refs=refs), "flash": pop_flash(request)},
        )

    @app.get("/ops/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        return render_template(request, "logs.html", {"log_tail": read_log_tail(200), "flash": pop_flash(request)})

    @app.get("/api/ops/overview")
    async def api_ops_overview(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        return JSONResponse(get_overview_snapshot(account_refs=principal_account_refs(request)))

    @app.get("/api/accounts/{unique_id}/friends")
    async def api_account_friends(request: Request, unique_id: str):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        _, account, error = account_for_request(request, unique_id)
        if error:
            return error
        client = accounts_module.onebot_client_for(account)
        try:
            friends = await client.get_friend_list()
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        finally:
            await client.close()
        return JSONResponse({"ok": True, "friends": friends})

    @app.post("/accounts/add")
    async def add_account(request: Request):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        username = str(form.get("username") or "").strip()
        service = str(form.get("service") or "napcat-1").strip() or "napcat-1"
        targets = extract_targets_from_form(form)
        account = accounts_module.add_account(
            username or None,
            service=service,
            access_token=str(os.getenv("ONEBOT_ACCESS_TOKEN") or ""),
            targets=targets,
        )
        flash(request, f"已添加账号 {account['username']}", "success")
        return redirect("/#account-management")

    @app.post("/accounts/{unique_id}/update")
    async def update_account(request: Request, unique_id: str):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        _, account, error = account_for_request(request, unique_id)
        if error:
            return error
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        onebot = dict(account.get("onebot") or {})
        service = str(form.get("service") or onebot.get("service") or "napcat-1").strip() or "napcat-1"
        onebot.update(
            {
                "service": service,
                "http_url": f"http://{service}:3000",
                "ws_url": f"ws://{service}:3001",
            }
        )
        accounts_module.update_account(
            unique_id,
            username=str(form.get("username") or "").strip() or account.get("username"),
            enabled=_form_bool(form, "enabled"),
            onebot=onebot,
            targets=extract_targets_from_form(form),
        )
        flash(request, "账号已更新", "success")
        return redirect("/#account-management")

    @app.post("/accounts/{unique_id}/delete")
    async def delete_account(request: Request, unique_id: str):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        accounts, account, error = account_for_request(request, unique_id)
        if error:
            return error
        refs = [account.get("account_ref")]
        accounts_module.delete_account(unique_id)
        remove_account_refs_from_users(refs)
        flash(request, "账号已删除", "success")
        return redirect("/#account-management")

    @app.post("/accounts/{unique_id}/refresh-friends")
    async def refresh_friends(request: Request, unique_id: str):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        _, account, error = account_for_request(request, unique_id)
        if error:
            return error
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        result = await accounts_module.validate_targets(account)
        if result.get("unavailable"):
            flash(request, "无法拉取好友列表（QQ 可能掉线）", "error")
        else:
            not_friends = [t.get("user_id") for t in result.get("targets", []) if not t.get("isFriend")]
            flash(request, f"已校验好友关系，{len(result.get('friendIds', []))} 位好友；非好友：{', '.join(not_friends) or '无'}", "success")
        return redirect("/#account-management")

    @app.post("/settings/runtime")
    async def save_runtime_config(request: Request):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)

        config = get_config(force_reload=True)
        strategy = config.setdefault("sendStrategy", {})
        strategy["messageVariants"] = _dedupe(str(form.get("messageVariants") or "").splitlines())
        for key in ("messageIntervalSecondsMin", "messageIntervalSecondsMax", "accountStartDelaySecondsMin", "accountStartDelaySecondsMax"):
            try:
                strategy[key] = max(0, int(form.get(key) or strategy.get(key, 0)))
            except ValueError:
                pass
        hitokoto_types = _dedupe(str(form.get("hitokotoTypes") or "").replace(",", "\n").splitlines())
        if hitokoto_types:
            config["hitokotoTypes"] = hitokoto_types
        config.setdefault("imageMode", {})
        config["imageMode"]["enabled"] = _form_bool(form, "imageModeEnabled")
        config["imageMode"]["images"] = _dedupe(str(form.get("imageModeImages") or "").splitlines())
        config["dailySendTime"] = str(form.get("dailySendTime") or config.get("dailySendTime") or "10:00")
        try:
            config["dailySendJitterMinutes"] = max(0, int(form.get("dailySendJitterMinutes") or 0))
        except ValueError:
            pass
        config.setdefault("happyNewYear", {})["enabled"] = _form_bool(form, "happyNewYearEnabled")
        save_config(config)
        try:
            persist_schedule_config(config["dailySendTime"])
        except ValueError as exc:
            flash(request, f"配置已保存，但发送时刻无效：{exc}", "warning")
            return redirect("/#config-panel")
        flash(request, "运行配置已保存", "success")
        return redirect("/#config-panel")

    @app.post("/admin/change-password")
    async def change_admin_password(request: Request):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        current = str(form.get("current_password") or "")
        new_password = str(form.get("new_password") or "")
        settings = get_app_settings(force_reload=True)
        if not verify_password(current, settings.get("admin_password_hash")):
            flash(request, "当前密码错误", "error")
            return redirect("/#settings-panel")
        if len(new_password) < 6:
            flash(request, "新密码至少 6 位", "error")
            return redirect("/#settings-panel")
        update_admin_password(new_password)
        flash(request, "管理员密码已更新", "success")
        return redirect("/#settings-panel")

    @app.post("/admin/users")
    async def create_user(request: Request):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        refs = _dedupe(str(form.get("account_refs") or "").replace(",", "\n").splitlines())
        try:
            create_web_user(username, password, account_refs=refs)
        except UserStoreError as exc:
            flash(request, str(exc), "error")
            return redirect("/#settings-panel")
        flash(request, f"已创建用户 {username}", "success")
        return redirect("/#settings-panel")

    @app.post("/admin/users/{username}/delete")
    async def delete_user(request: Request, username: str):
        maybe_redirect = require_admin(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        if str(username).casefold() == str(get_app_settings().get("admin_username") or "admin").casefold():
            flash(request, "不能删除管理员账号", "error")
            return redirect("/#settings-panel")
        delete_web_user(username)
        flash(request, f"已删除用户 {username}", "success")
        return redirect("/#settings-panel")

    @app.post("/ops/run-now")
    async def ops_run_now(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        result = run_task_now(force_all=True, account_refs=principal_account_refs(request))
        flash(request, f"任务已启动（pid={result['pid']}），实时日志见运行日志页", "success")
        return redirect("/ops/send-console")

    @app.post("/ops/run-failed-retry")
    async def ops_run_failed_retry(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        result = run_failed_retry_now(account_refs=principal_account_refs(request))
        flash(request, f"失败重发已启动（pid={result['pid']}）", "success")
        return redirect("/ops/send-console")

    @app.post("/ops/run-unsent-retry")
    async def ops_run_unsent_retry(request: Request):
        maybe_redirect = require_user(request)
        if maybe_redirect:
            return maybe_redirect
        form = await request.form()
        if not validate_csrf(request, form.get("csrf_token") or ""):
            return PlainTextResponse("Invalid CSRF token", status_code=403)
        result = run_unsent_retry_now(account_refs=principal_account_refs(request))
        flash(request, f"补发任务已启动（pid={result['pid']}）", "success")
        return redirect("/ops/send-console")

    return app


def verify_login(username, password):
    from webui.users import authenticate, find_web_user

    if not is_bootstrapped():
        return None
    user = authenticate(username, password)
    if user:
        return user
    # Fall back to the bootstrap admin account stored in app settings.
    settings = get_app_settings(force_reload=True)
    admin_username = str(settings.get("admin_username") or "admin").strip() or "admin"
    if str(username).casefold() == admin_username.casefold() and verify_password(password, settings.get("admin_password_hash")):
        return {"username": admin_username, "role": "admin", "account_refs": [], "enabled": True}
    return None


app = create_app()


def run_web_app(host=None, port=None):
    settings = get_app_settings()
    host = host or settings.get("ui_host") or "0.0.0.0"
    port = port or settings.get("ui_port") or 8787
    uvicorn.run(app, host=host, port=int(port), log_level="info")
