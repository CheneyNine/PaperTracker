"""Command runner for coordinating CLI execution.

Manages component lifecycle, resource cleanup, logging configuration,
and error handling for command execution.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import click

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.cli.commands import SearchCommand
from PaperTracker.config import AppConfig, load_config_with_defaults
from PaperTracker.dashboard import run_dashboard_server
from PaperTracker.dashboard.query_config import DashboardQueryConfig
from PaperTracker.dashboard.settings_config import DashboardSettingsConfig
from PaperTracker.llm import create_llm_service
from PaperTracker.renderers import create_output_writer
from PaperTracker.services import create_search_service
from PaperTracker.storage import DashboardStore, create_llm_store, create_storage
from PaperTracker.utils.log import configure_logging, log


class CommandRunner:
    """Orchestrates command execution with proper resource management.

    Handles logging configuration, component creation, database context
    management, and error handling for CLI commands.
    """

    def __init__(self, config: AppConfig, *, config_path: Path | None = None) -> None:
        """Initialize command runner.

        Args:
            config: Application configuration.
        """
        self.config = config
        self.config_path = config_path

    def run_search(self, action: str) -> None:
        """Execute search command with full resource management.

        Configures logging, creates components, executes search,
        and ensures proper cleanup of database connections.

        Args:
            action: The CLI command name (e.g., 'search').

        Raises:
            click.Abort: When the search fails.
        """
        configure_logging(
            level=self.config.runtime.level,
            action=action,
            log_to_file=self.config.runtime.to_file,
            log_dir=self.config.runtime.dir,
        )
        search_service = None
        try:
            # Create storage components
            db_manager, dedup_store, content_store = create_storage(self.config)

            # Create service and output writer (pass dedup_store for arXiv multi-round fetching)
            search_service = create_search_service(self.config, dedup_store=dedup_store)
            output_writer = create_output_writer(self.config)

            # Create LLM service if enabled
            llm_service = create_llm_service(self.config)

            # Create LLM store only when content persistence is enabled.
            llm_store = None
            if db_manager and llm_service and self.config.storage.content_storage_enabled:
                llm_store = create_llm_store(db_manager, self.config)

            # Create command with dependencies injected
            command = SearchCommand(
                config=self.config,
                search_service=search_service,
                dedup_store=dedup_store,
                content_store=content_store,
                output_writer=output_writer,
                llm_service=llm_service,
                llm_store=llm_store,
                progress_callback=None,
            )

            # Execute with proper resource cleanup
            if db_manager:
                with db_manager:
                    command.execute()
                    output_writer.finalize(action)
            else:
                command.execute()
                output_writer.finalize(action)

        except Exception as e:  # noqa: BLE001 - cli boundary
            log.error("Search failed: %s", e)
            raise click.Abort from e
        finally:
            close_func = getattr(search_service, "close", None)
            if callable(close_func):
                try:
                    close_func()
                except Exception as e:  # noqa: BLE001 - cli boundary
                    log.warning("Search service close failed at CLI boundary: %s", e)

    def run_dashboard(self, action: str) -> None:
        """Run the local dynamic dashboard server."""
        if not self.config.storage.enabled or not self.config.storage.content_storage_enabled:
            raise click.ClickException(
                "Dashboard requires storage.enabled=true and storage.content_storage_enabled=true"
            )

        configure_logging(
            level=self.config.runtime.level,
            action=action,
            log_to_file=self.config.runtime.to_file,
            log_dir=self.config.runtime.dir,
        )

        try:
            db_manager, _, _ = create_storage(self.config)
            if db_manager is None:
                raise click.ClickException("Dashboard storage is unavailable")
            with db_manager:
                click.echo(
                    f"Dashboard running at http://{self.config.dashboard.host}:{self.config.dashboard.port}"
                )
                if self.config_path is None:
                    raise click.ClickException("Dashboard requires a config path")
                dashboard_store = DashboardStore(db_manager)
                run_dashboard_server(
                    self.config.dashboard,
                    dashboard_store,
                    query_config=DashboardQueryConfig(self.config_path),
                    settings_config=DashboardSettingsConfig(self.config_path),
                    ccf_store=CCFVenueStore(Path(self.config.search.ccf_cache_path)),
                    refresh_callback=lambda progress_callback, theme_id, source_names: self._refresh_dashboard_data(
                        progress_callback=progress_callback,
                        theme_id=theme_id,
                        source_names=source_names,
                    ),
                    suggest_queries_callback=lambda theme_id: self._suggest_theme_queries(
                        theme_id=theme_id,
                        dashboard_store=dashboard_store,
                        llm_service=create_llm_service(self._load_runtime_config()),
                    ),
                )
        except KeyboardInterrupt:
            log.info("Dashboard stopped by user")
        except Exception as e:  # noqa: BLE001 - cli boundary
            log.error("Dashboard failed: %s", e)
            raise click.Abort from e

    def _refresh_dashboard_data(
        self,
        *,
        progress_callback,
        theme_id: int | None,
        source_names: tuple[str, ...] | None,
    ) -> None:
        """Refresh dashboard data by running search and backfilling missing translations."""
        search_service = None
        try:
            refresh_config = self._load_runtime_config()
            thread_db_manager, dedup_store, content_store = create_storage(refresh_config)
            if thread_db_manager is None:
                raise click.ClickException("Dashboard refresh storage is unavailable")
            thread_dashboard_store = DashboardStore(thread_db_manager)
            selected_query_labels: tuple[str, ...] = ()
            selected_theme = None
            if theme_id is not None:
                selected_theme = thread_dashboard_store.get_research_theme(theme_id)
                selected_query_labels = tuple(thread_dashboard_store.list_theme_query_labels(theme_id))
                if selected_theme is None:
                    raise click.ClickException("Selected research theme was not found")
                normalized_labels = {label.casefold() for label in selected_query_labels}
                filtered_queries = tuple(
                    query
                    for query in refresh_config.search.queries
                    if query.name and query.name.casefold() in normalized_labels
                )
                refresh_config = replace(
                    refresh_config,
                    search=replace(refresh_config.search, queries=filtered_queries),
                )
            if source_names:
                allowed_sources = set(source_names)
                normalized_sources = tuple(
                    source
                    for source in refresh_config.search.sources
                    if source in allowed_sources
                )
                if not normalized_sources:
                    raise click.ClickException("Selected search sources are unavailable")
                refresh_config = replace(
                    refresh_config,
                    search=replace(refresh_config.search, sources=normalized_sources),
                )
            search_service = create_search_service(
                refresh_config,
                dedup_store=dedup_store,
                progress_callback=progress_callback,
            )
            output_writer = create_output_writer(refresh_config)
            llm_service = create_llm_service(refresh_config)
            llm_store = None
            if llm_service and refresh_config.storage.content_storage_enabled:
                llm_store = create_llm_store(thread_db_manager, refresh_config)

            command = SearchCommand(
                config=refresh_config,
                search_service=search_service,
                dedup_store=dedup_store,
                content_store=content_store,
                output_writer=output_writer,
                llm_service=llm_service,
                llm_store=llm_store,
                progress_callback=progress_callback,
            )
            command.execute()
            output_writer.finalize("search")

            if llm_service and llm_store:
                missing_enrichment_papers = thread_dashboard_store.list_active_papers_missing_enrichment(
                    require_translation=refresh_config.llm.enable_translation,
                    require_summary=refresh_config.llm.enable_summary,
                )
                if missing_enrichment_papers:
                    infos = llm_service.generate_batch(missing_enrichment_papers)
                    if infos:
                        llm_store.save(infos)
                if selected_theme is not None:
                    themes = [selected_theme]
                else:
                    themes = [theme for theme in thread_dashboard_store.list_research_themes() if theme.is_active]
                for index, theme in enumerate(themes, start=1):
                    progress_callback(
                        "theme_started",
                        {
                            "theme_name": theme.name,
                            "theme_index": index,
                            "theme_total": len(themes),
                        },
                    )
                    missing_theme_papers = thread_dashboard_store.list_active_papers_missing_theme_contribution(
                        theme.id,
                        query_labels=tuple(thread_dashboard_store.list_theme_query_labels(theme.id)),
                    )
                    if not missing_theme_papers:
                        continue
                    theme_infos = llm_service.generate_theme_contribution_batch(
                        missing_theme_papers,
                        theme_name=theme.name,
                        theme_description=theme.description,
                    )
                    thread_dashboard_store.save_theme_contributions(
                        theme_id=theme.id,
                        provider=refresh_config.llm.provider,
                        model=refresh_config.llm.model,
                        infos=theme_infos,
                    )
        finally:
            close_func = getattr(search_service, "close", None)
            if callable(close_func):
                close_func()

    def _load_runtime_config(self) -> AppConfig:
        """Reload the config file so dashboard changes take effect on next refresh."""
        if self.config_path is None:
            return self.config
        return load_config_with_defaults(self.config_path)

    def _suggest_theme_queries(
        self,
        *,
        theme_id: int,
        dashboard_store: DashboardStore,
        llm_service,
    ) -> list[str]:
        """Generate AI keyword suggestions for one research theme."""
        if llm_service is None:
            raise click.ClickException("LLM is not available for keyword suggestions")
        theme = dashboard_store.get_research_theme(theme_id)
        if theme is None:
            raise click.ClickException("Selected research theme was not found")
        return llm_service.generate_theme_query_suggestions(
            theme_name=theme.name,
            theme_description=theme.description,
        )
