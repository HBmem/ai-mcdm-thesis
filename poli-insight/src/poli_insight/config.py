from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_SOURCE_ROOT = PROJECT_ROOT / "scenarios"
DEFAULT_SCENARIO_TEMPLATE_DIRECTORY = "_template"


class SettingsError(ValueError):
    """Raised when application configuration cannot be safely resolved."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    app_timezone: str
    public_base_url: str = "http://localhost:8501"
    app_environment: str = "development"
    scenario_source_root: Path | str = DEFAULT_SCENARIO_SOURCE_ROOT
    scenario_template_directory: Path | str | None = (
        DEFAULT_SCENARIO_TEMPLATE_DIRECTORY
    )
    participant_import_hmac_secret: str = field(
        default="development-only-participant-import-secret-change-me",
        repr=False,
    )
    participant_identity_encryption_key: str = field(
        default="development-only-participant-identity-key-change-me",
        repr=False,
    )
    imported_identity_retention_days: int = 365
    participant_import_max_bytes: int = 10 * 1024 * 1024
    participant_import_max_rows: int = 5_000

    def __post_init__(self) -> None:
        environment = self.app_environment.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise SettingsError(
                "app_environment must be development, test, or production."
            )
        parsed = urlsplit(self.public_base_url.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise SettingsError(
                "PUBLIC_BASE_URL must be an absolute HTTP(S) URL without "
                "credentials, query parameters, or a fragment."
            )
        if environment == "production" and parsed.scheme != "https":
            raise SettingsError("PUBLIC_BASE_URL must use HTTPS in production.")
        for field_name, secret in (
            (
                "PARTICIPANT_IMPORT_HMAC_SECRET",
                self.participant_import_hmac_secret,
            ),
            (
                "PARTICIPANT_IDENTITY_ENCRYPTION_KEY",
                self.participant_identity_encryption_key,
            ),
        ):
            if len(secret.encode("utf-8")) < 32:
                raise SettingsError(
                    f"{field_name} must contain at least 32 UTF-8 bytes."
                )
        if (
            isinstance(self.imported_identity_retention_days, bool)
            or not 1 <= self.imported_identity_retention_days <= 3_650
        ):
            raise SettingsError(
                "IMPORTED_IDENTITY_RETENTION_DAYS must be between 1 and 3650."
            )
        if not 1_024 <= self.participant_import_max_bytes <= 100 * 1024 * 1024:
            raise SettingsError(
                "PARTICIPANT_IMPORT_MAX_BYTES must be between 1024 and 104857600."
            )
        if not 1 <= self.participant_import_max_rows <= 100_000:
            raise SettingsError(
                "PARTICIPANT_IMPORT_MAX_ROWS must be between 1 and 100000."
            )
        normalized_path = parsed.path.rstrip("/")
        object.__setattr__(self, "app_environment", environment)
        object.__setattr__(
            self,
            "public_base_url",
            urlunsplit(
                (parsed.scheme, parsed.netloc, normalized_path, "", "")
            ),
        )

    @classmethod
    def from_environment(cls) -> Settings:
        environment = os.getenv(
            "POLI_INSIGHT_ENVIRONMENT",
            os.getenv("APP_ENV", "development"),
        )
        if environment.strip().lower() == "production":
            for name in (
                "PARTICIPANT_IMPORT_HMAC_SECRET",
                "PARTICIPANT_IDENTITY_ENCRYPTION_KEY",
            ):
                if not os.getenv(name):
                    raise SettingsError(
                        f"{name} must be explicitly configured in production."
                    )
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
            public_base_url=os.getenv(
                "PUBLIC_BASE_URL",
                "http://localhost:8501",
            ),
            app_environment=environment,
            scenario_source_root=os.getenv(
                "SCENARIO_SOURCE_ROOT",
                str(DEFAULT_SCENARIO_SOURCE_ROOT),
            ),
            scenario_template_directory=template_value or None,
            participant_import_hmac_secret=os.getenv(
                "PARTICIPANT_IMPORT_HMAC_SECRET",
                "development-only-participant-import-secret-change-me",
            ),
            participant_identity_encryption_key=os.getenv(
                "PARTICIPANT_IDENTITY_ENCRYPTION_KEY",
                "development-only-participant-identity-key-change-me",
            ),
            imported_identity_retention_days=_environment_integer(
                "IMPORTED_IDENTITY_RETENTION_DAYS", 365
            ),
            participant_import_max_bytes=_environment_integer(
                "PARTICIPANT_IMPORT_MAX_BYTES", 10 * 1024 * 1024
            ),
            participant_import_max_rows=_environment_integer(
                "PARTICIPANT_IMPORT_MAX_ROWS", 5_000
            ),
        )


def _environment_integer(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise SettingsError(f"{name} must be an integer.") from error


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
