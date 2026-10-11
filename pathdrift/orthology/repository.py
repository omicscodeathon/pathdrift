from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session


def persist_orthology(session: Session, run_id: str, mappings: pd.DataFrame, metadata: dict, primary_ids: set[tuple[str, str]]) -> None:
    from app.models import OrthologyMapping, RunOrthologyMapping

    source = str(metadata["source"])
    source_version = str(metadata["source_version"])
    source_metadata = {key: value for key, value in metadata.items() if key not in {"retrieved_at"}}
    rows = []
    for record in mappings.to_dict(orient="records"):
        confidence = record.get("confidence")
        confidence = None if pd.isna(confidence) else float(confidence)
        pair = (str(record["human_ensembl_id"]), str(record["mouse_ensembl_id"]))
        rows.append({
            "id": str(uuid.uuid4()),
            "human_ensembl_id": pair[0],
            "mouse_ensembl_id": pair[1],
            "human_symbol": record.get("human_symbol") or None,
            "mouse_symbol": record.get("mouse_symbol") or None,
            "orthology_type": str(record["orthology_type"]),
            "confidence": confidence,
            "source": source,
            "source_version": source_version,
            "source_metadata": source_metadata,
        })
    for offset in range(0, len(rows), 1000):
        batch = rows[offset:offset + 1000]
        statement = pg_insert(OrthologyMapping.__table__).values(batch)
        statement = statement.on_conflict_do_update(
            constraint="uq_orthology_source_pair_version",
            set_={
                "human_symbol": statement.excluded.human_symbol,
                "mouse_symbol": statement.excluded.mouse_symbol,
                "orthology_type": statement.excluded.orthology_type,
                "confidence": statement.excluded.confidence,
                "source_metadata": statement.excluded.source_metadata,
            },
        )
        session.execute(statement)

    session.execute(delete(RunOrthologyMapping).where(RunOrthologyMapping.run_id == run_id))
    run_rows = []
    for record in mappings.to_dict(orient="records"):
        human_id, mouse_id = str(record["human_ensembl_id"]), str(record["mouse_ensembl_id"])
        confidence = record.get("confidence")
        run_rows.append(RunOrthologyMapping(
            run_id=run_id,
            human_ensembl_id=human_id,
            mouse_ensembl_id=mouse_id,
            human_original_id=record.get("human_original_id"),
            mouse_original_id=record.get("mouse_original_id"),
            human_symbol=record.get("human_symbol") or None,
            mouse_symbol=record.get("mouse_symbol") or None,
            orthology_type=str(record["orthology_type"]),
            confidence=None if pd.isna(confidence) else float(confidence),
            source=source,
            source_version=source_version,
            source_metadata=source_metadata,
            is_primary=(human_id, mouse_id) in primary_ids,
        ))
    for offset in range(0, len(run_rows), 1000):
        session.add_all(run_rows[offset:offset + 1000])
        session.flush()
