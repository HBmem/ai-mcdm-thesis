from __future__ import annotations

import uuid

def new_id(prefix: str) -> str:
    """Create a stable, unique ID for prototype records."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"