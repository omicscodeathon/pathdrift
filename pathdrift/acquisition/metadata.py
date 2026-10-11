from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def read_sample_metadata(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    separator = "\t" if source.suffix.lower() in {".tsv", ".txt"} or ".tsv" in source.suffixes or ".txt" in source.suffixes else ","
    compression = "gzip" if source.suffix.lower() == ".gz" else "infer"
    frame = pd.read_csv(source, sep=separator, compression=compression, dtype=str, keep_default_na=False)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "sample_id" not in frame.columns:
        raise ValueError(f"Metadata file is missing sample_id: {source}")
    frame["sample_id"] = frame["sample_id"].astype(str).str.strip()
    if frame["sample_id"].eq("").any():
        raise ValueError(f"Metadata file contains empty sample IDs: {source}")
    if frame["sample_id"].duplicated().any():
        duplicates = sorted(frame.loc[frame["sample_id"].duplicated(False), "sample_id"].unique())
        raise ValueError(f"Metadata file contains duplicate sample IDs: {duplicates[:10]}")
    return frame


def sample_metadata_record(row: pd.Series, *, species: str, tissue: str, accession: str) -> dict[str, Any]:
    record = {str(key): (None if pd.isna(value) or value == "" else value) for key, value in row.items()}
    record.update({"species": species, "tissue": tissue, "accession": accession})
    return record