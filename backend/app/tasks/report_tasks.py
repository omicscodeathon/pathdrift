"""Report generation Celery task."""
import os
import html as html_lib
from datetime import datetime, timezone
import pandas as pd
from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import get_sync_db, _update_job
from app.core.config import settings
from app.models import BackgroundJob, JobStatusEnum
import structlog

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.report_tasks.generate_report_task")
def generate_report_task(self, job_id: str, analysis_id: str, sections: list, format: str = "pdf"):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 10, "Collecting analysis results")

        from app.models import (
            Analysis, Dataset, PreprocessingJob, DEGResult, GeneNetwork,
            DriftAnalysis, CrossSpeciesAnalysis, MLExperiment, ModelMetric,
            PathwayResult,
        )
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            raise ValueError(f"Analysis {analysis_id} not found")

        report_data = {
            "title": "PathDrift Analysis Report",
            "analysis_name": analysis.name,
            "analysis_id": analysis_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "random_seed": analysis.random_seed,
            "config": analysis.config_snapshot or {},
            "include_sections": sections,
            "sections": {},
        }

        datasets = db.query(Dataset).filter(Dataset.project_id == analysis.project_id).all()
        report_data["sections"]["dataset"] = {
            "title": "Dataset Information",
            "table": pd.DataFrame([{
                "name": item.name, "source": item.source, "accession": item.accession,
                "species": item.species.value if hasattr(item.species, "value") else item.species,
                "genes": item.n_genes, "samples": item.n_samples,
            } for item in datasets]),
        }

        result_file_fields = {
            "deg": "results_file_path",
            "networks": "node_features_file_path",
            "drift": "node_drift_file_path",
            "cross_species": "comparison_file_path",
            "pathways": "results_file_path",
        }
        for key, title, query, columns in [
            ("preprocessing", "Preprocessing", db.query(PreprocessingJob).filter(PreprocessingJob.analysis_id == analysis_id), ["id", "status", "n_genes_before", "n_genes_after", "n_samples_before", "n_samples_after"]),
            ("deg", "Differential Expression", db.query(DEGResult).filter(DEGResult.analysis_id == analysis_id), ["id", "status", "method", "n_deg_total", "n_deg_up", "n_deg_down"]),
            ("networks", "Network Construction", db.query(GeneNetwork).filter(GeneNetwork.analysis_id == analysis_id), ["id", "status", "name", "species", "disease_state", "n_nodes", "n_edges", "density"]),
            ("drift", "Network Drift", db.query(DriftAnalysis).filter(DriftAnalysis.analysis_id == analysis_id), ["id", "status", "species", "n_conserved_edges", "n_gained_edges", "n_lost_edges", "global_drift_score"]),
            ("cross_species", "Cross-Species Comparison", db.query(CrossSpeciesAnalysis).filter(CrossSpeciesAnalysis.analysis_id == analysis_id), ["id", "status", "n_orthologous_genes", "n_conserved_drift", "n_human_specific", "n_mouse_specific", "n_divergent", "conservation_score"]),
            ("ml", "Machine Learning", db.query(MLExperiment).filter(MLExperiment.analysis_id == analysis_id), ["id", "status", "name", "experiment_type", "model_type", "n_features_used"]),
            ("pathways", "Pathway Analysis", db.query(PathwayResult).filter(PathwayResult.analysis_id == analysis_id), ["id", "status", "gene_set", "source", "species", "n_significant", "fdr_threshold"]),
        ]:
            rows = []
            for item in query.all():
                row = {}
                for column in columns:
                    value = getattr(item, column, None)
                    row[column] = value.value if hasattr(value, "value") else value
                rows.append(row)
            table = pd.DataFrame(rows, columns=columns)
            file_field = result_file_fields.get(key)
            result_tables = []
            if file_field:
                for item in query.all():
                    result_path = getattr(item, file_field, None)
                    if result_path and os.path.exists(result_path):
                        result_tables.append(pd.read_parquet(result_path).reset_index())
            if result_tables:
                table = pd.concat(result_tables, ignore_index=True)
            report_data["sections"][key] = {"title": title, "table": table}

        _update_job(db, job_id, JobStatusEnum.RUNNING, 50, "Generating report")

        output_dir = os.path.join(settings.REPORT_DIR, analysis_id)
        os.makedirs(output_dir, exist_ok=True)

        if format == "html":
            _generate_html_report(report_data, output_dir)
        else:
            _generate_html_report(report_data, output_dir)  # PDF via weasyprint if available

        _update_job(db, job_id, JobStatusEnum.COMPLETED, 100, "Report generated")
        return {"status": "completed"}

    except Exception as e:
        logger.error("report_task_failed", error=str(e))
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", str(e))
        raise
    finally:
        db.close()


def _generate_html_report(data: dict, output_dir: str):
    """Generate an HTML report from persisted analysis results."""
    sections = []
    for key, section in data["sections"].items():
        if key not in data.get("include_sections", data["sections"].keys()):
            continue
        table = section["table"]
        body = table.to_html(index=False, border=0, classes="results") if not table.empty else "<p>No completed results were recorded for this section.</p>"
        sections.append(f"<h2>{html_lib.escape(section['title'])}</h2>{body}")

    sections_html = "\n".join(sections)
    report_html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{data['title']}</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1a1a2e; }}
    h1 {{ color: #1565c0; border-bottom: 2px solid #1565c0; padding-bottom: 10px; }}
    h2 {{ color: #0d47a1; margin-top: 30px; }}
    .meta {{ background: #f8fafc; padding: 15px; border-radius: 8px; margin: 20px 0; }}
    .warning {{ background: #fff3e0; border-left: 4px solid #e65100; padding: 10px 15px; margin: 15px 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
    th {{ background: #f0f4f8; font-weight: 600; }}
    .results {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
    .results th, .results td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
  </style>
</head>
<body>
  <h1>PathDrift Analysis Report</h1>
  <div class="meta">
    <strong>Analysis:</strong> {data['analysis_name']}<br>
    <strong>ID:</strong> {data['analysis_id']}<br>
    <strong>Generated:</strong> {data['generated_at']}<br>
    <strong>Random Seed:</strong> {data['random_seed']}
  </div>

  <div class="warning">
    <strong>Scientific Integrity Notice:</strong>
    Results in this report are computational predictions generated from the provided datasets.
    They do not constitute validated clinical biomarkers or diagnostic tools.
    External validation on independent datasets is required before drawing conclusions about
    clinical utility.
  </div>

  <h2>Research Hypothesis</h2>
  <p><em>Conserved gene-network drift between human and mouse breast-cancer states contains
  biologically meaningful information that can improve early breast-cancer state prediction
  compared with conventional gene-expression features alone.</em></p>

    {sections_html}
    <h2>Limitations</h2>
    <p>These results are computational outputs from the recorded datasets and parameters. They require independent biological and clinical validation.</p>
</body>
</html>"""

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_html)

    # Attempt PDF conversion
    try:
        from weasyprint import HTML
        HTML(string=report_html).write_pdf(os.path.join(output_dir, "report.pdf"))
    except Exception:
        # WeasyPrint may not be available; HTML report is the fallback
        pass
