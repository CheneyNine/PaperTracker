"""Dashboard HTTP server (FastAPI + uvicorn).

All API endpoint paths, HTTP methods, and JSON response shapes are preserved
from the original HTTPServer implementation.
"""

from __future__ import annotations

import importlib.resources
import json
import threading
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

import requests
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from PaperTracker.dashboard.llm_discovery import discover_llm_provider_and_models
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.ccf import CCFVenueStore
    from PaperTracker.config import DashboardConfig
    from PaperTracker.dashboard.query_config import DashboardQueryConfig
    from PaperTracker.dashboard.settings_config import DashboardSettingsConfig
    from PaperTracker.storage.dashboard import DashboardStore


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class ArchiveRequest(BaseModel):
    source: str
    source_id: str
    archived: bool


class RefreshRequest(BaseModel):
    theme_id: int | None = None
    sources: list[str] | None = None


class QueryRequest(BaseModel):
    action: str
    label: str
    theme_id: int


class QuerySuggestRequest(BaseModel):
    theme_id: int


class ThemeRequest(BaseModel):
    action: str
    theme_id: int | None = None
    name: str | None = None
    description: str | None = None


class LLMDiscoverRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


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
    """Start the local dashboard HTTP server."""
    import uvicorn

    app = create_dashboard_app(
        config,
        store,
        query_config=query_config,
        settings_config=settings_config,
        ccf_store=ccf_store,
        refresh_callback=refresh_callback,
        suggest_queries_callback=suggest_queries_callback,
    )
    log.info("Dashboard available at http://%s:%d", config.host, config.port)
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")


