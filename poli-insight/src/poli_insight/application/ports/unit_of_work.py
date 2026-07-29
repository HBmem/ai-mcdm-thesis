from __future__ import annotations

from typing import Protocol

from poli_insight.application.ports.audit_repository import AuditEventRepository

class UnitOfWork(Protocol):
    #TODO: Import repositories
    audits_events: AuditEventRepository

    def __enter__(self) -> "UnitOfWork":
        ...
    
    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...