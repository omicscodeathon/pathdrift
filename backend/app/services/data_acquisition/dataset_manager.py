from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "pathdrift"
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = DATA_ROOT / "processed"
METADATA_ROOT = DATA_ROOT / "metadata"
MANIFEST_ROOT = DATA_ROOT / "manifests"
LOG_ROOT = DATA_ROOT / "logs"
FRONTEND_PUBLIC_ROOT = Path(__file__).resolve().parents[4] / "frontend" / "public" / "data" / "pathdrift"
FRONTEND_RAW_ROOT = FRONTEND_PUBLIC_ROOT / "raw"
FRONTEND_PROCESSED_ROOT = FRONTEND_PUBLIC_ROOT / "processed"


def ensure_data_directories() -> Dict[str, str]:
    directories = {
        "root": str(DATA_ROOT),
        "raw": str(RAW_ROOT),
        "processed": str(PROCESSED_ROOT),
        "metadata": str(METADATA_ROOT),
        "manifests": str(MANIFEST_ROOT),
        "logs": str(LOG_ROOT),
        "frontend_root": str(FRONTEND_PUBLIC_ROOT),
        "frontend_raw": str(FRONTEND_RAW_ROOT),
        "frontend_processed": str(FRONTEND_PROCESSED_ROOT),
    }
    for path in directories.values():
        Path(path).mkdir(parents=True, exist_ok=True)

    for subdir in ["gtex", "gdc", "geo", "orthology", "human", "mouse"]:
        (RAW_ROOT / subdir).mkdir(parents=True, exist_ok=True)
        (PROCESSED_ROOT / subdir).mkdir(parents=True, exist_ok=True)
        (FRONTEND_RAW_ROOT / subdir).mkdir(parents=True, exist_ok=True)
        (FRONTEND_PROCESSED_ROOT / subdir).mkdir(parents=True, exist_ok=True)

    return directories


def mirror_to_frontend_visible_store(source_path: Path | str) -> Path:
    ensure_data_directories()
    source_path = Path(source_path)
    if not source_path.is_absolute():
        candidate = DATA_ROOT / source_path
        if candidate.exists():
            source_path = candidate
        else:
            source_path = (Path.cwd() / source_path).resolve()

    try:
        relative_path = source_path.relative_to(DATA_ROOT)
    except ValueError:
        relative_path = Path(source_path.name)

    frontend_target = FRONTEND_PUBLIC_ROOT / relative_path
    frontend_target.parent.mkdir(parents=True, exist_ok=True)
    frontend_target.write_bytes(source_path.read_bytes())
    return frontend_target


def write_manifest(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_data_directories()
    manifest_path = MANIFEST_ROOT / "dataset_manifest.json"
    payload = {
        **payload,
        "created_at": payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"path": str(manifest_path), "created_at": payload["created_at"]}


def list_acquired_datasets() -> List[Dict[str, Any]]:
    manifest_path = MANIFEST_ROOT / "dataset_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        datasets = []
        for item in manifest.get("datasets", []):
            normalized = dict(item)
            dataset_id = (
                normalized.get("id")
                or normalized.get("dataset_id")
                or normalized.get("datasetId")
                or normalized.get("accession")
                or normalized.get("name")
                or f"dataset-{len(datasets)}"
            )
            normalized["id"] = str(dataset_id)
            normalized["dataset_id"] = str(dataset_id)
            normalized["status"] = normalized.get("status") or "ready"
            normalized["created_at"] = normalized.get("created_at") or datetime.now(timezone.utc).isoformat()
            datasets.append(normalized)
        return datasets
    except json.JSONDecodeError:
        return []
