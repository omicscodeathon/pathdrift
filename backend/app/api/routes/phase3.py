from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.services.filesystem_runs import (
    FILESYSTEM_RUNS_ROOT,
    read_result_csv,
    read_result_run_manifest,
    user_can_access_result_run,
)
from app.models import (
    AnalysisRun,
    Gene,
    Project,
    RunDifferentialExpression,
    RunFigure,
    RunGeneNetwork,
    RunModuleGene,
    RunNetworkEdge,
    RunNetworkModule,
    RunNetworkNode,
    User,
)

router = APIRouter()
PUBLIC_RESULT_SUFFIXES = {".csv", ".json", ".png", ".svg", ".pdf", ".txt"}


def _run_artifact_directory(run_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", run_id):
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    root = FILESYSTEM_RUNS_ROOT.resolve()
    directory = (root / run_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Analysis run not found.") from exc
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="Saved result artifacts are not available for this run.")
    return directory


def _list_public_run_artifacts(run_directory: Path) -> list[dict[str, Any]]:
    items = []
    for path in run_directory.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in PUBLIC_RESULT_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.relative_to(run_directory).parts):
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(run_directory)
        except ValueError:
            continue
        relative_path = resolved.relative_to(run_directory).as_posix()
        items.append({
            "path": relative_path,
            "name": path.name,
            "section": path.relative_to(run_directory).parts[0] if len(path.relative_to(run_directory).parts) > 1 else "Run summary",
            "size_bytes": path.stat().st_size,
        })
    return sorted(items, key=lambda item: (item["section"].casefold(), item["path"].casefold()))


async def _owned_run(run_id: str, db: AsyncSession, user: User) -> AnalysisRun | dict[str, Any]:
    manifest = read_result_run_manifest(run_id)
    project = manifest.get("project") if manifest else None
    phase3 = manifest.get("phase3") if manifest else None
    if (
        isinstance(project, dict)
        and user_can_access_result_run(manifest, user.username, user.is_superuser)
        and isinstance(phase3, dict)
        and str(phase3.get("status", "")).upper() == "COMPLETED"
    ):
        return manifest

    statement = (
        select(AnalysisRun)
        .join(Project, Project.id == AnalysisRun.project_id)
        .where(AnalysisRun.id == run_id)
    )
    if not user.is_superuser:
        statement = statement.where(Project.owner_id == user.id)
    run = (await db.execute(statement)).scalar_one_or_none()
    if run is not None:
        return run

    raise HTTPException(status_code=404, detail="Analysis run not found.")


