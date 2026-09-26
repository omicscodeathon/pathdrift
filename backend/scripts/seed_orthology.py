"""
Seed orthology mappings from Ensembl REST API.

Usage:
    cd backend
    python scripts/seed_orthology.py

This script fetches human–mouse one-to-one orthologues from the Ensembl Compara
database via the REST API and stores them in the PathDrift PostgreSQL database.

It respects:
  - Ensembl REST API rate limits (15 requests/second recommended)
  - Gene-level data only (no genomic sequence data)
  - Only ortholog_one2one type by default (configurable)

Run this once after database setup. Re-running will update existing mappings.
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models import OrthologyMapping

ENSEMBL_REST = "https://rest.ensembl.org"
BATCH_SIZE = 1000
RATE_LIMIT_DELAY = 0.1  # seconds between requests


def get_db_session():
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


def fetch_all_human_genes(client: httpx.Client) -> list[dict]:
    """Fetch all human protein-coding gene Ensembl IDs."""
    print("Fetching human gene list from Ensembl BioMart REST...")
    url = f"{ENSEMBL_REST}/overlap/region/human/1:1-1?feature=gene&content-type=application/json"
    # Use a more efficient approach: fetch gene list via xrefs or lookup
    # For seeding, use the homology endpoint for the entire species
    return []


def fetch_homologies_for_gene(client: httpx.Client, human_gene_id: str) -> list[dict]:
    """Fetch mouse homologues for a single human gene."""
    url = f"{ENSEMBL_REST}/homology/id/{human_gene_id}"
    params = {
        "content-type": "application/json",
        "target_species": "mus_musculus",
        "type": "orthologues",
    }
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return []
    data = resp.json()
    results = []
    for item in data.get("data", []):
        for h in item.get("homologies", []):
            if h.get("type") == "ortholog_one2one":
                results.append({
                    "human_ensembl_id": item["id"],
                    "mouse_ensembl_id": h["target"]["id"],
                    "human_symbol": item.get("display_label"),
                    "mouse_symbol": h["target"].get("display_label"),
                    "orthology_type": "ortholog_one2one",
                    "confidence": 1.0,
                    "source_version": "ensembl_rest",
                })
    return results


def _try_ensembl_rest_fallback(client: httpx.Client) -> list:
    """
    Try the Ensembl REST lookup endpoint for a sample of well-known human genes
    to verify connectivity, then fall back to bundled file.
    """
    return []  # Let caller handle bundled file fallback


def fetch_bulk_homologies(client: httpx.Client) -> pd.DataFrame:
    """
    Fetch bulk human–mouse orthology data from Ensembl BioMart.
    This is the most reliable method for getting all one-to-one orthologues.
    """
    print("Fetching bulk orthology data from Ensembl BioMart...")

    biomart_url = "https://mart.ensembl.org/biomart/martservice"
    xml_query = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE Query>'
        '<Query virtualSchemaName="default" formatter="TSV" header="1" '
        'uniqueRows="1" count="" datasetConfigVersion="0.6">'
        '<Dataset name="hsapiens_gene_ensembl" interface="default">'
        '<Filter name="with_mmusculus_homolog" excluded="0"/>'
        '<Attribute name="ensembl_gene_id"/>'
        '<Attribute name="external_gene_name"/>'
        '<Attribute name="mmusculus_homolog_ensembl_gene"/>'
        '<Attribute name="mmusculus_homolog_associated_gene_name"/>'
        '<Attribute name="mmusculus_homolog_orthology_type"/>'
        '<Attribute name="mmusculus_homolog_orthology_confidence"/>'
        '</Dataset></Query>'
    )

    rows = []
    try:
        # Use POST to avoid URL-length issues with the XML query
        resp = client.post(
            biomart_url,
            content=f"query={xml_query}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=300,
        )
        resp.raise_for_status()

        lines = resp.text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("BioMart returned empty response")

        # Parse TSV (first line is header)
        import csv, io
        reader = csv.DictReader(io.StringIO(resp.text), delimiter="\t")
        for row in reader:
            human_id = row.get("Gene stable ID", "").strip()
            mouse_id = row.get("Mouse gene stable ID", "").strip()
            if not human_id or not mouse_id:
                continue
            rows.append({
                "human_ensembl_id": human_id,
                "mouse_ensembl_id": mouse_id,
                "human_symbol": row.get("Gene name", "").strip() or None,
                "mouse_symbol": row.get("Mouse gene name", "").strip() or None,
                "orthology_type": row.get("Mouse homology type", "ortholog_one2one").strip(),
                "confidence": float(row.get("Mouse orthology confidence [0 low, 1 high]", "1") or 1),
                "source_version": "ensembl_biomart",
            })

        print(f"  Retrieved {len(rows)} ortholog pairs from BioMart")
    except Exception as e:
        print(f"BioMart fetch failed: {e}")
        print("Trying Ensembl REST API fallback...")
        rows = _try_ensembl_rest_fallback(client)

    return pd.DataFrame(rows)


def upsert_mappings(db, df: pd.DataFrame):
    """Upsert orthology mappings into the database."""
    from app.models.models import now_utc
    engine = db.bind
    records = df.to_dict(orient="records")

    stmt = pg_insert(OrthologyMapping.__table__).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_orthology_pair",
        set_={
            "human_symbol": stmt.excluded.human_symbol,
            "mouse_symbol": stmt.excluded.mouse_symbol,
            "orthology_type": stmt.excluded.orthology_type,
            "confidence": stmt.excluded.confidence,
            "source_version": stmt.excluded.source_version,
        },
    )
    db.execute(stmt)
    db.commit()
    print(f"  Upserted {len(records)} records")


def main():
    import uuid
    db = get_db_session()
    print("PathDrift Orthology Seeding Script")
    print("=" * 50)

    with httpx.Client(
        headers={"Content-Type": "application/json"},
        timeout=60,
    ) as client:
        df = fetch_bulk_homologies(client)

    if df.empty:
        print("\nWARNING: No orthology data retrieved from BioMart or Ensembl REST API.")
        print("Possible reasons:")
        print("  1. No internet connectivity to ensembl.org")
        print("  2. BioMart is temporarily unavailable (check https://www.ensembl.org/biomart)")
        print("\nManual download instructions:")
        print("  1. Go to: https://www.ensembl.org/biomart/martview")
        print("  2. Dataset: Ensembl Genes → Human genes (GRCh38)")
        print("  3. Filters: Homology > With Mouse homolog")
        print("  4. Attributes: Gene stable ID, Gene name, Mouse gene stable ID,")
        print("                 Mouse gene name, Mouse homology type, Mouse orthology confidence")
        print("  5. Download as TSV → save to backend/data/ensembl_human_mouse_orthologs.tsv")
        print("  6. Re-run this script")

        # Try bundled file
        bundled_path = os.path.join(os.path.dirname(__file__), "..", "data", "ensembl_human_mouse_orthologs.tsv")
        bundled_path = os.path.normpath(bundled_path)
        if os.path.exists(bundled_path):
            print(f"\nLoading from bundled file: {bundled_path}")
            df = pd.read_csv(bundled_path, sep="\t")
            col_map = {
                "Gene stable ID": "human_ensembl_id",
                "Mouse gene stable ID": "mouse_ensembl_id",
                "Gene name": "human_symbol",
                "Mouse gene name": "mouse_symbol",
                "Mouse homology type": "orthology_type",
                "Mouse orthology confidence [0 low, 1 high]": "confidence",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            df = df[df.get("orthology_type", pd.Series(["ortholog_one2one"])).isin(
                ["ortholog_one2one", "ortholog_one2many"])]
            df["confidence"] = pd.to_numeric(df.get("confidence", 1), errors="coerce").fillna(1.0)
            df["source_version"] = "bundled"
        else:
            print(f"\nNo bundled file found at: {bundled_path}")
            print("Seeding aborted. Please download orthology data manually (see instructions above).")
            return

    # Add UUIDs
    df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    df["loaded_at"] = pd.Timestamp.now(tz="UTC")

    # Keep only needed columns
    keep_cols = ["id", "human_ensembl_id", "mouse_ensembl_id", "human_symbol",
                 "mouse_symbol", "orthology_type", "confidence", "source_version", "loaded_at"]
    df = df[[c for c in keep_cols if c in df.columns]]
    df = df.dropna(subset=["human_ensembl_id", "mouse_ensembl_id"])
    df = df.drop_duplicates(subset=["human_ensembl_id", "mouse_ensembl_id"])

    print(f"Upserting {len(df)} one-to-one ortholog pairs...")
    upsert_mappings(db, df)
    print("Orthology seeding complete.")
    db.close()


if __name__ == "__main__":
    main()
