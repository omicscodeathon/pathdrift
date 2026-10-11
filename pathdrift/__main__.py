from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy import create_engine, inspect, text

from .acquisition.registry import ROOT
from .phase3 import run_mouse_cross_study_deg, run_phase3
from .pipeline import run_phase2


REQUIRED_TABLES = {
    "users", "projects", "datasets", "samples", "analyses", "background_jobs",
    "analysis_runs", "analysis_run_datasets", "sample_qc", "alembic_version",
    "run_differential_expression", "run_gene_networks", "run_network_nodes",
    "run_network_edges", "run_network_modules", "run_module_genes", "run_figures",
    "orthology_mappings", "run_phase4_summaries", "run_orthology_mappings",
    "run_cross_species_node_alignments", "run_network_edge_drift",
    "run_gene_drift", "run_module_drift",
}


def database_check() -> int:
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            missing = sorted(REQUIRED_TABLES - tables)
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() if "alembic_version" in tables else []
            if missing:
                print(json.dumps({"status": "not_ready", "missing_tables": missing, "alembic_revision": revision}))
                return 1
            print(json.dumps({"status": "ready", "alembic_revision": revision, "required_tables": sorted(REQUIRED_TABLES)}))
            return 0
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="pathdrift")
    subcommands = parser.add_subparsers(dest="command", required=True)
    database_parser = subcommands.add_parser("database")
    database_parser.add_subparsers(dest="database_command", required=True).add_parser("check")
    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--config", required=True)
    phase3_parsers = {
        name: subcommands.add_parser(name)
        for name in ("deg", "networks", "modules", "phase3")
    }
    for command_parser in phase3_parsers.values():
        command_parser.add_argument("--run-id", required=True)
        command_parser.add_argument("--force", action="store_true")
        command_parser.add_argument("--max-network-genes", type=int)
    mouse_deg_parser = subcommands.add_parser("mouse-deg-exploratory")
    mouse_deg_parser.add_argument("--run-id", required=True)
    mouse_deg_parser.add_argument("--force", action="store_true")
    phase4_parsers = {
        name: subcommands.add_parser(name)
        for name in ("orthology", "cross-species", "drift", "phase4")
    }
    for command_parser in phase4_parsers.values():
        command_parser.add_argument("--run-id", required=True)
        command_parser.add_argument("--force", action="store_true")
    phase5_parser = subcommands.add_parser("phase5")
    phase5_parser.add_argument("--run-id", required=True)
    phase5_parser.add_argument("--force", action="store_true")
    phase5_parser.add_argument("--gsea", action="store_true", help="Run local preranked GSEA using the saved signed statistics.")
    phase6_parsers = {
        name: subcommands.add_parser(name)
        for name in ("ml", "validation", "phase6")
    }
    for command_parser in phase6_parsers.values():
        command_parser.add_argument("--run-id", required=True)
        command_parser.add_argument("--species", choices=("human", "mouse"), default="human")
        command_parser.add_argument("--seed", type=int, default=42)
        command_parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command == "database":
        sys.path.insert(0, str(ROOT / "backend"))
        return database_check()
    if args.command == "run":
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            result = run_phase2(args.config)
        except Exception as error:
            logging.getLogger("pathdrift").exception("Phase 2 run failed")
            print(json.dumps({"status": "FAILED", "error": str(error)}), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.command == "mouse-deg-exploratory":
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            result = run_mouse_cross_study_deg(args.run_id, force=args.force)
        except Exception as error:
            logging.getLogger("pathdrift").exception("Exploratory mouse cross-study DEG failed")
            print(json.dumps({
                "status": "FAILED",
                "run_id": args.run_id,
                "error": str(error),
            }), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.command in phase3_parsers:
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            result = run_phase3(
                args.run_id,
                force=args.force,
                stage=args.command,
                max_network_genes=args.max_network_genes,
            )
        except Exception as error:
            logging.getLogger("pathdrift").exception("Phase 3 %s stage failed", args.command)
            print(json.dumps({
                "status": "FAILED",
                "stage": args.command,
                "run_id": args.run_id,
                "error": str(error),
            }), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.command in phase4_parsers:
        sys.path.insert(0, str(ROOT / "backend"))
        from .drift.service import run_phase4

        try:
            result = run_phase4(
                args.run_id,
                stage=args.command,
                force=args.force,
            )
        except Exception as error:
            logging.getLogger("pathdrift").exception("Phase 4 %s stage failed", args.command)
            print(json.dumps({
                "status": "FAILED",
                "stage": args.command,
                "run_id": args.run_id,
                "error": str(error),
            }), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.command == "phase5":
        from .phase5.service import run_phase5

        try:
            result = run_phase5(args.run_id, force=args.force, run_gsea=args.gsea)
        except Exception as error:
            logging.getLogger("pathdrift").exception("Phase 5 run failed")
            print(json.dumps({
                "status": "FAILED",
                "stage": "phase5",
                "run_id": args.run_id,
                "error": str(error),
            }), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.command in phase6_parsers:
        from .phase6.service import run_phase6

        try:
            result = run_phase6(
                args.run_id,
                species=args.species,
                seed=args.seed,
                force=args.force,
            )
        except Exception as error:
            logging.getLogger("pathdrift").exception("Phase 6 %s workflow failed", args.command)
            print(json.dumps({
                "status": "FAILED",
                "stage": args.command,
                "run_id": args.run_id,
                "error": str(error),
            }), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())