"""Import a filesystem scenario as an immutable, content-addressed snapshot.

The use case deliberately performs preprocessing only while importing.  The
materialized decision matrix and all referenced source bytes are persisted in
the resulting :class:`~poli_insight.domain.scenario.ScenarioSnapshot`, so later
processing never needs to execute scenario-local Python or reread mutable
files.

Custom functions are disabled unless the caller injects an
``ApprovedFunctionRunner``.  A production runner should execute trusted,
allowlisted code in an isolated process or container; this module does not
pretend that importing a Python file in the application process is a sandbox.
"""

from __future__ import annotations

import io
import json
import mimetypes
import platform
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json, sha256_digest
from poli_insight.domain.enum import (
    ActorType,
    AuditAction,
    CriterionDataType,
    CriterionDirection,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    ScenarioSnapshotStatus,
    ScenarioType,
)
from poli_insight.domain.scenario import (
    ScenarioAlternative,
    ScenarioCriterion,
    ScenarioDefinition,
    ScenarioMatrixValue,
    ScenarioScale,
    ScenarioScaleValue,
    ScenarioSnapshot,
    ScenarioSnapshotFile,
)


JsonObject = Mapping[str, Any]
UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

IMPORTER_VERSION = "poli-insight-scenario-importer/1"
MANIFEST_SCHEMA_VERSION = 1


class ScenarioImportError(ValueError):
    """Raised when scenario source cannot produce a valid snapshot."""