def create_dashboard_app(
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
) -> FastAPI:
    """Build a configured FastAPI application."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

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

    # ------------------------------------------------------------------
    # Internal payload builders (shared by multiple routes)
    # ------------------------------------------------------------------

    def _build_refresh_payload() -> dict[str, Any]:
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
        payload = store.get_snapshot()
        configured_sources = settings_config.list_configured_sources()
        payload["query_labels"] = query_config.list_labels()
        payload["available_refresh_sources"] = list(configured_sources)
        payload["default_refresh_sources"] = list(configured_sources)
        payload.update(ccf_store.get_status())
        return payload

    def _update_refresh_progress(event_type: str, payload: dict[str, object]) -> None:
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
            progress_suffix = f"（{theme_index}/{theme_total}）" if theme_index and theme_total else ""
            refresh_state["progress_percent"] = 99
            refresh_state["message"] = f"正在评估研究主题贡献度：{theme_name or '当前主题'}{progress_suffix}"
            return

    # ------------------------------------------------------------------
    # GET routes
    # ------------------------------------------------------------------

    @app.get("/")
    def get_index() -> HTMLResponse:
        return HTMLResponse(_render_index_html(config))

    @app.get("/api/papers")
    def get_papers() -> JSONResponse:
        return JSONResponse(_build_snapshot_payload())

    @app.get("/api/refresh")
    def get_refresh() -> JSONResponse:
        return JSONResponse(_build_refresh_payload())

    @app.get("/api/settings")
    def get_settings() -> JSONResponse:
        return JSONResponse(settings_config.get_settings())

    @app.get("/api/ccf")
    def get_ccf() -> JSONResponse:
        return JSONResponse(ccf_store.get_status())

    @app.get("/assets/style.css")
    def get_style() -> Response:
        return Response(
            content=_load_asset_text("style.css"),
            media_type="text/css; charset=utf-8",
        )

    @app.get("/assets/app.js")
    def get_app_js() -> Response:
        return Response(
            content=_load_asset_text("app.js"),
            media_type="application/javascript; charset=utf-8",
        )

    @app.get("/assets/vue.global.prod.js")
    def get_vue_js() -> Response:
        return Response(
            content=_load_asset_text("vue.global.prod.js"),
            media_type="application/javascript; charset=utf-8",
        )

    @app.get("/assets/app.vue.js")
    def get_app_vue_js() -> Response:
        return Response(
            content=_load_asset_text("app.vue.js"),
            media_type="application/javascript; charset=utf-8",
        )

    # ------------------------------------------------------------------
    # POST routes
    # ------------------------------------------------------------------

    @app.post("/api/papers/archive")
    def post_archive(req: ArchiveRequest) -> JSONResponse:
        if not req.source.strip():
            raise HTTPException(status_code=400, detail="source is required")
        if not req.source_id.strip():
            raise HTTPException(status_code=400, detail="source_id is required")
        if req.archived:
            store.archive_paper(req.source, req.source_id)
        else:
            store.restore_paper(req.source, req.source_id)
        return JSONResponse(_build_snapshot_payload())

    @app.post("/api/refresh")
    def post_refresh(req: RefreshRequest = Body(default_factory=RefreshRequest)) -> JSONResponse:
        if refresh_callback is None:
            raise HTTPException(status_code=501, detail="refresh is unavailable")

        configured_sources = settings_config.list_configured_sources()
        selected_sources = _normalize_selected_sources(req.sources, configured_sources)
        if req.sources is not None and not selected_sources:
            raise HTTPException(
                status_code=400,
                detail="sources must include at least one configured source",
            )

        if not refresh_lock.acquire(blocking=False):
            return JSONResponse(_build_refresh_payload(), status_code=202)

        theme_id = req.theme_id
        if theme_id is not None and not isinstance(theme_id, int):
            refresh_lock.release()
            raise HTTPException(status_code=400, detail="theme_id must be integer")

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
            except Exception as exc:
                log.warning("Dashboard refresh failed: %s", exc)
                refresh_state["last_error"] = str(exc)
            finally:
                refresh_state["running"] = False
                refresh_state["last_finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if refresh_state["last_error"] is None:
                    refresh_state["progress_percent"] = 100
                    refresh_state["message"] = "刷新完成"
                refresh_lock.release()

        thread = threading.Thread(
            target=_run_refresh,
            name="paper-tracker-dashboard-refresh",
            daemon=True,
        )
        thread.start()
        return JSONResponse(_build_refresh_payload(), status_code=202)

    @app.post("/api/queries")
    def post_queries(req: QueryRequest) -> JSONResponse:
        if req.action not in {"add", "delete"}:
            raise HTTPException(status_code=400, detail="action must be add or delete")
        if not req.label.strip():
            raise HTTPException(status_code=400, detail="label is required")

        if req.action == "add":
            query_config.add_query(req.label)
            store.add_theme_query(req.theme_id, req.label)
        else:
            store.archive_theme_papers_for_query(req.theme_id, req.label)
            store.delete_theme_query(req.theme_id, req.label)
        return JSONResponse(_build_snapshot_payload())

    @app.post("/api/queries/suggest")
    def post_queries_suggest(req: QuerySuggestRequest) -> JSONResponse:
        if suggest_queries_callback is None:
            raise HTTPException(status_code=501, detail="query suggestions are unavailable")

        try:
            result = suggest_queries_callback(req.theme_id)
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=502)

        new_queries: list[str] = result.get("new_queries", [])
        optimized_queries: list[dict] = result.get("optimized_queries", [])

        added: list[str] = []
        existing = {label.casefold() for label in query_config.list_labels()}
        for label in new_queries:
            normalized = " ".join(label.split())
            if not normalized or normalized.casefold() in existing:
                continue
            query_config.add_query(normalized)
            store.add_theme_query(req.theme_id, normalized)
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
            store.delete_theme_query(req.theme_id, from_label)
            existing.discard(from_label.casefold())
            query_config.add_query(to_label)
            store.add_theme_query(req.theme_id, to_label)
            existing.add(to_label.casefold())
            optimized.append({"from": from_label, "to": to_label})

        return JSONResponse(
            {
                "suggested_queries": new_queries,
                "added_queries": added,
                "optimized_queries": optimized,
                "snapshot": _build_snapshot_payload(),
            }
        )

    @app.post("/api/themes")
    def post_themes(req: ThemeRequest) -> JSONResponse:
        if req.action not in {"create", "update", "delete"}:
            raise HTTPException(status_code=400, detail="action must be create, update, or delete")

        if req.action == "create":
            if not req.name or not req.name.strip():
                raise HTTPException(status_code=400, detail="name is required")
            if not req.description or not req.description.strip():
                raise HTTPException(status_code=400, detail="description is required")
            store.create_research_theme(req.name, req.description)
            return JSONResponse(_build_snapshot_payload())

        if req.theme_id is None:
            raise HTTPException(status_code=400, detail="theme_id must be integer")

        if req.action == "update":
            if not req.name or not req.name.strip():
                raise HTTPException(status_code=400, detail="name is required")
            if not req.description or not req.description.strip():
                raise HTTPException(status_code=400, detail="description is required")
            store.update_research_theme(req.theme_id, req.name, req.description)
        else:
            store.delete_research_theme(req.theme_id)
        return JSONResponse(_build_snapshot_payload())

    @app.post("/api/ccf/update")
    def post_ccf_update() -> JSONResponse:
        status = ccf_store.refresh_cache()
        return JSONResponse(status)

    @app.post("/api/settings")
    def post_settings(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        try:
            settings = settings_config.save_settings(payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        return JSONResponse({"settings": settings, "snapshot": _build_snapshot_payload()})

    @app.post("/api/settings/llm/discover")
    def post_llm_discover(req: LLMDiscoverRequest) -> JSONResponse:
        base_url = req.base_url.strip()
        api_key = req.api_key.strip()
        if not base_url:
            return JSONResponse({"error": "请填写 Base URL"}, status_code=400)
        if not api_key:
            return JSONResponse({"error": "请填写 API Key"}, status_code=400)
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
            return JSONResponse(
                {"error": f"接口返回 HTTP {status_code}{': ' + msg if msg else ''}"},
                status_code=502,
            )
        except (requests.RequestException, OSError) as error:
            return JSONResponse({"error": f"连接失败：{error}"}, status_code=502)
        return JSONResponse({"provider": result.provider, "models": list(result.models)})

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_index_html(config: DashboardConfig) -> str:
    """Render the dashboard shell HTML with runtime config injected."""
    template = _load_asset_text("index.html")
    runtime = json.dumps(
        {"autoRefreshSeconds": config.auto_refresh_seconds},
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