@router.get("/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    directory = _run_artifact_directory(run_id)
    items = _list_public_run_artifacts(directory)
    return {"run_id": run_id, "total": len(items), "items": items}


@router.get("/{run_id}/artifacts/download-all")
async def download_all_run_artifacts(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    directory = _run_artifact_directory(run_id)
    items = _list_public_run_artifacts(directory)
    if not items:
        raise HTTPException(status_code=404, detail="No downloadable result artifacts are available.")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in items:
            bundle.write(directory / item["path"], arcname=item["path"])
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="pathdrift-results-{run_id}.zip"'},
    )


@router.get("/{run_id}/artifacts/{artifact_path:path}")
async def download_run_artifact(
    run_id: str,
    artifact_path: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    directory = _run_artifact_directory(run_id)
    allowed_paths = {item["path"] for item in _list_public_run_artifacts(directory)}
    if artifact_path not in allowed_paths:
        raise HTTPException(status_code=404, detail="Result artifact not found.")
    target = (directory / artifact_path).resolve()
    try:
        target.relative_to(directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Result artifact not found.") from exc
    if target.suffix.lower() not in PUBLIC_RESULT_SUFFIXES or not target.is_file():
        raise HTTPException(status_code=404, detail="Result artifact not found.")
    return FileResponse(target, filename=target.name)


def _page(total: int, limit: int, offset: int, items: list[dict[str, Any]]) -> dict:
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def _deg_artifact_directory(run_id: str, species: str, comparison: str | None) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", run_id) or species not in {"human", "mouse"}:
        raise HTTPException(status_code=404, detail="DEG artifacts not found.")
    relative_directory = Path("deg") / species
    if species == "mouse" and comparison and "cross_study_exploratory" in comparison:
        relative_directory /= "cross_study_exploratory"
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    directory = (run_directory / relative_directory).resolve()
    try:
        directory.relative_to(run_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="DEG artifacts not found.") from exc
    return directory


@router.get("/{run_id}/deg/{species}/artifacts")
async def list_run_deg_artifacts(
    run_id: str,
    species: str,
    comparison: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    directory = _deg_artifact_directory(run_id, species, comparison)
    if not directory.is_dir():
        return {"items": []}
    items = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".csv", ".json", ".png", ".svg"}:
            continue
        try:
            path.resolve().relative_to(directory.resolve())
        except ValueError:
            continue
        items.append(path.name)
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    shared_summary = run_directory / "deg" / "network_module_summary.json"
    if shared_summary.is_file():
        items.append(shared_summary.name)
    return {
        "items": sorted(set(items))
    }


@router.get("/{run_id}/deg/{species}/artifacts/{artifact_name}")
async def get_run_deg_artifact(
    run_id: str,
    species: str,
    artifact_name: str,
    comparison: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    if (
        not artifact_name
        or Path(artifact_name).name != artifact_name
        or Path(artifact_name).suffix.lower() not in {".csv", ".json", ".png", ".svg"}
    ):
        raise HTTPException(status_code=404, detail="DEG artifact not found.")
    directory = _deg_artifact_directory(run_id, species, comparison)
    artifact_directory = directory
    if artifact_name == "network_module_summary.json":
        artifact_directory = directory.parent.parent if directory.name == "cross_study_exploratory" else directory.parent
    artifact_path = (artifact_directory / artifact_name).resolve()
    try:
        artifact_path.relative_to(artifact_directory.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="DEG artifact not found.") from exc
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="DEG artifact not found.")
    return FileResponse(artifact_path, filename=artifact_name)


def _csv_number(value: str | None, *, integer: bool = False) -> int | float | None:
    if value is None or not value.strip():
        return None
    try:
        return int(float(value)) if integer else float(value)
    except ValueError:
        return None


def _csv_bool(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"true", "1", "yes"})


def _csv_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _filesystem_networks(run_id: str) -> list[dict[str, Any]]:
    rows = read_result_csv(run_id, "networks/network_summary.csv")
    networks = []
    for row in rows:
        name = f"{row.get('species')}_{row.get('disease_state')}"
        networks.append({
            "network_id": row.get("network_id"),
            "dataset_id": row.get("dataset_id"),
            "name": name,
            "species": row.get("species"),
            "disease_state": row.get("disease_state"),
            "method": row.get("method"),
            "summary": {
                "n_nodes": _csv_number(row.get("n_nodes"), integer=True),
                "n_edges": _csv_number(row.get("n_edges"), integer=True),
                "density": _csv_number(row.get("density")),
                "average_degree": _csv_number(row.get("average_degree")),
                "average_clustering": _csv_number(row.get("average_clustering")),
                "connected_components": _csv_number(row.get("connected_components"), integer=True),
                "largest_component_size": _csv_number(row.get("largest_component_size"), integer=True),
                "average_absolute_edge_weight": _csv_number(row.get("average_absolute_edge_weight")),
                "top_central_genes": _csv_json(row.get("top_central_genes"), []),
                "centrality": _csv_json(row.get("centrality"), {}),
                "degree_distribution": _csv_json(row.get("degree_distribution"), {}),
                "filtering": _csv_json(row.get("filtering"), {}),
                "sample_ids": _csv_json(row.get("sample_ids"), []),
                "sample_selection": _csv_json(row.get("sample_selection"), {}),
                "method": row.get("method"),
            },
            "configuration": {"correlation": _csv_json(row.get("filtering"), {})},
        })
    return networks


def _filesystem_network(run_id: str, network_id: str) -> dict[str, Any]:
    network = next(
        (item for item in _filesystem_networks(run_id) if item["network_id"] == network_id),
        None,
    )
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found.")
    network["module_count"] = len(_filesystem_modules(run_id, network["species"], network_id))
    network["figures"] = []
    return network


def _filesystem_nodes(run_id: str, network: dict[str, Any], limit: int, offset: int) -> dict:
    rows = read_result_csv(run_id, f"networks/{network['name']}_nodes.csv")
    items = [{
        "gene_id": row.get("gene_id"),
        "ensembl_id": row.get("gene_id"),
        "gene_symbol": row.get("gene_symbol") or None,
        "degree": _csv_number(row.get("degree"), integer=True) or 0,
        "weighted_degree": _csv_number(row.get("weighted_degree")) or 0,
        "betweenness_centrality": _csv_number(row.get("betweenness_centrality")),
        "closeness_centrality": _csv_number(row.get("closeness_centrality")),
        "eigenvector_centrality": _csv_number(row.get("eigenvector_centrality")),
        "module_id": f"{network['network_id']}::{row['module_id']}" if row.get("module_id") else None,
    } for row in rows]
    items.sort(key=lambda item: (-item["degree"], -item["weighted_degree"], item["ensembl_id"] or ""))
    return _page(len(items), limit, offset, items[offset:offset + limit])


def _filesystem_edges(run_id: str, network: dict[str, Any], limit: int, offset: int) -> dict:
    name = network["name"]
    paths = [f"networks/{name}_edges.csv", f"networks/human_healthy/{name}_edges.csv"]
    rows = next((items for items in (read_result_csv(run_id, path) for path in paths) if items), [])
    items = [{
        "source_gene_id": row.get("source_gene"),
        "source_ensembl_id": row.get("source_gene"),
        "target_gene_id": row.get("target_gene"),
        "target_ensembl_id": row.get("target_gene"),
        "correlation": _csv_number(row.get("correlation")) or 0,
        "absolute_correlation": _csv_number(row.get("absolute_correlation")) or 0,
        "pvalue": _csv_number(row.get("p_value")),
        "adjusted_p_value": _csv_number(row.get("adjusted_p_value")),
        "weight": _csv_number(row.get("weight")) or 0,
    } for row in rows]
    items.sort(key=lambda item: item["adjusted_p_value"] if item["adjusted_p_value"] is not None else float("inf"))
    return _page(len(items), limit, offset, items[offset:offset + limit])


def _filesystem_modules(
    run_id: str,
    species: str | None = None,
    network_id: str | None = None,
) -> list[dict[str, Any]]:
    networks = {item["network_id"]: item for item in _filesystem_networks(run_id)}
    species_values = [species] if species else ["human", "mouse"]
    mouse_deg_by_gene = {
        str(row.get("gene_id")): row
        for row in read_result_csv(
            run_id, "deg/mouse/cross_study_exploratory/all_genes.csv"
        )
        if row.get("gene_id")
    } if "mouse" in species_values else {}
    modules: list[dict[str, Any]] = []
    for species_value in species_values:
        module_gene_rows = (
            read_result_csv(run_id, f"modules/{species_value}/module_genes.csv")
            if species_value == "mouse" and mouse_deg_by_gene
            else []
        )
        module_genes_by_key: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        for gene_row in module_gene_rows:
            key = (gene_row.get("network_name") or "", gene_row.get("module_id") or "")
            module_genes_by_key.setdefault(key, []).append(gene_row)
        for row in read_result_csv(run_id, f"modules/{species_value}/modules.csv"):
            network = next((item for item in networks.values() if item["name"] == row.get("network_name")), None)
            if network is None or (network_id and network["network_id"] != network_id):
                continue
            module_key = row.get("module_id") or ""
            statistics = {
                key: _csv_number(value) if key not in {"network_name", "module_id", "top_central_genes", "detection_method"}
                else _csv_json(value, []) if key == "top_central_genes"
                else value
                for key, value in row.items()
            }
            if species_value == "mouse" and mouse_deg_by_gene:
                tested_rows = [
                    mouse_deg_by_gene[str(gene_row["gene_id"])]
                    for gene_row in module_genes_by_key.get(
                        (row.get("network_name") or "", module_key), []
                    )
                    if gene_row.get("gene_id")
                    and str(gene_row["gene_id"]) in mouse_deg_by_gene
                ]
                significant_rows = [
                    deg_row for deg_row in tested_rows
                    if _csv_bool(deg_row.get("significant"))
                ]
                upregulated = sum(
                    (deg_row.get("direction") or "").strip().lower()
                    in {"up", "upregulated"}
                    for deg_row in significant_rows
                )
                downregulated = sum(
                    (deg_row.get("direction") or "").strip().lower()
                    in {"down", "downregulated"}
                    for deg_row in significant_rows
                )
                statistics.update({
                    "deg_gene_count": len(significant_rows),
                    "deg_gene_percent": (
                        100.0 * len(significant_rows) / statistics["size"]
                        if statistics.get("size") else None
                    ),
                    "upregulated_deg_count": upregulated,
                    "downregulated_deg_count": downregulated,
                    "non_deg_gene_count": len(tested_rows) - len(significant_rows),
                    "deg_genes_tested": len(tested_rows),
                    "deg_comparison": "cancer_vs_healthy_cross_study_exploratory",
                })
            modules.append({
                "module_id": f"{network['network_id']}::{module_key}",
                "module_key": module_key,
                "network_id": network["network_id"],
                "network_name": network["name"],
                "species": species_value,
                "size": _csv_number(row.get("size"), integer=True) or 0,
                "detection_method": row.get("detection_method"),
                "parameters": {
                    "resolution": _csv_number(row.get("resolution")),
                    "min_module_size": _csv_number(row.get("min_module_size"), integer=True),
                },
                "statistics": statistics,
            })
    return modules


def _parse_filesystem_module_id(module_id: str) -> tuple[str, str] | None:
    network_id, separator, module_key = module_id.partition("::")
    if not separator or not re.fullmatch(r"[0-9a-fA-F-]{36}", network_id) or not module_key:
        return None
    return network_id, module_key


def _filesystem_module(run_id: str, module_id: str) -> dict[str, Any]:
    parsed = _parse_filesystem_module_id(module_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    network_id, module_key = parsed
    module = next(
        (item for item in _filesystem_modules(run_id) if item["network_id"] == network_id and item["module_key"] == module_key),
        None,
    )
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    return module


def _filesystem_deg_page(
    run_id: str,
    species: str | None,
    comparison: str | None,
    significant_only: bool,
    limit: int,
    offset: int,
) -> dict:
    species_values = [species] if species else ["human", "mouse"]
    entries = []
    for species_value in species_values:
        if species_value not in {"human", "mouse"}:
            continue
        if significant_only and species_value == "human":
            significant_path = f"deg/{species_value}/significant_genes.csv"
            paths = [significant_path] if read_result_csv(run_id, significant_path) else [
                f"deg/{species_value}/all_genes.csv"
            ]
        else:
            paths = (
                [f"deg/{species_value}/all_genes.csv", f"deg/{species_value}/cross_study_exploratory/all_genes.csv"]
                if species_value == "mouse"
                else [f"deg/{species_value}/all_genes.csv"]
            )
        for path in paths:
            rows = read_result_csv(run_id, path)
            for row in rows:
                pvalue = _csv_number(row.get("pvalue"))
                adjusted_p_value = _csv_number(row.get("adjusted_p_value"))
                statistic = _csv_number(row.get("statistic"))
                testable = pvalue is not None and adjusted_p_value is not None and statistic is not None
                raw_direction = (row.get("direction") or "").upper()
                direction = (
                    "not_testable" if not testable
                    else "up" if "UP" in raw_direction
                    else "down" if "DOWN" in raw_direction
                    else "not_significant"
                )
                item = {
                    "id": row.get("gene_id"),
                    "gene_id": row.get("gene_id"),
                    "ensembl_id": row.get("gene_id"),
                    "gene_symbol": row.get("gene_symbol") or None,
                    "species": species_value,
                    "comparison": row.get("comparison") or (
                        "cancer_vs_healthy_cross_study_exploratory"
                        if "cross_study_exploratory" in path
                        else "cancer_vs_healthy"
                    ),
                    "log2fc": _csv_number(row.get("log2fc")),
                    "pvalue": pvalue,
                    "adjusted_p_value": adjusted_p_value,
                    "statistic": statistic,
                    "base_mean": _csv_number(row.get("base_mean")),
                    "average_expression": _csv_number(row.get("average_expression")),
                    "direction": direction,
                    "significant": _csv_bool(row.get("significant")),
                    "testable": testable,
                    "method": row.get("method") or "Not provided",
                    "thresholds": {},
                }
                if comparison is not None and item["comparison"] != comparison:
                    continue
                if significant_only and not item["significant"]:
                    continue
                entries.append(item)
    entries.sort(key=lambda item: (
        item["adjusted_p_value"] if item["adjusted_p_value"] is not None else float("inf"),
        item["ensembl_id"] or "",
    ))
    return _page(len(entries), limit, offset, entries[offset:offset + limit])


async def _deg_page(
    run_id: str,
    db: AsyncSession,
    *,
    species: str | None,
    significant_only: bool,
    comparison: str | None,
    limit: int,
    offset: int,
) -> dict:
    statement = (
        select(RunDifferentialExpression, Gene)
        .join(Gene, Gene.id == RunDifferentialExpression.gene_id)
        .where(RunDifferentialExpression.run_id == run_id)
    )
    count_statement = select(func.count()).select_from(RunDifferentialExpression).where(
        RunDifferentialExpression.run_id == run_id
    )
    if species is not None:
        statement = statement.where(RunDifferentialExpression.species == species)
        count_statement = count_statement.where(RunDifferentialExpression.species == species)
    if significant_only:
        statement = statement.where(RunDifferentialExpression.significant.is_(True))
        count_statement = count_statement.where(RunDifferentialExpression.significant.is_(True))
    if comparison is not None:
        statement = statement.where(RunDifferentialExpression.comparison == comparison)
        count_statement = count_statement.where(RunDifferentialExpression.comparison == comparison)
    total = int((await db.execute(count_statement)).scalar_one())
    records = (await db.execute(
        statement.order_by(
            RunDifferentialExpression.adjusted_p_value.asc().nulls_last(),
            Gene.ensembl_id,
        ).limit(limit).offset(offset)
    )).all()
    return _page(total, limit, offset, [{
        "id": de.id,
        "gene_id": gene.id,
        "ensembl_id": gene.ensembl_id,
        "gene_symbol": gene.gene_symbol,
        "species": de.species,
        "comparison": de.comparison,
        "log2fc": de.log2fc,
        "pvalue": de.pvalue,
        "adjusted_p_value": de.adjusted_p_value,
        "statistic": de.statistic,
        "base_mean": de.base_mean,
        "average_expression": de.average_expression,
        "direction": de.direction,
        "significant": de.significant,
        "method": de.method,
        "thresholds": de.thresholds,
    } for de, gene in records])


@router.get("/{run_id}/deg")
async def get_run_deg(
    run_id: str,
    species: str | None = None,
    comparison: str | None = None,
    significant: bool = False,
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return _filesystem_deg_page(run_id, species, comparison, significant, limit, offset)
    return await _deg_page(
        run_id, db, species=species, significant_only=significant,
        comparison=comparison, limit=limit, offset=offset,
    )


@router.get("/{run_id}/integrated")
async def get_integrated_results(
    run_id: str,
    species: str = Query(..., pattern="^(human|mouse)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        rows = read_result_csv(run_id, f"integrated/{species}_gene_integration.csv")
        items = []
        for row in rows[offset:offset + limit]:
            direction = str(row.get("direction") or "").lower()
            items.append({
                "gene_id": row.get("gene_id"),
                "ensembl_id": row.get("gene_id"),
                "gene_symbol": row.get("gene_symbol") or None,
                "species": row.get("species") or species,
                "comparison": row.get("comparison_status") or "saved",
                "log2fc": _csv_number(row.get("log2fc")),
                "pvalue": _csv_number(row.get("pvalue")),
                "adjusted_p_value": _csv_number(row.get("adjusted_p_value")),
                "base_mean": _csv_number(row.get("base_mean")),
                "average_expression": _csv_number(row.get("average_expression")),
                "direction": direction,
                "significant": _csv_bool(row.get("significant")),
                "method": row.get("method"),
                "degree": _csv_number(row.get("degree"), integer=True),
                "weighted_degree": _csv_number(row.get("weighted_degree")),
                "betweenness_centrality": _csv_number(row.get("betweenness_centrality")),
                "closeness_centrality": _csv_number(row.get("closeness_centrality")),
                "eigenvector_centrality": _csv_number(row.get("eigenvector_centrality")),
                "module_id": row.get("module_id") or None,
            })
        return _page(len(rows), limit, offset, items)
    return _page(0, limit, offset, [])


@router.get("/{run_id}/deg/{species}/significant")
async def get_significant_run_deg(
    run_id: str,
    species: str,
    comparison: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return _filesystem_deg_page(run_id, species, comparison, True, limit, offset)
    return await _deg_page(
        run_id, db, species=species, significant_only=True,
        comparison=comparison, limit=limit, offset=offset,
    )


@router.get("/{run_id}/deg/{species}")
async def get_species_run_deg(
    run_id: str,
    species: str,
    comparison: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return _filesystem_deg_page(run_id, species, comparison, False, limit, offset)
    return await _deg_page(
        run_id, db, species=species, significant_only=False,
        comparison=comparison, limit=limit, offset=offset,
    )


@router.get("/{run_id}/deg/{species}/tables/{table_name}")
async def get_run_deg_table(
    run_id: str,
    species: str,
    table_name: str,
    comparison: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_run(run_id, db, current_user)
    if species == "mouse" and comparison == "cancer_vs_healthy_cross_study_exploratory":
        relative_path = Path("deg") / "mouse" / "cross_study_exploratory" / table_name
        allowed_tables = {"all_genes.csv", "significant_genes.csv", "gene_mapping.csv", "sample_metadata.csv"}
    elif species == "human" and comparison is None:
        relative_path = Path("deg") / "human" / table_name
        allowed_tables = {"all_genes.csv", "significant_genes.csv"}
    else:
        raise HTTPException(status_code=404, detail="DEG table not found.")
    if table_name not in allowed_tables:
        raise HTTPException(status_code=404, detail="DEG table not found.")
    rows = read_result_csv(run_id, str(relative_path))
    return _page(len(rows), limit, offset, rows[offset:offset + limit])


@router.get("/{run_id}/networks")
async def list_run_networks(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return {"items": _filesystem_networks(run_id)}
    networks = (await db.execute(
        select(RunGeneNetwork).where(RunGeneNetwork.run_id == run_id).order_by(RunGeneNetwork.name)
    )).scalars().all()
    return {"items": [{
        "network_id": item.id,
        "dataset_id": item.dataset_id,
        "name": item.name,
        "species": item.species,
        "disease_state": item.disease_state,
        "method": item.method,
        "summary": item.summary,
        "configuration": item.configuration,
    } for item in networks]}


async def _owned_network(run_id: str, network_id: str, db: AsyncSession) -> RunGeneNetwork:
    network = (await db.execute(select(RunGeneNetwork).where(
        RunGeneNetwork.id == network_id,
        RunGeneNetwork.run_id == run_id,
    ))).scalar_one_or_none()
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found.")
    return network


@router.get("/{run_id}/networks/{network_id}")
async def get_run_network(
    run_id: str,
    network_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return _filesystem_network(run_id, network_id)
    network = await _owned_network(run_id, network_id, db)
    modules = (await db.execute(
        select(RunNetworkModule).where(RunNetworkModule.network_id == network.id)
    )).scalars().all()
    figures = (await db.execute(
        select(RunFigure).where(RunFigure.network_id == network.id)
    )).scalars().all()
    return {
        "network_id": network.id,
        "dataset_id": network.dataset_id,
        "name": network.name,
        "species": network.species,
        "disease_state": network.disease_state,
        "method": network.method,
        "summary": network.summary,
        "configuration": network.configuration,
        "module_count": len(modules),
        "figures": [{"figure_type": row.figure_type, "format": row.format, "file_path": row.file_path} for row in figures],
    }


@router.get("/{run_id}/networks/{network_id}/nodes")
async def get_run_network_nodes(
    run_id: str,
    network_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        network = _filesystem_network(run_id, network_id)
        return _filesystem_nodes(run_id, network, limit, offset)
    await _owned_network(run_id, network_id, db)
    total = int((await db.execute(select(func.count()).select_from(RunNetworkNode).where(
        RunNetworkNode.network_id == network_id
    ))).scalar_one())
    rows = (await db.execute(
        select(RunNetworkNode, Gene)
        .join(Gene, Gene.id == RunNetworkNode.gene_id)
        .where(RunNetworkNode.network_id == network_id)
        .order_by(RunNetworkNode.degree.desc(), RunNetworkNode.weighted_degree.desc(), Gene.ensembl_id)
        .limit(limit).offset(offset)
    )).all()
    return _page(total, limit, offset, [{
        "gene_id": gene.id,
        "ensembl_id": gene.ensembl_id,
        "gene_symbol": gene.gene_symbol,
        "degree": node.degree,
        "weighted_degree": node.weighted_degree,
        "betweenness_centrality": node.betweenness_centrality,
        "closeness_centrality": node.closeness_centrality,
        "eigenvector_centrality": node.eigenvector_centrality,
        "module_id": node.module_id,
    } for node, gene in rows])


@router.get("/{run_id}/networks/{network_id}/edges")
async def get_run_network_edges(
    run_id: str,
    network_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy.orm import aliased

    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        network = _filesystem_network(run_id, network_id)
        return _filesystem_edges(run_id, network, limit, offset)
    await _owned_network(run_id, network_id, db)
    source = aliased(Gene)
    target = aliased(Gene)
    total = int((await db.execute(select(func.count()).select_from(RunNetworkEdge).where(
        RunNetworkEdge.network_id == network_id
    ))).scalar_one())
    rows = (await db.execute(
        select(RunNetworkEdge, source, target)
        .join(source, source.id == RunNetworkEdge.source_gene_id)
        .join(target, target.id == RunNetworkEdge.target_gene_id)
        .where(RunNetworkEdge.network_id == network_id)
        .order_by(RunNetworkEdge.adjusted_p_value, source.ensembl_id, target.ensembl_id)
        .limit(limit).offset(offset)
    )).all()
    return _page(total, limit, offset, [{
        "source_gene_id": row.source_gene_id,
        "source_ensembl_id": source_gene.ensembl_id,
        "target_gene_id": row.target_gene_id,
        "target_ensembl_id": target_gene.ensembl_id,
        "correlation": row.correlation,
        "absolute_correlation": row.absolute_correlation,
        "pvalue": row.pvalue,
        "adjusted_p_value": row.adjusted_p_value,
        "weight": row.weight,
    } for row, source_gene, target_gene in rows])


@router.get("/{run_id}/modules")
async def list_run_modules(
    run_id: str,
    species: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        modules = _filesystem_modules(run_id, species)
        modules.sort(key=lambda item: (item["network_name"], item["module_key"]))
        return _page(len(modules), limit, offset, modules[offset:offset + limit])
    statement = (
        select(RunNetworkModule, RunGeneNetwork)
        .join(RunGeneNetwork, RunGeneNetwork.id == RunNetworkModule.network_id)
        .where(RunGeneNetwork.run_id == run_id)
    )
    count_statement = (
        select(func.count()).select_from(RunNetworkModule)
        .join(RunGeneNetwork, RunGeneNetwork.id == RunNetworkModule.network_id)
        .where(RunGeneNetwork.run_id == run_id)
    )
    if species is not None:
        statement = statement.where(RunGeneNetwork.species == species)
        count_statement = count_statement.where(RunGeneNetwork.species == species)
    total = int((await db.execute(count_statement)).scalar_one())
    rows = (await db.execute(
        statement.order_by(RunGeneNetwork.name, RunNetworkModule.module_key).limit(limit).offset(offset)
    )).all()
    return _page(total, limit, offset, [{
        "module_id": module.id,
        "module_key": module.module_key,
        "network_id": network.id,
        "network_name": network.name,
        "species": network.species,
        "size": module.size,
        "detection_method": module.detection_method,
        "parameters": module.parameters,
        "statistics": module.statistics,
    } for module, network in rows])


async def _owned_module(run_id: str, module_id: str, db: AsyncSession) -> RunNetworkModule:
    module = (await db.execute(
        select(RunNetworkModule)
        .join(RunGeneNetwork, RunGeneNetwork.id == RunNetworkModule.network_id)
        .where(RunNetworkModule.id == module_id, RunGeneNetwork.run_id == run_id)
    )).scalar_one_or_none()
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    return module


@router.get("/{run_id}/modules/{module_id}")
async def get_run_module(
    run_id: str,
    module_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        return _filesystem_module(run_id, module_id)
    module = await _owned_module(run_id, module_id, db)
    network = await _owned_network(run_id, module.network_id, db)
    return {
        "module_id": module.id,
        "module_key": module.module_key,
        "network_id": network.id,
        "network_name": network.name,
        "species": network.species,
        "size": module.size,
        "detection_method": module.detection_method,
        "parameters": module.parameters,
        "statistics": module.statistics,
    }


@router.get("/{run_id}/modules/{module_id}/genes")
async def get_run_module_genes(
    run_id: str,
    module_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        module = _filesystem_module(run_id, module_id)
        rows = read_result_csv(run_id, f"modules/{module['species']}/module_genes.csv")
        network_rows = read_result_csv(
            run_id,
            f"networks/{module['network_name']}_nodes.csv",
        )
        network_by_gene_id = {
            str(row.get("gene_id")): row
            for row in network_rows
            if row.get("gene_id")
        }
        genes = [{
            "gene_id": row.get("gene_id"),
            "ensembl_id": row.get("gene_id"),
            "gene_symbol": row.get("gene_symbol") or network_by_gene_id.get(
                str(row.get("gene_id")), {}
            ).get("gene_symbol") or None,
            "membership": None,
            "degree": _csv_number(network_by_gene_id.get(str(row.get("gene_id")), {}).get("degree"), integer=True),
            "weighted_degree": _csv_number(network_by_gene_id.get(str(row.get("gene_id")), {}).get("weighted_degree")),
            "betweenness_centrality": _csv_number(network_by_gene_id.get(str(row.get("gene_id")), {}).get("betweenness_centrality")),
            "closeness_centrality": _csv_number(network_by_gene_id.get(str(row.get("gene_id")), {}).get("closeness_centrality")),
            "eigenvector_centrality": _csv_number(network_by_gene_id.get(str(row.get("gene_id")), {}).get("eigenvector_centrality")),
        } for row in rows if (
            row.get("network_name") == module["network_name"]
            and row.get("module_id") == module["module_key"]
        )]
        return _page(len(genes), limit, offset, genes[offset:offset + limit])
    module = await _owned_module(run_id, module_id, db)
    total = int((await db.execute(select(func.count()).select_from(RunModuleGene).where(
        RunModuleGene.module_id == module_id
    ))).scalar_one())
    rows = (await db.execute(
        select(RunModuleGene, Gene, RunNetworkNode)
        .join(Gene, Gene.id == RunModuleGene.gene_id)
        .outerjoin(
            RunNetworkNode,
            (RunNetworkNode.gene_id == Gene.id)
            & (RunNetworkNode.network_id == module.network_id),
        )
        .where(RunModuleGene.module_id == module_id)
        .order_by(Gene.ensembl_id)
        .limit(limit).offset(offset)
    )).all()
    return _page(total, limit, offset, [{
        "gene_id": gene.id,
        "ensembl_id": gene.ensembl_id,
        "gene_symbol": gene.gene_symbol,
        "membership": member.membership,
        "degree": node.degree if node else None,
        "weighted_degree": node.weighted_degree if node else None,
        "betweenness_centrality": node.betweenness_centrality if node else None,
        "closeness_centrality": node.closeness_centrality if node else None,
        "eigenvector_centrality": node.eigenvector_centrality if node else None,
    } for member, gene, node in rows])


@router.get("/{run_id}/analysis-summary")
async def get_run_analysis_summary(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _owned_run(run_id, db, current_user)
    if isinstance(run, dict):
        phase3_summary = run.get("phase3", {}).get("summary", {})
        deg_summary = phase3_summary.get("deg", {})
        differential_expression = []
        if isinstance(deg_summary, dict):
            for label, item in deg_summary.items():
                status = item.get("status", "COMPLETED") if isinstance(item, dict) else ""
                if not isinstance(item, dict) or str(status).lower() not in {"completed", "complete"}:
                    continue
                differential_expression.append({
                    "species": item.get("species") or label.split("_")[0],
                    "comparison": item.get("comparison") or label,
                    "tested_genes": item.get("tested_genes", item.get("total_genes_tested", 0)),
                    "significant_genes": item.get("significant_genes", 0),
                })
        networks = phase3_summary.get("networks", [])
        modules = phase3_summary.get("modules", [])
        return {
            "run_id": run_id,
            "run_status": run.get("phase3", {}).get("status", "COMPLETED"),
            "phase3": phase3_summary,
            "differential_expression": differential_expression,
            "networks": [{
                "network_id": item.get("network_id"),
                "name": item.get("name") or item.get("network_name"),
                "species": item.get("species"),
                "summary": item,
            } for item in networks if isinstance(item, dict)] if isinstance(networks, list) else [],
            "module_count": sum(
                len(item.get("modules", []))
                for item in modules
                if isinstance(item, dict) and isinstance(item.get("modules"), list)
            ) if isinstance(modules, list) else 0,
        }

    de_counts = (await db.execute(
        select(
            RunDifferentialExpression.species,
            RunDifferentialExpression.comparison,
            func.count(RunDifferentialExpression.pvalue),
            func.sum(RunDifferentialExpression.significant.cast(Integer)),
        )
        .where(RunDifferentialExpression.run_id == run_id)
        .group_by(RunDifferentialExpression.species, RunDifferentialExpression.comparison)
    )).all()
    networks = (await db.execute(
        select(RunGeneNetwork).where(RunGeneNetwork.run_id == run_id).order_by(RunGeneNetwork.name)
    )).scalars().all()
    module_count = int((await db.execute(
        select(func.count())
        .select_from(RunNetworkModule)
        .join(RunGeneNetwork, RunGeneNetwork.id == RunNetworkModule.network_id)
        .where(RunGeneNetwork.run_id == run_id)
    )).scalar_one())
    return {
        "run_id": run.id,
        "run_status": run.status,
        "phase3": (run.config or {}).get("phase3_summary", {}),
        "differential_expression": [{
            "species": species,
            "comparison": comparison,
            "tested_genes": int(tested),
            "significant_genes": int(significant or 0),
        } for species, comparison, tested, significant in de_counts],
        "networks": [{
            "network_id": network.id,
            "name": network.name,
            "species": network.species,
            "summary": network.summary,
        } for network in networks],
        "module_count": module_count,
    }
