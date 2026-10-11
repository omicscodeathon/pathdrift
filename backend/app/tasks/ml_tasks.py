"""
Celery Tasks: Machine Learning pipeline tasks.
"""
import os
import traceback
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import structlog

from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import (
    get_sync_db, _update_job, _load_analysis_data,
    _split_samples_by_state, _load_expression
)
from app.core.config import settings
from app.models import MLExperiment, ModelMetric, BackgroundJob, JobStatusEnum

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.ml_tasks.run_ml_experiment")
def run_ml_experiment(self, job_id: str, experiment_id: str):
    db = get_sync_db()
    try:
        _update_job(db, job_id, JobStatusEnum.RUNNING, 5, "Loading experiment configuration")

        exp = db.query(MLExperiment).filter(MLExperiment.id == experiment_id).first()
        if not exp:
            raise ValueError(f"MLExperiment {experiment_id} not found")

        _update_job(db, job_id, JobStatusEnum.RUNNING, 15, "Loading training data")
        expr_df, metadata_df = _load_analysis_data(db, exp.training_dataset_id, exp.preprocessing_job_id)
        healthy_samples, disease_samples = _split_samples_by_state(metadata_df, expr_df)

        all_train_samples = healthy_samples + disease_samples
        y_train = pd.Series(
            [0] * len(healthy_samples) + [1] * len(disease_samples),
            index=all_train_samples,
            name="label",
        )

        _update_job(db, job_id, JobStatusEnum.RUNNING, 30, "Extracting features")

        # Load optional drift and cross-species results
        node_drift_df = None
        cross_species_df = None
        deg_results = None

        if exp.drift_analysis_id:
            from app.models import DriftAnalysis
            drift = db.query(DriftAnalysis).filter(DriftAnalysis.id == exp.drift_analysis_id).first()
            if drift and drift.node_drift_file_path:
                node_drift_df = pd.read_parquet(drift.node_drift_file_path)

        if exp.cross_species_analysis_id:
            from app.models import CrossSpeciesAnalysis
            cs = db.query(CrossSpeciesAnalysis).filter(CrossSpeciesAnalysis.id == exp.cross_species_analysis_id).first()
            if cs and cs.comparison_file_path:
                cross_species_df = pd.read_parquet(cs.comparison_file_path)

        from app.bio.features import FeatureExtractor
        extractor = FeatureExtractor(
            experiment_type=exp.experiment_type.value,
        )
        X_train = extractor.extract(
            expr_df=expr_df,
            deg_results=deg_results,
            node_drift_df=node_drift_df,
            cross_species_df=cross_species_df,
            sample_ids=all_train_samples,
        )
        X_train = X_train.loc[all_train_samples]

        _update_job(db, job_id, JobStatusEnum.RUNNING, 50, f"Training model ({X_train.shape[1]} features)")

        # Load validation data if provided
        X_val, y_val = None, None
        if exp.validation_dataset_id:
            val_expr, val_meta = _load_analysis_data(db, exp.validation_dataset_id, None)
            val_healthy, val_disease = _split_samples_by_state(val_meta, val_expr)
            val_samples = val_healthy + val_disease
            y_val = pd.Series(
                [0] * len(val_healthy) + [1] * len(val_disease),
                index=val_samples,
                name="label",
            )
            X_val = extractor.extract(
                expr_df=val_expr,
                node_drift_df=node_drift_df,
                cross_species_df=cross_species_df,
                sample_ids=val_samples,
            )
            X_val = X_val.loc[val_samples]
            # Align columns
            shared_cols = X_train.columns.intersection(X_val.columns)
            X_train = X_train[shared_cols]
            X_val = X_val[shared_cols]

        model_dir = os.path.join(settings.REPORT_DIR, "models", experiment_id)
        os.makedirs(model_dir, exist_ok=True)

        from app.ml.engine import MLEngine
        hyperparams = exp.hyperparams or {}
        fs_config = exp.feature_selection_config or {}
        feature_k = fs_config.get("k", None)

        engine = MLEngine(
            model_type=exp.model_type.value,
            experiment_type=exp.experiment_type.value,
            random_seed=exp.random_seed,
            cv_folds=exp.cv_folds,
            test_size=exp.test_size,
            class_weight=exp.class_weight or "balanced",
            hyperparams=hyperparams,
            feature_selection_k=feature_k,
            model_save_dir=model_dir,
        )

        ml_result = engine.train_and_evaluate(
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            experiment_id=experiment_id,
        )

        _update_job(db, job_id, JobStatusEnum.RUNNING, 90, "Saving model and metrics")

        # Save metrics to DB
        def _save_metric(split_name, metrics_dict):
            if not metrics_dict:
                return
            metric = ModelMetric(
                experiment_id=experiment_id,
                split=split_name,
                auroc=metrics_dict.get("auroc", metrics_dict.get("mean_auroc")),
                auprc=metrics_dict.get("auprc", metrics_dict.get("mean_auprc")),
                accuracy=metrics_dict.get("accuracy", metrics_dict.get("mean_accuracy")),
                sensitivity=metrics_dict.get("sensitivity"),
                specificity=metrics_dict.get("specificity"),
                precision=metrics_dict.get("precision"),
                recall=metrics_dict.get("recall"),
                f1=metrics_dict.get("f1", metrics_dict.get("mean_f1")),
                auroc_ci_lower=metrics_dict.get("auroc_ci_lower"),
                auroc_ci_upper=metrics_dict.get("auroc_ci_upper"),
                confusion_matrix=metrics_dict.get("confusion_matrix"),
            )
            db.add(metric)

        _save_metric("train", ml_result.train_metrics)
        _save_metric("cv", ml_result.cv_metrics)
        if ml_result.external_val_metrics:
            _save_metric("external_val", ml_result.external_val_metrics)

        # Save feature importances
        fi_path = None
        if ml_result.feature_importances is not None:
            fi_path = os.path.join(model_dir, "feature_importances.parquet")
            ml_result.feature_importances.to_parquet(fi_path)

        exp.n_features_used = ml_result.n_features
        exp.model_file_path = ml_result.model_path
        exp.feature_importance_path = fi_path
        exp.leakage_warnings = ml_result.leakage_warnings
        exp.status = JobStatusEnum.COMPLETED
        db.commit()

        cv_auroc = ml_result.cv_metrics.get("mean_auroc")
        _update_job(job_id=job_id, db=db, status=JobStatusEnum.COMPLETED, progress=100,
                    msg=f"ML training done. CV AUROC: {cv_auroc:.3f}" if cv_auroc else "ML training done")
        return {"status": "completed", "cv_auroc": cv_auroc}

    except Exception as e:
        err = str(e)
        tb = traceback.format_exc()
        logger.error("ml_task_failed", error=err)
        _update_job(db, job_id, JobStatusEnum.FAILED, 0, "Failed", err)
        ex = db.query(MLExperiment).filter(MLExperiment.id == experiment_id).first()
        if ex:
            ex.status = JobStatusEnum.FAILED
            db.commit()
        raise
    finally:
        db.close()
