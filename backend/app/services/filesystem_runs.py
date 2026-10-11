from __future__ import annotations

import json
import logging
import re
import csv
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FILESYSTEM_RUNS_ROOT = REPOSITORY_ROOT / "results" / "runs"
RUN_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")


def _set_csv_field_size_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_set_csv_field_size_limit()


def read_result_run_manifest(run_id: str) -> dict[str, Any] | None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        return None

    run_dir = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    try:
        run_dir.relative_to(FILESYSTEM_RUNS_ROOT.resolve())
    except ValueError:
        return None

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read saved analysis manifest: %s", manifest_path)
        return None
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        return None
    return manifest


def user_can_access_result_run(manifest: dict[str, Any], username: str | None, is_superuser: bool = False) -> bool:
    if is_superuser:
        return True
    if manifest.get("visibility") == "public":
        return True
    project = manifest.get("project")
    if not isinstance(project, dict) or not username:
        return False
    shared_with = manifest.get("shared_with_usernames")
    return project.get("owner_username") == username or (
        isinstance(shared_with, list) and username in shared_with
    )


@lru_cache(maxsize=12)
def _read_result_csv_cached(path: str, modified_ns: int, size: int) -> list[dict[str, str | None]]:
    del modified_ns, size
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
            return list(csv.DictReader(source))
    except (OSError, csv.Error) as exc:
        logger.exception("Could not read saved analysis artifact %s", path)
        raise HTTPException(status_code=500, detail="Saved analysis artifact could not be read.") from exc


def read_result_csv(run_id: str, relative_path: str) -> list[dict[str, str | None]]:
    if not RUN_ID_PATTERN.fullmatch(run_id) or read_result_run_manifest(run_id) is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    run_dir = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    try:
        run_dir.relative_to(FILESYSTEM_RUNS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Analysis run not found.") from exc
    target = (run_dir / relative_path).resolve()
    try:
        target.relative_to(run_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Analysis artifact not found.") from exc
    if not target.is_file():
        return []
    stat = target.stat()
    return _read_result_csv_cached(str(target), stat.st_mtime_ns, stat.st_size)


def read_result_csv_page(
    run_id: str,
    relative_path: str,
    *,
    limit: int,
    offset: int,
    species: str | None = None,
    gene_set_key: str | None = None,
    database: str | None = None,
    significant_only: bool = False,
) -> tuple[list[dict[str, str | None]], int]:
    if not RUN_ID_PATTERN.fullmatch(run_id) or read_result_run_manifest(run_id) is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    run_dir = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    target = (run_dir / relative_path).resolve()
    try:
        run_dir.relative_to(FILESYSTEM_RUNS_ROOT.resolve())
        target.relative_to(run_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Analysis artifact not found.") from exc
    if not target.is_file():
        return [], 0
    items: list[dict[str, str | None]] = []
    total = 0
    try:
        with target.open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                if species and row.get("species") != species:
                    continue
                if gene_set_key and gene_set_key not in {
                    row.get("gene_set_key"),
                    row.get("human_gene_set_key"),
                    row.get("mouse_gene_set_key"),
                }:
                    continue
                if database and row.get("database") != database:
                    continue
                if significant_only:
                    fdr_values = (
                        row.get("adjusted_p_value"),
                        row.get("human_fdr"),
                        row.get("mouse_fdr"),
                    )
                    is_significant = False
                    for value in fdr_values:
                        try:
                            if value is not None and float(value) <= 0.05:
                                is_significant = True
                                break
                        except ValueError:
                            continue
                    if not is_significant:
                        continue
                if offset <= total < offset + limit:
                    items.append(row)
                total += 1
    except (OSError, csv.Error) as exc:
        logger.exception("Could not page saved analysis artifact %s", target)
        raise HTTPException(status_code=500, detail="Saved analysis artifact could not be read.") from exc
    return items, total


def list_completed_result_manifests(
    project_name: str | None,
    owner_username: str | None,
) -> list[dict[str, Any]]:
    if not FILESYSTEM_RUNS_ROOT.is_dir():
        return []

    manifests = []
    for run_dir in FILESYSTEM_RUNS_ROOT.iterdir():
        if not run_dir.is_dir():
            continue
        manifest = read_result_run_manifest(run_dir.name)
        if manifest is None:
            continue
        project = manifest.get("project")
        phase3 = manifest.get("phase3")
        status = manifest.get("status")
        phase3_status = phase3.get("status") if isinstance(phase3, dict) else None
        project_owner = project.get("owner_username") if isinstance(project, dict) else None
        project_matches = project_name is None or project.get("name") == project_name if isinstance(project, dict) else False
        owner_matches = (
            owner_username is None
            or project_owner in (None, "")
            or project_owner == owner_username
            or user_can_access_result_run(manifest, owner_username)
        )
        if (
            isinstance(project, dict)
            and project_matches
            and owner_matches
            and isinstance(status, str)
            and status.upper() == "COMPLETED"
            and isinstance(phase3, dict)
            and isinstance(phase3_status, str)
            and phase3_status.upper() == "COMPLETED"
        ):
            manifests.append(manifest)
    return sorted(
        manifests,
        key=lambda manifest: str(manifest.get("created_at") or ""),
        reverse=True,
    )
