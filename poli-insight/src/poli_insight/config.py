from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_SOURCE_ROOT = PROJECT_ROOT / "scenarios"
DEFAULT_SCENARIO_TEMPLATE_DIRECTORY = "_template"


class SettingsError(ValueError):
    """Raised when application configuration cannot be safely resolved."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    app_timezone: str
    scenario_source_root: Path | str = DEFAULT_SCENARIO_SOURCE_ROOT
    scenario_template_directory: Path | str | None = (
        DEFAULT_SCENARIO_TEMPLATE_DIRECTORY
    )

    @classmethod
    def from_environment(cls) -> "Settings":
        template_value = os.getenv(
            "SCENARIO_TEMPLATE_DIRECTORY",
            DEFAULT_SCENARIO_TEMPLATE_DIRECTORY,
        ).strip()
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "sqlite+pysqlite:///database/poli-insight.sqlite",
            ),
            app_timezone=os.getenv("APP_TIMEZONE", "America/Los_Angeles"),
            scenario_source_root=os.getenv(
                "SCENARIO_SOURCE_ROOT",
                str(DEFAULT_SCENARIO_SOURCE_ROOT),
            ),
            scenario_template_directory=template_value or None,
        )


@dataclass(frozen=True, slots=True)
class ResolvedScenarioPaths:
    source_root: Path
    template_directory: Path | None


def resolve_scenario_paths(settings: Settings) -> ResolvedScenarioPaths:
    """Resolve and validate read-only scenario paths during app startup."""

    root = _resolve_source_root(settings.scenario_source_root)
    return ResolvedScenarioPaths(
        source_root=root,
        template_directory=_resolve_template_directory(
            root,
            settings.scenario_template_directory,
        ),
    )


def _resolve_source_root(value: Path | str) -> Path:
    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raw_path = PROJECT_ROOT / raw_path
    try:
        resolved = raw_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SettingsError(
            "The configured scenario source root is unavailable."
        ) from error
    if not resolved.is_dir():
        raise SettingsError(
            "The configured scenario source root must be a directory."
        )
    return resolved


def _resolve_template_directory(
    root: Path,
    value: Path | str | None,
) -> Path | None:
    if value is None:
        return None
    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raw_path = root / raw_path
    try:
        resolved = raw_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SettingsError(
            "The configured scenario template directory is unavailable."
        ) from error
    if not resolved.is_dir() or not resolved.is_relative_to(root):
        raise SettingsError(
            "The scenario template directory must be inside the scenario "
            "source root."
        )
    return resolved
