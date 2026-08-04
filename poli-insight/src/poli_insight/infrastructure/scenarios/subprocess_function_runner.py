"""Restricted subprocess runner for trusted, configured bundled scenarios."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from poli_insight.application.use_cases.import_scenario import (
    ScenarioImportError,
)


logger = logging.getLogger(__name__)
_MAX_SERIALIZED_FRAME_BYTES = 50 * 1024 * 1024
_ALLOWED_IMPORTS = frozenset({"math", "numpy", "pandas"})
_RUNNER_SCRIPT = r"""
import builtins
import io
import json
import sys

import pandas as pd

payload = json.load(sys.stdin)
allowed_imports = frozenset(payload["allowed_imports"])
real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_name = name.split(".", 1)[0]
    if root_name not in allowed_imports and root_name != "__future__":
        raise ImportError(f"Import {root_name!r} is not approved")
    return real_import(name, globals, locals, fromlist, level)

restricted_builtins = dict(vars(builtins))
restricted_builtins["__import__"] = guarded_import
for blocked_name in ("eval", "exec", "input", "open"):
    restricted_builtins.pop(blocked_name, None)

namespace = {
    "__builtins__": restricted_builtins,
    "__name__": "__bundled_scenario_function__",
}
source = payload["source"]
exec(compile(source, "bundled-scenario-function.py", "exec"), namespace, namespace)
function = namespace.get(payload["callable_name"])
if not callable(function):
    raise TypeError("The approved callable was not found")
frame = pd.read_json(io.StringIO(payload["frame"]), orient="table")
result = function(frame)
if not isinstance(result, pd.DataFrame):
    raise TypeError("The approved callable did not return a DataFrame")
sys.stdout.write(result.to_json(orient="table", index=False))
"""


class BundledScenarioSubprocessRunner:
    """Execute allowlisted functions only from the configured bundled root.

    ZIP uploads use a separate importer without this runner. The child process
    uses Python isolated mode, a restricted import hook, a temporary working
    directory, a timeout, and bounded serialized input/output.
    """

    def __init__(
        self,
        source_root: Path,
        template_directory: Path | None,
        *,
        timeout_seconds: int = 20,
    ) -> None:
        self._root = source_root.resolve(strict=True)
        self._template = (
            template_directory.resolve(strict=True)
            if template_directory is not None
            else None
        )
        if not self._root.is_dir() or (
            self._template is not None
            and (
                not self._template.is_dir()
                or not self._template.is_relative_to(self._root)
            )
        ):
            raise ScenarioImportError(
                "The bundled function source configuration is invalid."
            )
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        source_path: Path,
        source_bytes: bytes,
        callable_name: str,
        allowed_imports: tuple[str, ...],
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        resolved_source = self._validate_source(source_path, source_bytes)
        requested_imports = frozenset(allowed_imports)
        if not requested_imports.issubset(_ALLOWED_IMPORTS):
            raise ScenarioImportError(
                "The bundled function requests unsupported imports."
            )
        frame_json = frame.to_json(orient="table", index=False)
        try:
            source_text = source_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ScenarioImportError(
                "The bundled function source is not valid UTF-8."
            ) from error
        payload = json.dumps(
            {
                "source": source_text,
                "callable_name": callable_name,
                "allowed_imports": sorted(requested_imports),
                "frame": frame_json,
            }
        )
        if len(payload.encode("utf-8")) > _MAX_SERIALIZED_FRAME_BYTES:
            raise ScenarioImportError(
                "The bundled function input exceeds the processing limit."
            )

        try:
            with TemporaryDirectory(
                prefix="poli-insight-bundled-function-"
            ) as working_directory:
                completed = subprocess.run(  # noqa: S603 - fixed executable/script
                    [sys.executable, "-I", "-c", _RUNNER_SCRIPT],
                    input=payload,
                    capture_output=True,
                    text=True,
                    cwd=working_directory,
                    timeout=self._timeout_seconds,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.exception(
                "Bundled function subprocess failed for %s",
                resolved_source.name,
            )
            raise ScenarioImportError(
                "The bundled preprocessing function could not be completed."
            ) from error

        if completed.returncode != 0:
            logger.error(
                "Bundled function subprocess returned %s for %s: %s",
                completed.returncode,
                resolved_source.name,
                completed.stderr[-4000:],
            )
            raise ScenarioImportError(
                "The bundled preprocessing function failed validation."
            )
        if len(completed.stdout.encode("utf-8")) > _MAX_SERIALIZED_FRAME_BYTES:
            raise ScenarioImportError(
                "The bundled function output exceeds the processing limit."
            )
        try:
            return pd.read_json(
                io.StringIO(completed.stdout),
                orient="table",
            )
        except (TypeError, ValueError) as error:
            raise ScenarioImportError(
                "The bundled preprocessing function returned invalid data."
            ) from error

    def _validate_source(
        self,
        source_path: Path,
        source_bytes: bytes,
    ) -> Path:
        try:
            resolved = source_path.resolve(strict=True)
            relative = resolved.relative_to(self._root)
        except (OSError, ValueError) as error:
            raise ScenarioImportError(
                "The bundled function source is outside the configured root."
            ) from error
        if (
            len(relative.parts) < 2
            or (
                self._template is not None
                and resolved.is_relative_to(self._template)
            )
            or not resolved.is_file()
        ):
            raise ScenarioImportError(
                "The bundled function source is not approved for execution."
            )
        try:
            current_bytes = resolved.read_bytes()
        except OSError as error:
            raise ScenarioImportError(
                "The bundled function source is unavailable."
            ) from error
        if current_bytes != source_bytes:
            raise ScenarioImportError(
                "The bundled function source changed during import."
            )
        return resolved
