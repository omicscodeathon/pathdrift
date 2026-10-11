from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import runs


class FailingDatabase:
    async def execute(self, statement):
        raise SQLAlchemyError("database unavailable")


def test_saved_runs_falls_back_to_completed_filesystem_manifests(monkeypatch):
    manifest = {
        "run_id": "1c782941-d15c-4c3a-a291-5172f1d23937",
        "project": {"name": "BRCA Network Drift 2026"},
        "created_at": "2026-10-05T17:34:12+00:00",
        "updated_at": "2026-10-06T17:04:09+00:00",
        "datasets": [{}, {}],
    }
    monkeypatch.setattr(runs, "list_completed_result_manifests", lambda *_: [manifest])
    user = SimpleNamespace(id="user-id", username="researcher2026", is_superuser=False)

    result = asyncio.run(runs.list_saved_runs(current_user=user, db=FailingDatabase()))

    assert result == [{
        "id": manifest["run_id"],
        "project_name": "BRCA Network Drift 2026",
        "status": "COMPLETED",
        "stage": "ANALYSIS",
        "created_at": manifest["created_at"],
        "completed_at": manifest["updated_at"],
        "error_message": None,
        "datasets": 2,
    }]
