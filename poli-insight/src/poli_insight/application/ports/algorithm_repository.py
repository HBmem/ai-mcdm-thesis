"""Persistence boundary for versioned algorithm registry entries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from poli_insight.domain.enum import AlgorithmRole


@dataclass(frozen=True, slots=True)
class AlgorithmImplementation:
    algorithm_implementation_id: str
    stable_key: str
    role: AlgorithmRole
    conceptual_method: str
    provider: str
    library_name: str
    library_version: str
    implementation_version: str
    adapter_version: str
    parameter_schema_json: Mapping[str, object]
    capabilities_json: Mapping[str, object]
    active: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameter_schema_json",
            MappingProxyType(dict(self.parameter_schema_json)),
        )
        object.__setattr__(
            self,
            "capabilities_json",
            MappingProxyType(dict(self.capabilities_json)),
        )


class AlgorithmRepository(Protocol):
    def get_many(
        self,
        implementation_ids: tuple[str, ...],
    ) -> tuple[AlgorithmImplementation, ...]:
        """Return registry entries matching the supplied identities."""
        ...