class ApprovedFunctionRunner(Protocol):
    """Port for controlled execution of an allowlisted custom function.

    Implementations are responsible for isolation, time and resource limits,
    and enforcing ``allowed_imports``.  The returned frame must be detached
    from any mutable state retained by the runner.
    """

    def run(
        self,
        *,
        source_path: Path,
        source_bytes: bytes,
        callable_name: str,
        allowed_imports: tuple[str, ...],
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        ...


@dataclass(frozen=True, slots=True)
class ImportScenarioCommand:
    """Inputs needed to import one scenario directory."""

    source_directory: Path
    actor_id: str
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    source_uri: str | None = None
    request_id: str | None = None
    actor_type: ActorType = ActorType.IMPORT_PROCESS

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ScenarioImportError("actor_id cannot be empty")
        if not self.correlation_id.strip():
            raise ScenarioImportError("correlation_id cannot be empty")


@dataclass(frozen=True, slots=True)
class ImportScenarioResult:
    """Identity and readiness outcome returned to the caller."""

    scenario_definition_id: str
    scenario_snapshot_id: str
    root_hash: str
    materialized_input_hash: str
    status: ScenarioSnapshotStatus
    created: bool

    @property
    def ready(self) -> bool:
        return self.status is ScenarioSnapshotStatus.READY


@dataclass(frozen=True, slots=True)
class _SourceFile:
    logical_path: str
    role: ScenarioFileRole
    media_type: str
    content: bytes

    @property
    def content_hash(self) -> str:
        return sha256_digest(self.content)


@dataclass(frozen=True, slots=True)
class _ScenarioDocuments:
    source_directory: Path
    scenario: dict[str, Any]
    criteria: dict[str, Any]
    data_sources: dict[str, Any]
    preprocessing: dict[str, Any]
    session_rules: dict[str, Any]
    ui_config: dict[str, Any]
    files: tuple[_SourceFile, ...]


@dataclass(frozen=True, slots=True)
class _MaterializedScenario:
    frame: pd.DataFrame
    alternative_column: str
    criterion_columns: dict[str, str]
    table_name: str


class ImportScenario:
    """Create or reuse an immutable scenario snapshot from a directory."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        approved_function_runner: ApprovedFunctionRunner | None = None,
        importer_version: str = IMPORTER_VERSION,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
    ) -> None:
        if not importer_version.strip():
            raise ValueError("importer_version cannot be empty")
        self._unit_of_work_factory = unit_of_work_factory
        self._approved_function_runner = approved_function_runner
        self._importer_version = importer_version
        self._clock = clock
        self._id_factory = id_factory

    def execute(self, command: ImportScenarioCommand) -> ImportScenarioResult:
        """Validate, materialize, hash, and persist one scenario snapshot."""

        source_directory = command.source_directory.resolve()
        documents = _read_scenario_documents(source_directory)
        materialized = _materialize_decision_matrix(
            documents,
            approved_function_runner=self._approved_function_runner,
        )
        prepared = _prepare_snapshot_content(documents, materialized)
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            existing_snapshot = unit_of_work.scenarios.get_by_root_hash(
                prepared.root_hash
            )
            if existing_snapshot is not None:
                return _result(existing_snapshot, created=False)

            scenario_key = _required_string(
                documents.scenario,
                "scenario_id",
                document="scenario",
            )
            definition = unit_of_work.scenarios.get_definition_by_key(
                scenario_key
            )
            if definition is None:
                definition = _build_definition(
                    documents.scenario,
                    definition_id=self._id_factory(),
                    actor_id=command.actor_id,
                    occurred_at=occurred_at,
                )
                unit_of_work.scenarios.add_definition(definition)
            elif definition.domain != documents.scenario.get("domain"):
                raise ScenarioImportError(
                    f"Scenario {scenario_key!r} is already registered in "
                    f"domain {definition.domain!r}; the import declares "
                    f"{documents.scenario.get('domain')!r}."
                )

            snapshot = _build_snapshot(
                documents,
                materialized,
                prepared,
                definition_id=definition.scenario_definition_id,
                actor_id=command.actor_id,
                occurred_at=occurred_at,
                source_uri=(
                    command.source_uri
                    if command.source_uri is not None
                    else source_directory.as_uri()
                ),
                importer_version=self._importer_version,
                id_factory=self._id_factory,
            )
            add_result = unit_of_work.scenarios.add_snapshot(snapshot)

            if add_result.created:
                unit_of_work.audit_events.add(
                    _build_import_audit_event(
                        add_result.snapshot,
                        command=command,
                        occurred_at=occurred_at,
                        id_factory=self._id_factory,
                    )
                )

            unit_of_work.commit()
            return _result(add_result.snapshot, created=add_result.created)


@dataclass(frozen=True, slots=True)
class _PreparedSnapshotContent:
    manifest: dict[str, Any]
    root_hash: str
    materialized_input_hash: str


def _read_scenario_documents(source_directory: Path) -> _ScenarioDocuments:
    if not source_directory.is_dir():
        raise ScenarioImportError(
            f"Scenario directory does not exist: {source_directory}"
        )

    captured: dict[str, _SourceFile] = {}
    scenario_path = _find_required_config(
        source_directory,
        names=("scenario.json", "scenario.jsonc"),
        label="scenario configuration",
    )
    scenario_source = _capture_file(
        source_directory,
        scenario_path,
        ScenarioFileRole.SCENARIO_CONFIG,
        captured,
    )
    scenario = _read_json_object(scenario_path, scenario_source.content)
    _validate_scenario_document(scenario)

    criteria_path = _resolve_config_reference(
        source_directory,
        scenario,
        key="criteria_file",
        defaults=("criteria.json", "criteria.jsonc"),
    )
    data_sources_path = _resolve_config_reference(
        source_directory,
        scenario,
        key="data_sources_file",
        defaults=("data_sources.json", "data_sources.jsonc"),
    )
    preprocessing_path = _resolve_config_reference(
        source_directory,
        scenario,
        key="preprocessing_file",
        defaults=("preprocessing.json", "preprocessing.jsonc"),
    )
    session_rules_path = _resolve_config_reference(
        source_directory,
        scenario,
        key="session_rules_file",
        defaults=("session_rules.json", "session_rules.jsonc"),
    )
    ui_config_path = _resolve_config_reference(
        source_directory,
        scenario,
        key="ui_config_file",
        defaults=("ui_config.json", "ui_config.jsonc"),
    )

    config_specs = (
        (criteria_path, ScenarioFileRole.CRITERIA_CONFIG),
        (data_sources_path, ScenarioFileRole.DATA_SOURCE_CONFIG),
        (preprocessing_path, ScenarioFileRole.PREPROCESSING_CONFIG),
        (session_rules_path, ScenarioFileRole.SESSION_RULES),
        (ui_config_path, ScenarioFileRole.UI_CONFIG),
    )
    config_sources = {
        path: _capture_file(source_directory, path, role, captured)
        for path, role in config_specs
    }

    criteria = _read_json_object(
        criteria_path,
        config_sources[criteria_path].content,
    )
    data_sources = _read_json_object(
        data_sources_path,
        config_sources[data_sources_path].content,
    )
    preprocessing = _read_json_object(
        preprocessing_path,
        config_sources[preprocessing_path].content,
    )
    session_rules = _read_json_object(
        session_rules_path,
        config_sources[session_rules_path].content,
    )
    ui_config = _read_json_object(
        ui_config_path,
        config_sources[ui_config_path].content,
    )
    _validate_criteria_document(criteria)

    for source in _data_source_specs(data_sources):
        source_path = _safe_resolve(
            source_directory,
            _required_string(source, "path", document="data source"),
        )
        if not source_path.is_file():
            if bool(source.get("required", True)):
                raise ScenarioImportError(
                    f"Required data source does not exist: {source_path}"
                )
            continue
        _capture_file(
            source_directory,
            source_path,
            ScenarioFileRole.SOURCE_DATA,
            captured,
        )

    for function_spec in _approved_function_specs(preprocessing):
        function_path = _safe_resolve(
            source_directory,
            _required_string(
                function_spec,
                "file",
                document="approved function",
            ),
        )
        if not function_path.is_file():
            raise ScenarioImportError(
                f"Approved function source does not exist: {function_path}"
            )
        _capture_file(
            source_directory,
            function_path,
            ScenarioFileRole.CUSTOM_FUNCTION,
            captured,
        )

    return _ScenarioDocuments(
        source_directory=source_directory,
        scenario=scenario,
        criteria=criteria,
        data_sources=data_sources,
        preprocessing=preprocessing,
        session_rules=session_rules,
        ui_config=ui_config,
        files=tuple(sorted(captured.values(), key=lambda item: item.logical_path)),
    )


def _materialize_decision_matrix(
    documents: _ScenarioDocuments,
    *,
    approved_function_runner: ApprovedFunctionRunner | None,
) -> _MaterializedScenario:
    data_sources = {
        _required_string(spec, "id", document="data source"): spec
        for spec in _data_source_specs(documents.data_sources)
    }
    if len(data_sources) != len(_data_source_specs(documents.data_sources)):
        raise ScenarioImportError("Data source IDs must be unique")

    function_specs = {
        _required_string(spec, "id", document="approved function"): spec
        for spec in _approved_function_specs(documents.preprocessing)
    }
    if len(function_specs) != len(
        _approved_function_specs(documents.preprocessing)
    ):
        raise ScenarioImportError("Approved function IDs must be unique")

    source_contents = {
        item.logical_path: item.content for item in documents.files
    }

    tables: dict[str, pd.DataFrame] = {}
    steps = _required_sequence(
        documents.preprocessing,
        "steps",
        document="preprocessing",
    )
    seen_step_ids: set[str] = set()
    for index, raw_step in enumerate(steps):
        step = _as_object(raw_step, f"preprocessing.steps[{index}]")
        step_id = _required_string(
            step,
            "id",
            document=f"preprocessing.steps[{index}]",
        )
        if step_id in seen_step_ids:
            raise ScenarioImportError(f"Duplicate preprocessing step ID: {step_id}")
        seen_step_ids.add(step_id)

        output_name = _required_string(
            step,
            "output",
            document=f"preprocessing step {step_id!r}",
        )
        if output_name in tables:
            raise ScenarioImportError(
                f"Preprocessing output {output_name!r} is defined more than once"
            )

        operation = _required_string(
            step,
            "type",
            document=f"preprocessing step {step_id!r}",
        )
        tables[output_name] = _execute_step(
            operation,
            step,
            step_id=step_id,
            tables=tables,
            data_sources=data_sources,
            function_specs=function_specs,
            source_directory=documents.source_directory,
            source_contents=source_contents,
            approved_function_runner=approved_function_runner,
        )

    final_output = _as_object(
        documents.preprocessing.get("final_output"),
        "preprocessing.final_output",
    )
    table_name = _required_string(
        final_output,
        "table",
        document="preprocessing.final_output",
    )
    if table_name not in tables:
        raise ScenarioImportError(
            f"Final output references unknown table {table_name!r}"
        )
    alternative_column = _required_string(
        final_output,
        "alternative_id_column",
        document="preprocessing.final_output",
    )
    criterion_columns = _criterion_column_mapping(
        final_output.get("criteria_columns")
    )
    frame = tables[table_name].copy()
    _validate_final_frame(
        frame,
        documents=documents,
        alternative_column=alternative_column,
        criterion_columns=criterion_columns,
    )
    return _MaterializedScenario(
        frame=frame,
        alternative_column=alternative_column,
        criterion_columns=criterion_columns,
        table_name=table_name,
    )


def _execute_step(
    operation: str,
    step: JsonObject,
    *,
    step_id: str,
    tables: Mapping[str, pd.DataFrame],
    data_sources: Mapping[str, JsonObject],
    function_specs: Mapping[str, JsonObject],
    source_directory: Path,
    source_contents: Mapping[str, bytes],
    approved_function_runner: ApprovedFunctionRunner | None,
) -> pd.DataFrame:
    if operation == "load_csv":
        source_ref = _required_string(
            step,
            "source_ref",
            document=f"preprocessing step {step_id!r}",
        )
        source = data_sources.get(source_ref)
        if source is None:
            raise ScenarioImportError(
                f"Step {step_id!r} references unknown source {source_ref!r}"
            )
        if source.get("type") != "csv":
            raise ScenarioImportError(
                f"Step {step_id!r} requires a CSV source, got "
                f"{source.get('type')!r}"
            )
        source_path = _safe_resolve(
            source_directory,
            _required_string(source, "path", document="data source"),
        )
        logical_path = source_path.relative_to(source_directory).as_posix()
        try:
            source_bytes = source_contents[logical_path]
        except KeyError as error:
            raise ScenarioImportError(
                f"CSV source {logical_path!r} was not captured for this import"
            ) from error
        options = step.get("options", {})
        if not isinstance(options, Mapping):
            raise ScenarioImportError(
                f"Options for step {step_id!r} must be an object"
            )
        try:
            return pd.read_csv(io.BytesIO(source_bytes), **dict(options))
        except Exception as error:
            raise ScenarioImportError(
                f"Unable to load CSV for step {step_id!r}: {error}"
            ) from error

    if operation == "join":
        left = _table(tables, step, "left", step_id)
        right = _table(tables, step, "right", step_id)
        join_columns = step.get("on")
        if isinstance(join_columns, str):
            on: str | list[str] = join_columns
        elif isinstance(join_columns, Sequence) and not isinstance(
            join_columns, (str, bytes)
        ):
            on = [
                _require_text(item, f"join key for step {step_id!r}")
                for item in join_columns
            ]
        else:
            raise ScenarioImportError(
                f"Join step {step_id!r} requires 'on' as a string or list"
            )
        return left.merge(
            right,
            how=str(step.get("how", "inner")),
            on=on,
        )

    frame = _input_table(tables, step, step_id)
    if operation == "rename_columns":
        columns = _string_mapping(step.get("columns"), step_id=step_id)
        _require_columns(frame, columns, step_id=step_id)
        return frame.rename(columns=columns)

    if operation == "convert_types":
        columns = _string_mapping(step.get("columns"), step_id=step_id)
        _require_columns(frame, columns, step_id=step_id)
        converted = frame.copy()
        for column, type_name in columns.items():
            converted[column] = _convert_series(
                converted[column],
                type_name,
                step_id=step_id,
            )
        return converted

    if operation == "missing_values":
        return _handle_missing_values(frame, step, step_id=step_id)

    if operation == "derive_column":
        return _derive_column(frame, step, step_id=step_id)

    if operation == "approved_function":
        function_ref = _required_string(
            step,
            "function_ref",
            document=f"preprocessing step {step_id!r}",
        )
        function_spec = function_specs.get(function_ref)
        if function_spec is None:
            raise ScenarioImportError(
                f"Step {step_id!r} references unapproved function "
                f"{function_ref!r}"
            )
        if approved_function_runner is None:
            raise ScenarioImportError(
                f"Scenario requires approved function {function_ref!r}, but "
                "no isolated ApprovedFunctionRunner was configured."
            )
        source_path = _safe_resolve(
            source_directory,
            _required_string(
                function_spec,
                "file",
                document=f"approved function {function_ref!r}",
            ),
        )
        logical_path = source_path.relative_to(source_directory).as_posix()
        try:
            source_bytes = source_contents[logical_path]
        except KeyError as error:
            raise ScenarioImportError(
                f"Custom function source {logical_path!r} was not captured"
            ) from error
        callable_name = _required_string(
            function_spec,
            "callable",
            document=f"approved function {function_ref!r}",
        )
        allowed_imports_raw = function_spec.get("allowed_imports", [])
        allowed_imports = tuple(
            _require_text(item, "allowed import")
            for item in _as_sequence(
                allowed_imports_raw,
                f"approved function {function_ref!r}.allowed_imports",
            )
        )
        result = approved_function_runner.run(
            source_path=source_path,
            source_bytes=source_bytes,
            callable_name=callable_name,
            allowed_imports=allowed_imports,
            frame=frame.copy(),
        )
        if not isinstance(result, pd.DataFrame):
            raise ScenarioImportError(
                f"Approved function {function_ref!r} did not return a DataFrame"
            )
        return result.copy()

    if operation == "select_columns":
        raw_columns = step.get("columns")
        if isinstance(raw_columns, Mapping):
            selected = [
                _require_text(key, f"selected column for step {step_id!r}")
                for key, include in raw_columns.items()
                if bool(include)
            ]
        else:
            selected = [
                _require_text(item, f"selected column for step {step_id!r}")
                for item in _as_sequence(
                    raw_columns,
                    f"preprocessing step {step_id!r}.columns",
                )
            ]
        _require_columns(frame, selected, step_id=step_id)
        return frame.loc[:, selected].copy()

    raise ScenarioImportError(
        f"Unsupported preprocessing operation {operation!r} in step {step_id!r}"
    )


def _handle_missing_values(
    frame: pd.DataFrame,
    step: JsonObject,
    *,
    step_id: str,
) -> pd.DataFrame:
    result = frame.copy()
    raw_strategy = step.get("strategy", "error")
    if isinstance(raw_strategy, str):
        return _apply_missing_strategy(
            result,
            raw_strategy,
            columns=list(result.columns),
            step_id=step_id,
        )
    strategy = _as_object(raw_strategy, f"step {step_id!r}.strategy")
    default = str(strategy.get("default", "error"))
    overrides_raw = strategy.get("columns", {})
    overrides = _string_mapping(overrides_raw, step_id=step_id)
    unknown = set(overrides).difference(result.columns)
    if unknown:
        raise ScenarioImportError(
            f"Step {step_id!r} references unknown columns: {sorted(unknown)}"
        )
    by_strategy: dict[str, list[str]] = {}
    for column in result.columns:
        selected_strategy = overrides.get(str(column), default)
        by_strategy.setdefault(selected_strategy, []).append(str(column))
    for selected_strategy, columns in by_strategy.items():
        result = _apply_missing_strategy(
            result,
            selected_strategy,
            columns=columns,
            step_id=step_id,
        )
    return result


def _apply_missing_strategy(
    frame: pd.DataFrame,
    strategy: str,
    *,
    columns: list[str],
    step_id: str,
) -> pd.DataFrame:
    result = frame.copy()
    missing = result[columns].isna()
    if strategy == "error":
        if bool(missing.any(axis=None)):
            raise ScenarioImportError(
                f"Step {step_id!r} encountered missing values in "
                f"{[column for column in columns if result[column].isna().any()]}"
            )
        return result
    if strategy in {"drop_rows", "drop"}:
        return result.dropna(subset=columns)
    if strategy in {"fill_zero", "zero"}:
        result.loc[:, columns] = result[columns].fillna(0)
        return result
    if strategy in {"fill_forward", "forward"}:
        result.loc[:, columns] = result[columns].ffill()
        return result
    if strategy in {"fill_mean", "mean", "fill_median", "median"}:
        for column in columns:
            series = pd.to_numeric(result[column], errors="raise")
            value = series.mean() if "mean" in strategy else series.median()
            result[column] = result[column].fillna(value)
        return result
    raise ScenarioImportError(
        f"Unsupported missing-value strategy {strategy!r} in step {step_id!r}"
    )


def _derive_column(
    frame: pd.DataFrame,
    step: JsonObject,
    *,
    step_id: str,
) -> pd.DataFrame:
    result = frame.copy()
    explicit_new_column = step.get("new_column")
    operation = _required_string(
        step,
        "operation",
        document=f"preprocessing step {step_id!r}",
    )
    operands = [
        _require_text(item, f"operand for step {step_id!r}")
        for item in _as_sequence(
            step.get("operands"),
            f"preprocessing step {step_id!r}.operands",
        )
    ]

    if explicit_new_column is not None:
        new_column = _require_text(explicit_new_column, "new_column")
        if len(operands) != 2:
            raise ScenarioImportError(
                f"Step {step_id!r} operation {operation!r} requires two operands"
            )
        left, right = (_operand(result, value, step_id) for value in operands)
        result[new_column] = _apply_operator(
            left,
            right,
            operation,
            on_zero=str(step.get("on_zero", "error")),
            step_id=step_id,
        )
        return result

    new_column = operation
    if len(operands) < 3 or len(operands) % 2 == 0:
        raise ScenarioImportError(
            f"Step {step_id!r} operands must alternate column/operator/column"
        )
    value = _operand(result, operands[0], step_id)
    for index in range(1, len(operands), 2):
        value = _apply_operator(
            value,
            _operand(result, operands[index + 1], step_id),
            operands[index],
            on_zero=str(step.get("on_zero", "error")),
            step_id=step_id,
        )
    result[new_column] = value
    return result


def _apply_operator(
    left: Any,
    right: Any,
    operation: str,
    *,
    on_zero: str,
    step_id: str,
) -> Any:
    aliases = {
        "add": "+",
        "subtract": "-",
        "multiply": "*",
        "divide": "/",
        "modulo": "%",
    }
    operator = aliases.get(operation, operation)
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator in {"/", "%"}:
        zero_mask = right == 0
        if hasattr(zero_mask, "any") and bool(zero_mask.any()):
            if on_zero == "error":
                raise ScenarioImportError(
                    f"Step {step_id!r} attempted division by zero"
                )
            if on_zero != "zero":
                raise ScenarioImportError(
                    f"Unsupported on_zero policy {on_zero!r} in step {step_id!r}"
                )
        calculated = left / right if operator == "/" else left % right
        if on_zero == "zero" and hasattr(calculated, "mask"):
            return calculated.mask(zero_mask, 0)
        return calculated
    raise ScenarioImportError(
        f"Unsupported derive operator {operation!r} in step {step_id!r}"
    )


def _validate_final_frame(
    frame: pd.DataFrame,
    *,
    documents: _ScenarioDocuments,
    alternative_column: str,
    criterion_columns: Mapping[str, str],
) -> None:
    rules_value = documents.preprocessing.get(
        "validation",
        documents.preprocessing.get("validations", {}),
    )
    rules = _as_object(rules_value, "preprocessing.validation")
    required_columns = [
        _require_text(item, "required output column")
        for item in _as_sequence(
            rules.get("required_columns", []),
            "preprocessing.validation.required_columns",
        )
    ]
    required_columns.extend([alternative_column, *criterion_columns.values()])
    _require_columns(frame, required_columns, step_id="final_output")

    no_nulls = [
        _require_text(item, "non-null output column")
        for item in _as_sequence(
            rules.get("no_nulls_in", []),
            "preprocessing.validation.no_nulls_in",
        )
    ]
    _require_columns(frame, no_nulls, step_id="final_output")
    null_columns = [column for column in no_nulls if frame[column].isna().any()]
    if null_columns:
        raise ScenarioImportError(
            f"Final decision matrix has null values in {null_columns}"
        )

    minimum_rows = rules.get("minimum_rows", 1)
    if not isinstance(minimum_rows, int) or minimum_rows < 1:
        raise ScenarioImportError("minimum_rows must be a positive integer")
    if len(frame.index) < minimum_rows:
        raise ScenarioImportError(
            f"Final decision matrix has {len(frame.index)} rows; "
            f"at least {minimum_rows} are required"
        )
    if frame[alternative_column].isna().any():
        raise ScenarioImportError("Alternative identifiers cannot be null")
    if frame[alternative_column].duplicated().any():
        duplicates = frame.loc[
            frame[alternative_column].duplicated(keep=False),
            alternative_column,
        ].astype(str)
        raise ScenarioImportError(
            f"Alternative identifiers must be unique; duplicates: "
            f"{sorted(set(duplicates))}"
        )

    declared_criteria = {
        _required_string(item, "id", document="criterion")
        for item in _criteria_specs(documents.criteria)
    }
    if set(criterion_columns) != declared_criteria:
        missing = sorted(declared_criteria.difference(criterion_columns))
        unknown = sorted(set(criterion_columns).difference(declared_criteria))
        raise ScenarioImportError(
            "Final output criterion mapping must exactly match declared "
            f"criteria; missing={missing}, unknown={unknown}"
        )

    declared_alternatives = {
        _required_string(item, "id", document="alternative")
        for item in _alternative_specs(documents.scenario)
    }
    output_alternatives = set(frame[alternative_column].astype(str))
    if output_alternatives != declared_alternatives:
        missing = sorted(declared_alternatives.difference(output_alternatives))
        unknown = sorted(output_alternatives.difference(declared_alternatives))
        raise ScenarioImportError(
            "Materialized alternatives must exactly match scenario alternatives; "
            f"missing={missing}, unknown={unknown}"
        )


def _prepare_snapshot_content(
    documents: _ScenarioDocuments,
    materialized: _MaterializedScenario,
) -> _PreparedSnapshotContent:
    matrix_document = _matrix_hash_document(documents, materialized)
    materialized_input_hash = hash_json(matrix_document)
    components = [
        {
            "logical_path": source_file.logical_path,
            "role": source_file.role.value,
            "media_type": source_file.media_type,
            "byte_size": len(source_file.content),
            "content_hash": source_file.content_hash,
        }
        for source_file in documents.files
    ]
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "scenario_key": documents.scenario["scenario_id"],
        "declared_version": documents.scenario["scenario_version"],
        "components": components,
        "materialized_input": {
            "schema_version": 1,
            "content_hash": materialized_input_hash,
            "alternative_count": len(_alternative_specs(documents.scenario)),
            "criterion_count": len(_criteria_specs(documents.criteria)),
            "value_count": (
                len(_alternative_specs(documents.scenario))
                * len(_criteria_specs(documents.criteria))
            ),
        },
    }
    return _PreparedSnapshotContent(
        manifest=manifest,
        root_hash=hash_json(manifest),
        materialized_input_hash=materialized_input_hash,
    )


def _build_definition(
    scenario: JsonObject,
    *,
    definition_id: str,
    actor_id: str,
    occurred_at: datetime,
) -> ScenarioDefinition:
    status_value = str(scenario.get("status", "active"))
    if status_value == "active":
        status = ScenarioDefinitionStatus.ACTIVE
    elif status_value in {"retired", "archived"}:
        status = ScenarioDefinitionStatus.RETIRED
    else:
        raise ScenarioImportError(
            f"Unsupported scenario definition status: {status_value!r}"
        )
    return ScenarioDefinition(
        scenario_definition_id=definition_id,
        scenario_key=_required_string(
            scenario, "scenario_id", document="scenario"
        ),
        title=_required_string(scenario, "title", document="scenario"),
        domain=_required_string(scenario, "domain", document="scenario"),
        description=_required_string(
            scenario,
            "description",
            document="scenario",
        ),
        status=status,
        created_at=occurred_at,
        created_by=actor_id,
        updated_at=occurred_at,
        updated_by=actor_id,
    )


def _build_snapshot(
    documents: _ScenarioDocuments,
    materialized: _MaterializedScenario,
    prepared: _PreparedSnapshotContent,
    *,
    definition_id: str,
    actor_id: str,
    occurred_at: datetime,
    source_uri: str,
    importer_version: str,
    id_factory: IdFactory,
) -> ScenarioSnapshot:
    criterion_specs = _criteria_specs(documents.criteria)
    alternative_specs = _alternative_specs(documents.scenario)
    criterion_ids = {
        _required_string(item, "id", document="criterion"): id_factory()
        for item in criterion_specs
    }
    alternative_ids = {
        _required_string(item, "id", document="alternative"): id_factory()
        for item in alternative_specs
    }
    criteria = tuple(
        _build_criterion(
            item,
            criterion_ids=criterion_ids,
            default_order=index,
        )
        for index, item in enumerate(criterion_specs)
    )
    alternatives = tuple(
        ScenarioAlternative(
            alternative_id=alternative_ids[
                _required_string(item, "id", document="alternative")
            ],
            alternative_key=_required_string(
                item, "id", document="alternative"
            ),
            name=_required_string(item, "name", document="alternative"),
            description=_optional_string(item.get("description")),
            display_order=_nonnegative_int(
                item.get("display_order", index),
                field_name="alternative.display_order",
            ),
            metadata_json=_extra_fields(
                item,
                excluded={"id", "name", "description", "display_order"},
            ),
        )
        for index, item in enumerate(alternative_specs)
    )
    scales = _build_scales(documents.scenario, id_factory=id_factory)
    matrix_values = _build_matrix_values(
        documents,
        materialized,
        alternative_ids=alternative_ids,
        criterion_ids=criterion_ids,
    )
    return ScenarioSnapshot(
        scenario_snapshot_id=id_factory(),
        scenario_definition_id=definition_id,
        declared_version=_required_string(
            documents.scenario,
            "scenario_version",
            document="scenario",
        ),
        scenario_type=ScenarioType(
            str(documents.scenario.get("scenario_type", "standard"))
        ),
        schema_version=_major_schema_version(
            documents.scenario.get("schema_version", 1)
        ),
        status=ScenarioSnapshotStatus.READY,
        title=_required_string(
            documents.scenario, "title", document="scenario"
        ),
        domain=_required_string(
            documents.scenario, "domain", document="scenario"
        ),
        summary=_required_string(
            documents.scenario, "summary", document="scenario"
        ),
        policy_question=_required_string(
            documents.scenario,
            "policy_question",
            document="scenario",
        ),
        manifest_json=prepared.manifest,
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        root_hash=prepared.root_hash,
        materialized_input_hash=prepared.materialized_input_hash,
        source_uri=source_uri,
        importer_version=importer_version,
        import_environment_json={
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "pandas_version": pd.__version__,
            "platform": sys.platform,
        },
        created_at=occurred_at,
        created_by=actor_id,
        ready_at=occurred_at,
        files=tuple(
            ScenarioSnapshotFile(
                snapshot_file_id=id_factory(),
                logical_path=item.logical_path,
                file_role=item.role,
                media_type=item.media_type,
                byte_size=len(item.content),
                content_hash=item.content_hash,
                inline_bytes=item.content,
            )
            for item in documents.files
        ),
        criteria=criteria,
        alternatives=alternatives,
        scales=scales,
        matrix_values=matrix_values,
    )


def _build_criterion(
    item: JsonObject,
    *,
    criterion_ids: Mapping[str, str],
    default_order: int,
) -> ScenarioCriterion:
    key = _required_string(item, "id", document="criterion")
    parent_key = _optional_string(item.get("parent_id"))
    if parent_key is not None and parent_key not in criterion_ids:
        raise ScenarioImportError(
            f"Criterion {key!r} references unknown parent {parent_key!r}"
        )
    return ScenarioCriterion(
        criterion_id=criterion_ids[key],
        criterion_key=key,
        name=_required_string(item, "name", document="criterion"),
        direction=CriterionDirection(
            _required_string(item, "criteria_type", document="criterion")
        ),
        data_type=CriterionDataType(
            str(item.get("data_type", CriterionDataType.NUMERIC.value))
        ),
        display_order=_nonnegative_int(
            item.get("display_order", default_order),
            field_name=f"criterion {key!r}.display_order",
        ),
        description=_optional_string(item.get("description")),
        unit=_optional_string(item.get("unit")),
        parent_criterion_id=(
            criterion_ids[parent_key] if parent_key is not None else None
        ),
        required=bool(item.get("required", True)),
        source_column=_optional_string(item.get("source_column")),
        metadata_json=_extra_fields(
            item,
            excluded={
                "id",
                "name",
                "description",
                "criteria_type",
                "data_type",
                "display_order",
                "unit",
                "parent_id",
                "required",
                "source_column",
            },
        ),
    )


def _build_scales(
    scenario: JsonObject,
    *,
    id_factory: IdFactory,
) -> tuple[ScenarioScale, ...]:
    raw_scales = scenario.get("scales", {})
    if not isinstance(raw_scales, Mapping):
        raise ScenarioImportError("scenario.scales must be an object")
    scales: list[ScenarioScale] = []
    for scale_key, raw_scale in sorted(raw_scales.items()):
        scale_key = _require_text(scale_key, "scale key")
        scale = _as_object(raw_scale, f"scenario.scales.{scale_key}")
        scale_id = id_factory()
        values: list[ScenarioScaleValue] = []
        seen_value_keys: set[str] = set()
        for index, raw_value in enumerate(
            _as_sequence(
                scale.get("values", []),
                f"scenario.scales.{scale_key}.values",
            )
        ):
            value = _as_object(
                raw_value,
                f"scenario.scales.{scale_key}.values[{index}]",
            )
            label = _required_string(value, "label", document="scale value")
            stable_key = str(
                value.get("id")
                or value.get("key")
                or _slugify(label)
                or f"value_{index}"
            )
            if stable_key in seen_value_keys:
                raise ScenarioImportError(
                    f"Scale {scale_key!r} has duplicate value key {stable_key!r}"
                )
            seen_value_keys.add(stable_key)
            fuzzy = value.get("fuzzy_value")
            fuzzy_values: tuple[Decimal | None, Decimal | None, Decimal | None]
            if fuzzy is None:
                fuzzy_values = (None, None, None)
            else:
                parts = _as_sequence(
                    fuzzy,
                    f"scale {scale_key!r} value {stable_key!r}.fuzzy_value",
                )
                if len(parts) != 3:
                    raise ScenarioImportError(
                        f"Fuzzy value {stable_key!r} must contain three numbers"
                    )
                fuzzy_values = (
                    _decimal(parts[0]),
                    _decimal(parts[1]),
                    _decimal(parts[2]),
                )
            values.append(
                ScenarioScaleValue(
                    scale_value_id=id_factory(),
                    scale_id=scale_id,
                    stable_value_key=stable_key,
                    label=label,
                    ordinal=_nonnegative_int(
                        value.get("ordinal", index),
                        field_name=f"scale value {stable_key!r}.ordinal",
                    ),
                    numeric_value=(
                        _decimal(value["numeric_value"])
                        if value.get("numeric_value") is not None
                        else None
                    ),
                    fuzzy_lower=fuzzy_values[0],
                    fuzzy_middle=fuzzy_values[1],
                    fuzzy_upper=fuzzy_values[2],
                    metadata_json=_extra_fields(
                        value,
                        excluded={
                            "id",
                            "key",
                            "label",
                            "ordinal",
                            "numeric_value",
                            "fuzzy_value",
                        },
                    ),
                )
            )
        scales.append(
            ScenarioScale(
                scale_id=scale_id,
                scale_key=scale_key,
                name=str(scale.get("name", scale_key.replace("_", " ").title())),
                scale_type=str(
                    scale.get(
                        "type",
                        scale.get("elicitation_method", "numeric"),
                    )
                ),
                ordered=bool(scale.get("ordered", True)),
                definition_version=_major_schema_version(
                    scale.get("version", 1)
                ),
                metadata_json=_extra_fields(
                    scale,
                    excluded={
                        "name",
                        "type",
                        "elicitation_method",
                        "ordered",
                        "version",
                        "values",
                    },
                ),
                values=tuple(values),
            )
        )
    return tuple(scales)


def _build_matrix_values(
    documents: _ScenarioDocuments,
    materialized: _MaterializedScenario,
    *,
    alternative_ids: Mapping[str, str],
    criterion_ids: Mapping[str, str],
) -> tuple[ScenarioMatrixValue, ...]:
    criterion_specs = {
        _required_string(item, "id", document="criterion"): item
        for item in _criteria_specs(documents.criteria)
    }
    values: list[ScenarioMatrixValue] = []
    for row_index, row in materialized.frame.reset_index(drop=True).iterrows():
        alternative_key = str(row[materialized.alternative_column])
        for criterion_key, column in materialized.criterion_columns.items():
            criterion = criterion_specs[criterion_key]
            raw_value = row[column]
            data_type = CriterionDataType(
                str(criterion.get("data_type", "numeric"))
            )
            provenance = {
                "schema_version": 1,
                "pipeline_id": documents.preprocessing.get("pipeline_id"),
                "output_table": materialized.table_name,
                "row_index": int(row_index),
                "alternative_key": alternative_key,
                "criterion_key": criterion_key,
                "source_column": column,
            }
            if data_type is CriterionDataType.NUMERIC:
                values.append(
                    ScenarioMatrixValue(
                        alternative_id=alternative_ids[alternative_key],
                        criterion_id=criterion_ids[criterion_key],
                        value_numeric=_decimal(raw_value),
                        source_provenance_json=provenance,
                    )
                )
            else:
                values.append(
                    ScenarioMatrixValue(
                        alternative_id=alternative_ids[alternative_key],
                        criterion_id=criterion_ids[criterion_key],
                        value_json={"value": _plain_scalar(raw_value)},
                        source_provenance_json=provenance,
                    )
                )
    return tuple(values)


def _matrix_hash_document(
    documents: _ScenarioDocuments,
    materialized: _MaterializedScenario,
) -> dict[str, Any]:
    criterion_specs = {
        _required_string(item, "id", document="criterion"): item
        for item in _criteria_specs(documents.criteria)
    }
    rows: list[dict[str, Any]] = []
    for _, row in materialized.frame.iterrows():
        values: dict[str, Any] = {}
        for criterion_key, column in materialized.criterion_columns.items():
            data_type = CriterionDataType(
                str(criterion_specs[criterion_key].get("data_type", "numeric"))
            )
            values[criterion_key] = (
                _decimal(row[column])
                if data_type is CriterionDataType.NUMERIC
                else _plain_scalar(row[column])
            )
        rows.append(
            {
                "alternative_key": str(row[materialized.alternative_column]),
                "values": values,
            }
        )
    rows.sort(key=lambda item: item["alternative_key"])
    return {
        "schema_version": 1,
        "criteria": sorted(materialized.criterion_columns),
        "rows": rows,
    }


def _build_import_audit_event(
    snapshot: ScenarioSnapshot,
    *,
    command: ImportScenarioCommand,
    occurred_at: datetime,
    id_factory: IdFactory,
) -> AuditEvent:
    event_id = id_factory()
    after_json = {
        "schema_version": 1,
        "scenario_definition_id": snapshot.scenario_definition_id,
        "scenario_snapshot_id": snapshot.scenario_snapshot_id,
        "declared_version": snapshot.declared_version,
        "root_hash": snapshot.root_hash,
        "materialized_input_hash": snapshot.materialized_input_hash,
        "status": snapshot.status.value,
    }
    source_metadata = {
        "schema_version": 1,
        "importer_version": snapshot.importer_version,
        "source_uri": snapshot.source_uri,
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "scenario_snapshot",
        "entity_id": snapshot.scenario_snapshot_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.CREATED,
        entity_type="scenario_snapshot",
        entity_id=snapshot.scenario_snapshot_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )


def _result(snapshot: ScenarioSnapshot, *, created: bool) -> ImportScenarioResult:
    return ImportScenarioResult(
        scenario_definition_id=snapshot.scenario_definition_id,
        scenario_snapshot_id=snapshot.scenario_snapshot_id,
        root_hash=snapshot.root_hash,
        materialized_input_hash=snapshot.materialized_input_hash,
        status=snapshot.status,
        created=created,
    )


def _validate_scenario_document(scenario: JsonObject) -> None:
    required = (
        "scenario_id",
        "scenario_version",
        "title",
        "domain",
        "summary",
        "description",
        "policy_question",
    )
    for key in required:
        _required_string(scenario, key, document="scenario")
    try:
        ScenarioType(str(scenario.get("scenario_type", "standard")))
    except ValueError as error:
        raise ScenarioImportError(
            f"Unsupported scenario_type: {scenario.get('scenario_type')!r}"
        ) from error
    alternatives = _alternative_specs(scenario)
    keys = [
        _required_string(item, "id", document="alternative")
        for item in alternatives
    ]
    if not keys:
        raise ScenarioImportError("Scenario must define at least one alternative")
    if len(keys) != len(set(keys)):
        raise ScenarioImportError("Alternative IDs must be unique")
    for item in alternatives:
        _required_string(item, "name", document="alternative")


def _validate_criteria_document(criteria: JsonObject) -> None:
    specs = _criteria_specs(criteria)
    if not specs:
        raise ScenarioImportError("Scenario must define at least one criterion")
    keys: list[str] = []
    for item in specs:
        key = _required_string(item, "id", document="criterion")
        keys.append(key)
        _required_string(item, "name", document=f"criterion {key!r}")
        try:
            CriterionDirection(
                _required_string(
                    item,
                    "criteria_type",
                    document=f"criterion {key!r}",
                )
            )
            CriterionDataType(str(item.get("data_type", "numeric")))
        except ValueError as error:
            raise ScenarioImportError(
                f"Criterion {key!r} has an unsupported type"
            ) from error
    if len(keys) != len(set(keys)):
        raise ScenarioImportError("Criterion IDs must be unique")


def _read_json_object(path: Path, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8-sig")
        if path.suffix.lower() == ".jsonc":
            text = _strip_jsonc(text)
        value = json.loads(text)
    except OSError as error:
        raise ScenarioImportError(f"Unable to read {path}: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScenarioImportError(f"Malformed JSON document {path}: {error}") from error
    if not isinstance(value, dict):
        raise ScenarioImportError(f"JSON document must contain an object: {path}")
    return value


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas without altering strings."""

    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline == -1 else newline
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                raise ScenarioImportError("Unterminated block comment in JSONC")
            index = end + 2
            continue
        output.append(char)
        index += 1
    return _remove_jsonc_trailing_commas("".join(output))


def _remove_jsonc_trailing_commas(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _find_required_config(
    base: Path,
    *,
    names: tuple[str, ...],
    label: str,
) -> Path:
    existing = [base / name for name in names if (base / name).is_file()]
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        raise ScenarioImportError(
            f"Multiple {label} files found: {[path.name for path in existing]}"
        )
    raise ScenarioImportError(
        f"Missing {label}; expected one of {list(names)} in {base}"
    )


def _resolve_config_reference(
    base: Path,
    scenario: JsonObject,
    *,
    key: str,
    defaults: tuple[str, ...],
) -> Path:
    reference = scenario.get(key)
    if reference is not None:
        path = _safe_resolve(base, _require_text(reference, f"scenario.{key}"))
        if not path.is_file():
            raise ScenarioImportError(
                f"Referenced configuration does not exist: {path}"
            )
        return path
    return _find_required_config(base, names=defaults, label=key)


def _safe_resolve(base: Path, reference: str) -> Path:
    candidate = (base / reference).resolve()
    if not candidate.is_relative_to(base):
        raise ScenarioImportError(
            f"Unsafe path reference outside scenario directory: {reference!r}"
        )
    return candidate


def _capture_file(
    base: Path,
    path: Path,
    role: ScenarioFileRole,
    captured: dict[str, _SourceFile],
) -> _SourceFile:
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise ScenarioImportError(
            f"Cannot capture file outside scenario directory: {path}"
        )
    try:
        content = resolved.read_bytes()
    except OSError as error:
        raise ScenarioImportError(
            f"Unable to read referenced file {path}: {error}"
        ) from error
    logical_path = resolved.relative_to(base).as_posix()
    existing = captured.get(logical_path)
    if existing is not None:
        if existing.role is not role and role is not ScenarioFileRole.CUSTOM_FUNCTION:
            raise ScenarioImportError(
                f"File {logical_path!r} is referenced with conflicting roles"
            )
        return existing
    source_file = _SourceFile(
        logical_path=logical_path,
        role=role,
        media_type=_media_type(resolved),
        content=content,
    )
    captured[logical_path] = source_file
    return source_file


def _media_type(path: Path) -> str:
    if path.suffix.lower() in {".json", ".jsonc"}:
        return "application/json"
    if path.suffix.lower() == ".csv":
        return "text/csv"
    if path.suffix.lower() == ".py":
        return "text/x-python"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _data_source_specs(document: JsonObject) -> list[dict[str, Any]]:
    return [
        _as_object(item, f"data_sources[{index}]")
        for index, item in enumerate(
            _required_sequence(document, "data_sources", document="data_sources")
        )
    ]


def _approved_function_specs(document: JsonObject) -> list[dict[str, Any]]:
    return [
        _as_object(item, f"approved_functions[{index}]")
        for index, item in enumerate(
            _as_sequence(
                document.get("approved_functions", []),
                "preprocessing.approved_functions",
            )
        )
    ]


def _criteria_specs(document: JsonObject) -> list[dict[str, Any]]:
    return [
        _as_object(item, f"criteria[{index}]")
        for index, item in enumerate(
            _required_sequence(document, "criteria", document="criteria")
        )
    ]


def _alternative_specs(document: JsonObject) -> list[dict[str, Any]]:
    return [
        _as_object(item, f"alternatives[{index}]")
        for index, item in enumerate(
            _required_sequence(document, "alternatives", document="scenario")
        )
    ]


def _criterion_column_mapping(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {
            _require_text(key, "criterion key"): _require_text(
                column, "criterion output column"
            )
            for key, column in value.items()
        }
    return {
        column: column
        for column in (
            _require_text(item, "criterion output column")
            for item in _as_sequence(value, "final_output.criteria_columns")
        )
    }


def _input_table(
    tables: Mapping[str, pd.DataFrame],
    step: JsonObject,
    step_id: str,
) -> pd.DataFrame:
    return _table(tables, step, "input", step_id)


def _table(
    tables: Mapping[str, pd.DataFrame],
    step: JsonObject,
    key: str,
    step_id: str,
) -> pd.DataFrame:
    name = _required_string(
        step,
        key,
        document=f"preprocessing step {step_id!r}",
    )
    try:
        return tables[name].copy()
    except KeyError as error:
        raise ScenarioImportError(
            f"Step {step_id!r} references unknown table {name!r}"
        ) from error


def _convert_series(
    series: pd.Series,
    type_name: str,
    *,
    step_id: str,
) -> pd.Series:
    try:
        if type_name in {"string", "str"}:
            return series.astype("string")
        if type_name in {"int", "integer"}:
            return pd.to_numeric(series, errors="raise").astype("int64")
        if type_name in {"float", "numeric", "number"}:
            return pd.to_numeric(series, errors="raise").astype("float64")
        if type_name in {"bool", "boolean"}:
            return series.astype("boolean")
    except (TypeError, ValueError) as error:
        raise ScenarioImportError(
            f"Unable to convert {series.name!r} to {type_name!r} in "
            f"step {step_id!r}: {error}"
        ) from error
    raise ScenarioImportError(
        f"Unsupported conversion type {type_name!r} in step {step_id!r}"
    )


def _operand(frame: pd.DataFrame, value: str, step_id: str) -> Any:
    if value in frame.columns:
        return frame[value]
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ScenarioImportError(
            f"Step {step_id!r} references unknown operand {value!r}"
        ) from error


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str] | Mapping[str, object],
    *,
    step_id: str,
) -> None:
    missing = sorted(set(columns).difference(str(item) for item in frame.columns))
    if missing:
        raise ScenarioImportError(
            f"Step {step_id!r} is missing required columns: {missing}"
        )


def _string_mapping(value: object, *, step_id: str) -> dict[str, str]:
    mapping = _as_object(value, f"preprocessing step {step_id!r}.columns")
    return {
        _require_text(key, f"column name in step {step_id!r}"): _require_text(
            item, f"column value in step {step_id!r}"
        )
        for key, item in mapping.items()
    }


def _required_string(
    document_value: JsonObject,
    key: str,
    *,
    document: str,
) -> str:
    if key not in document_value:
        raise ScenarioImportError(f"{document} is missing required field {key!r}")
    return _require_text(document_value[key], f"{document}.{key}")


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioImportError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ScenarioImportError(
            f"{field_name} cannot contain leading or trailing whitespace"
        )
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_text(value, "optional text value")


def _required_sequence(
    document_value: JsonObject,
    key: str,
    *,
    document: str,
) -> list[Any]:
    if key not in document_value:
        raise ScenarioImportError(f"{document} is missing required field {key!r}")
    return _as_sequence(document_value[key], f"{document}.{key}")


def _as_sequence(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScenarioImportError(f"{field_name} must be a list")
    return value


def _as_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScenarioImportError(f"{field_name} must be an object")
    return dict(value)


def _nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScenarioImportError(f"{field_name} must be a nonnegative integer")
    return value


def _major_schema_version(value: object) -> int:
    if isinstance(value, bool):
        raise ScenarioImportError("schema version must be a positive version")
    try:
        major = int(str(value).split(".", maxsplit=1)[0])
    except (TypeError, ValueError) as error:
        raise ScenarioImportError(f"Invalid schema version: {value!r}") from error
    if major < 1:
        raise ScenarioImportError("schema version must be at least 1")
    return major


def _decimal(value: object) -> Decimal:
    plain = _plain_scalar(value)
    if isinstance(plain, bool) or plain is None:
        raise ScenarioImportError(f"Expected a finite numeric value, got {plain!r}")
    try:
        result = Decimal(str(plain))
    except (InvalidOperation, ValueError) as error:
        raise ScenarioImportError(f"Expected a numeric value, got {plain!r}") from error
    if not result.is_finite():
        raise ScenarioImportError(f"Numeric value must be finite, got {plain!r}")
    return result


def _plain_scalar(value: object) -> Any:
    if pd.isna(value):
        raise ScenarioImportError("Decision matrix values cannot be null")
    item_method = getattr(value, "item", None)
    return item_method() if callable(item_method) else value


def _extra_fields(
    value: JsonObject,
    *,
    excluded: set[str],
) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in excluded}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
