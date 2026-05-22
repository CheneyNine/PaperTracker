"""Dashboard HTTP server.

Serves a local dynamic HTML dashboard backed by SQLite data and archive actions.
"""

from __future__ import annotations

import importlib.resources
import json
import threading
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests

from PaperTracker.dashboard.llm_discovery import discover_llm_provider_and_models
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.ccf import CCFVenueStore
    from PaperTracker.config import DashboardConfig
    from PaperTracker.dashboard.query_config import DashboardQueryConfig
    from PaperTracker.dashboard.settings_config import DashboardSettingsConfig
    from PaperTracker.storage.dashboard import DashboardStore


def run_dashboard_server(
    config: DashboardConfig,
    store: DashboardStore,
    *,
    query_config: DashboardQueryConfig,
    settings_config: DashboardSettingsConfig,
    ccf_store: CCFVenueStore,
    refresh_callback: Callable[
        [Callable[[str, dict[str, object]], None], int | None, tuple[str, ...] | None],
        None,
    ] | None = None,
    suggest_queries_callback: Callable[[int], dict] | None = None,
) -> None:
    """Start the local dashboard HTTP server.

    Args:
        config: Dashboard server settings.
        store: Dashboard-backed SQLite query store.
    """
    server = HTTPServer(
        (config.host, config.port),
        _build_handler(
            config,
            store,
            query_config=query_config,
            settings_config=settings_config,
            ccf_store=ccf_store,
            refresh_callback=refresh_callback,
            suggest_queries_callback=suggest_queries_callback,
        ),
    )
    log.info("Dashboard available at http://%s:%d", config.host, config.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _build_handler(
    config: DashboardConfig,
    store: DashboardStore,
    *,
    query_config: DashboardQueryConfig,
    settings_config: DashboardSettingsConfig,
    ccf_store: CCFVenueStore,
    refresh_callback: Callable[
        [Callable[[str, dict[str, object]], None], int | None, tuple[str, ...] | None],
        None,
    ] | None,
    suggest_queries_callback: Callable[[int], dict] | None,
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to config and store."""
    refresh_lock = threading.Lock()
    refresh_state: dict[str, Any] = {
        "running": False,
        "last_started_at": None,
        "last_finished_at": None,
        "last_error": None,
        "message": None,
        "progress_percent": 0,
        "query_index": None,
        "query_total": None,
        "source": None,
        "selected_sources": settings_config.list_configured_sources(),
    }

    def _build_refresh_payload() -> dict[str, Any]:
        """Build refresh status payload."""
        return {
            "running": bool(refresh_state["running"]),
            "last_started_at": refresh_state["last_started_at"],
            "last_finished_at": refresh_state["last_finished_at"],
            "last_error": refresh_state["last_error"],
            "message": refresh_state["message"],
            "progress_percent": refresh_state["progress_percent"],
            "query_index": refresh_state["query_index"],
            "query_total": refresh_state["query_total"],
            "source": refresh_state["source"],
        }

    def _build_snapshot_payload() -> dict[str, Any]:
        """Build one dashboard response payload."""
        payload = store.get_snapshot()
        configured_sources = settings_config.list_configured_sources()
        payload["query_labels"] = query_config.list_labels()
        payload["available_refresh_sources"] = list(configured_sources)
        payload["default_refresh_sources"] = list(configured_sources)
        payload.update(ccf_store.get_status())
        return payload

    def _build_settings_payload() -> dict[str, Any]:
        """Build settings payload for dashboard settings page."""
        return settings_config.get_settings()

    def _update_refresh_progress(event_type: str, payload: dict[str, object]) -> None:
        """Update in-memory refresh progress snapshot."""
        if event_type == "query_started":
            refresh_state["query_index"] = payload.get("query_index")
            refresh_state["query_total"] = payload.get("query_total")
            refresh_state["message"] = (
                f"准备检索第 {payload.get('query_index')}/{payload.get('query_total')} 个关键词"
            )
            return
        if event_type == "source_started":
            source_name = str(payload.get("source") or "").strip()
            refresh_state["source"] = source_name
            query_index = int(refresh_state["query_index"] or 1)
            query_total = int(refresh_state["query_total"] or 1)
            active_sources = tuple(refresh_state.get("selected_sources") or settings_config.list_configured_sources())
            total_sources = max(len(active_sources), 1)
            source_order = {name: index for index, name in enumerate(active_sources)}
            current_step = (query_index - 1) * total_sources + source_order.get(source_name, total_sources - 1) + 1
            total_steps = max(query_total * total_sources, 1)
            refresh_state["progress_percent"] = min(int(current_step * 100 / total_steps), 95)
            refresh_state["message"] = f"检索 {source_name.upper()} 中，关键词进度 {query_index}/{query_total}"
            return
        if event_type == "llm_started":
            query_index = payload.get("query_index")
            query_total = payload.get("query_total")
            refresh_state["progress_percent"] = 98
            refresh_state["message"] = f"补齐翻译与结构化摘要中，关键词进度 {query_index}/{query_total}"
            return
        if event_type == "theme_started":
            theme_name = str(payload.get("theme_name") or "").strip()
            theme_index = payload.get("theme_index")
            theme_total = payload.get("theme_total")
            progress_suffix = ""
            if theme_index and theme_total:
                progress_suffix = f"（{theme_index}/{theme_total}）"
            refresh_state["progress_percent"] = 99
            refresh_state["message"] = f"正在评估研究主题贡献度：{theme_name or '当前主题'}{progress_suffix}"
            return

    class DashboardHandler(BaseHTTPRequestHandler):
        """Serve the dashboard shell, assets, and JSON APIs."""

        def do_GET(self) -> None:  # noqa: N802 - http handler signature
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._write_html(_render_index_html(config))
                return
            if parsed.path == "/api/papers":
                self._write_json(_build_snapshot_payload())
                return
            if parsed.path == "/api/refresh":
                self._write_json(_build_refresh_payload())
                return
            if parsed.path == "/api/settings":
                self._write_json(_build_settings_payload())
                return
            if parsed.path == "/api/ccf":
                self._write_json(ccf_store.get_status())
                return
            if parsed.path == "/assets/style.css":
                self._write_text(_load_asset_text("style.css"), "text/css; charset=utf-8")
                return
            if parsed.path == "/assets/app.js":
                self._write_text(_load_asset_text("app.js"), "application/javascript; charset=utf-8")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - http handler signature
            parsed = urlparse(self.path)
            if parsed.path == "/api/refresh":
                self._handle_refresh()
                return
            if parsed.path == "/api/queries":
                self._handle_query_update()
                return
            if parsed.path == "/api/queries/suggest":
                self._handle_query_suggestions()
                return
            if parsed.path == "/api/themes":
                self._handle_theme_update()
                return
            if parsed.path == "/api/ccf/update":
                self._handle_ccf_update()
                return
            if parsed.path == "/api/settings":
                self._handle_settings_update()
                return
            if parsed.path == "/api/settings/llm/discover":
                self._handle_llm_discovery()
                return
            if parsed.path != "/api/papers/archive":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            payload = self._read_json_body()
            source = payload.get("source")
            source_id = payload.get("source_id")
            archived = payload.get("archived")
            if not isinstance(source, str) or not source.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "source is required")
                return
            if not isinstance(source_id, str) or not source_id.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "source_id is required")
                return
            if not isinstance(archived, bool):
                self.send_error(HTTPStatus.BAD_REQUEST, "archived must be boolean")
                return

            if archived:
                store.archive_paper(source, source_id)
            else:
                store.restore_paper(source, source_id)
            self._write_json(_build_snapshot_payload())

        def _handle_query_update(self) -> None:
            """Add or delete one configured query."""
            payload = self._read_json_body()
            action = payload.get("action")
            label = payload.get("label")
            theme_id = payload.get("theme_id")
            if not isinstance(action, str) or action not in {"add", "delete"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "action must be add or delete")
                return
            if not isinstance(label, str) or not label.strip():
                self.send_error(HTTPStatus.BAD_REQUEST, "label is required")
                return
            if not isinstance(theme_id, int):
                self.send_error(HTTPStatus.BAD_REQUEST, "theme_id is required")
                return

            if action == "add":
                query_config.add_query(label)
                store.add_theme_query(theme_id, label)
            else:
                store.archive_theme_papers_for_query(theme_id, label)
                store.delete_theme_query(theme_id, label)
            self._write_json(_build_snapshot_payload())

        def _handle_ccf_update(self) -> None:
            """Refresh local CCF whitelist cache from bundled snapshot."""
            status = ccf_store.refresh_cache()
            self._write_json(status)

        def _handle_query_suggestions(self) -> None:
            """Generate and optimize AI keyword suggestions for one research theme."""
            if suggest_queries_callback is None:
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, "query suggestions are unavailable")
                return
            payload = self._read_json_body()
            theme_id = payload.get("theme_id")
            if not isinstance(theme_id, int):
                self.send_error(HTTPStatus.BAD_REQUEST, "theme_id is required")
                return
            try:
                result = suggest_queries_callback(theme_id)
            except Exception as error:
                self._write_json({"error": str(error)}, status=HTTPStatus.BAD_GATEWAY)
                return

            new_queries: list[str] = result.get("new_queries", [])
            optimized_queries: list[dict] = result.get("optimized_queries", [])

            added: list[str] = []
            existing = {label.casefold() for label in query_config.list_labels()}
            for label in new_queries:
                normalized = " ".join(label.split())
                if not normalized or normalized.casefold() in existing:
                    continue
                query_config.add_query(normalized)
                store.add_theme_query(theme_id, normalized)
                existing.add(normalized.casefold())
                added.append(normalized)

            optimized: list[dict[str, str]] = []
            for entry in optimized_queries:
                from_label = " ".join(str(entry.get("from", "")).split())
                to_label = " ".join(str(entry.get("to", "")).split())
                if not from_label or not to_label:
                    continue
                if from_label.casefold() not in existing:
                    continue
                if to_label.casefold() in existing:
                    continue
                query_config.delete_query(from_label)
                store.delete_theme_query(theme_id, from_label)
                existing.discard(from_label.casefold())
                query_config.add_query(to_label)
                store.add_theme_query(theme_id, to_label)
                existing.add(to_label.casefold())
                optimized.append({"from": from_label, "to": to_label})

            self._write_json(
                {
                    "suggested_queries": new_queries,
                    "added_queries": added,
                    "optimized_queries": optimized,
                    "snapshot": _build_snapshot_payload(),
                }
            )

        def _handle_theme_update(self) -> None:
            """Create, activate, or delete one research theme."""
            payload = self._read_json_body()
            action = payload.get("action")
            if not isinstance(action, str) or action not in {"create", "update", "delete"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "action must be create, update, or delete")
                return

            if action == "create":
                name = payload.get("name")
                description = payload.get("description")
                if not isinstance(name, str) or not name.strip():
                    self.send_error(HTTPStatus.BAD_REQUEST, "name is required")
                    return
                if not isinstance(description, str) or not description.strip():
                    self.send_error(HTTPStatus.BAD_REQUEST, "description is required")
                    return
                store.create_research_theme(name, description)
                self._write_json(_build_snapshot_payload())
                return

            theme_id = payload.get("theme_id")
            if not isinstance(theme_id, int):
                self.send_error(HTTPStatus.BAD_REQUEST, "theme_id must be integer")
                return
            if action == "update":
                name = payload.get("name")
                description = payload.get("description")
                if not isinstance(name, str) or not name.strip():
                    self.send_error(HTTPStatus.BAD_REQUEST, "name is required")
                    return
                if not isinstance(description, str) or not description.strip():
                    self.send_error(HTTPStatus.BAD_REQUEST, "description is required")
                    return
                store.update_research_theme(theme_id, name, description)
            else:
                store.delete_research_theme(theme_id)
            self._write_json(_build_snapshot_payload())

        def _handle_refresh(self) -> None:
            """Trigger a live search refresh asynchronously."""
            if refresh_callback is None:
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, "refresh is unavailable")
                return
            payload = self._read_json_body()
            theme_id = payload.get("theme_id")
            configured_sources = settings_config.list_configured_sources()
            selected_sources = _normalize_selected_sources(payload.get("sources"), configured_sources)
            if payload.get("sources") is not None and not selected_sources:
                self.send_error(HTTPStatus.BAD_REQUEST, "sources must include at least one configured source")
                return

            if not refresh_lock.acquire(blocking=False):
                self._write_json(_build_refresh_payload(), status=HTTPStatus.ACCEPTED)
                return
            if theme_id is not None and not isinstance(theme_id, int):
                refresh_lock.release()
                self.send_error(HTTPStatus.BAD_REQUEST, "theme_id must be integer")
                return

            refresh_state["running"] = True
            refresh_state["last_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            refresh_state["last_error"] = None
            refresh_state["message"] = "刷新任务已启动"
            refresh_state["progress_percent"] = 1
            refresh_state["query_index"] = None
            refresh_state["query_total"] = None
            refresh_state["source"] = None
            refresh_state["selected_sources"] = selected_sources or configured_sources

            def _run_refresh() -> None:
                try:
                    refresh_callback(
                        _update_refresh_progress,
                        theme_id if isinstance(theme_id, int) else None,
                        selected_sources,
                    )
                except Exception as exc:  # noqa: BLE001 - background task boundary
                    log.warning("Dashboard refresh failed: %s", exc)
                    refresh_state["last_error"] = str(exc)
                finally:
                    refresh_state["running"] = False
                    refresh_state["last_finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if refresh_state["last_error"] is None:
                        refresh_state["progress_percent"] = 100
                        refresh_state["message"] = "刷新完成"
                    refresh_lock.release()

            thread = threading.Thread(target=_run_refresh, name="paper-tracker-dashboard-refresh", daemon=True)
            thread.start()
            self._write_json(_build_refresh_payload(), status=HTTPStatus.ACCEPTED)

        def _handle_settings_update(self) -> None:
            """Persist settings from the dashboard settings page."""
            payload = self._read_json_body()
            try:
                settings = settings_config.save_settings(payload)
            except ValueError as error:
                self.send_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            response = {
                "settings": settings,
                "snapshot": _build_snapshot_payload(),
            }
            self._write_json(response)

        def _handle_llm_discovery(self) -> None:
            """Detect LLM provider compatibility and available models."""
            payload = self._read_json_body()
            base_url = str(payload.get("base_url", "") or "").strip()
            api_key = str(payload.get("api_key", "") or "").strip()
            if not base_url:
                self._write_json({"error": "请填写 Base URL"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not api_key:
                self._write_json({"error": "请填写 API Key"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                result = discover_llm_provider_and_models(base_url=base_url, api_key=api_key)
            except requests.exceptions.HTTPError as error:
                status_code = error.response.status_code if error.response is not None else "?"
                try:
                    body = error.response.json() if error.response is not None else {}
                    detail = body.get("error", {})
                    msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
                except Exception:
                    msg = ""
                self._write_json(
                    {"error": f"接口返回 HTTP {status_code}{': ' + msg if msg else ''}"},
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            except (requests.RequestException, OSError) as error:
                self._write_json(
                    {"error": f"连接失败：{error}"},
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            self._write_json(
                {
                    "provider": result.provider,
                    "models": list(result.models),
                }
            )

        def log_message(self, format: str, *args: Any) -> None:
            """Route HTTP logs through project logging."""
            log.debug("Dashboard HTTP: " + format, *args)

        def _read_json_body(self) -> dict[str, Any]:
            """Read and decode request JSON body."""
            length_header = self.headers.get("Content-Length", "0").strip()
            try:
                length = int(length_header)
            except ValueError:
                return {}
            body = self.rfile.read(max(length, 0))
            if not body:
                return {}
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return dict(data) if isinstance(data, dict) else {}

        def _write_html(self, content: str) -> None:
            """Send HTML response."""
            self._write_text(content, "text/html; charset=utf-8")

        def _write_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            """Send JSON response."""
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _write_text(self, content: str, content_type: str) -> None:
            """Send plain text-based response."""
            encoded = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return DashboardHandler


def _render_index_html(config: DashboardConfig) -> str:
    """Render the dashboard shell HTML with runtime config injected."""
    template = _load_asset_text("index.html")
    runtime = json.dumps(
        {
            "autoRefreshSeconds": config.auto_refresh_seconds,
        },
        ensure_ascii=False,
    )
    return template.replace("__DASHBOARD_CONFIG__", runtime)


def _normalize_selected_sources(value: object, allowed_sources: tuple[str, ...]) -> tuple[str, ...] | None:
    """Normalize one refresh request source list against configured sources."""
    if value is None:
        return None
    if not isinstance(value, list):
        return ()
    allowed = {source.strip().lower() for source in allowed_sources if source.strip()}
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        source_name = item.strip().lower()
        if not source_name or source_name not in allowed or source_name in seen:
            continue
        seen.add(source_name)
        normalized.append(source_name)
    return tuple(normalized)


def _load_asset_text(filename: str) -> str:
    """Load dashboard asset text from package resources."""
    package = importlib.resources.files("PaperTracker.dashboard.assets")
    return (package / filename).read_text(encoding="utf-8")
