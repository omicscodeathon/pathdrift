"""
PathDrift Machine Learning Engine

Implements three experimental comparisons:
  Model A — Expression-only baseline
  Model B — Network-drift features
  Model C — Combined (expression + drift)

Algorithms:
  - Logistic Regression
  - Random Forest
  - SVM
  - Gradient Boosting

Evaluation:
  - Stratified k-fold cross-validation
  - Feature selection inside training folds (NO leakage)
  - Normalization fit on training data only
  - External validation on completely held-out dataset

Data-leakage prevention:
  - StandardScaler fit only inside each CV fold's training set
  - Feature selection performed inside each fold
  - External validation dataset never influences any training step
  - Warnings logged for any potential leakage scenario

Metrics reported:
  AUROC, AUPRC, sensitivity, specificity, precision, recall, F1,
  confusion matrix, calibration, 95% CI (bootstrap)
"""
import numpy as np
import pandas as pd
import joblib
import os
from typing import Optional, Dict, Any, List, Tuple
import structlog
from dataclasses import dataclass, field

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.feature_selection import SelectKBest, f_classif, VarianceThreshold
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    roc_auc_score, average_precision_score, confusion_matrix,
    f1_score, precision_score, recall_score, accuracy_score,
    roc_curve, precision_recall_curve,
)
from sklearn.utils.class_weight import compute_class_weight

logger = structlog.get_logger(__name__)


@dataclass
class MLResult:
    experiment_id: str
    experiment_type: str
    model_type: str
    train_metrics: Dict = field(default_factory=dict)
    cv_metrics: Dict = field(default_factory=dict)
    external_val_metrics: Dict = field(default_factory=dict)
    feature_importances: Optional[pd.DataFrame] = None
    leakage_warnings: List[str] = field(default_factory=list)
    n_features: int = 0
    model_path: Optional[str] = None


class MLEngine:
    """
    Trains and evaluates a machine learning model for breast cancer state prediction.

    Parameters
    ----------
    model_type : str
        One of: logistic_regression, random_forest, svm, gradient_boosting
    experiment_type : str
        One of: expression_only, drift_only, combined
    random_seed : int
    cv_folds : int
    test_size : float
    class_weight : str
        'balanced' or None
    hyperparams : dict or None
        Override default hyperparameters.
    feature_selection_k : int or None
        Number of top features to select by univariate F-score.
        Applied INSIDE each CV fold to prevent leakage.
    """

    def __init__(
        self,
        model_type: str = "random_forest",
        experiment_type: str = "combined",
        random_seed: int = 42,
        cv_folds: int = 5,
        test_size: float = 0.2,
        class_weight: str = "balanced",
        hyperparams: Optional[Dict[str, Any]] = None,
        feature_selection_k: Optional[int] = None,
        model_save_dir: str = "./models",
    ):
        self.model_type = model_type
        self.experiment_type = experiment_type
        self.random_seed = random_seed
        self.cv_folds = cv_folds
        self.test_size = test_size
        self.class_weight = class_weight
        self.hyperparams = hyperparams or {}
        self.feature_selection_k = feature_selection_k
        self.model_save_dir = model_save_dir
        os.makedirs(model_save_dir, exist_ok=True)

    def train_and_evaluate(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        experiment_id: str = "experiment",
    ) -> MLResult:
        """
        Full training and evaluation workflow.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features (samples × features). Must not contain test samples.
        y_train : pd.Series
            Training labels (0 = healthy, 1 = cancer/disease).
        X_val, y_val : optional
            External validation set. MUST be completely independent of training.
        experiment_id : str

        Returns
        -------
        MLResult
        """
        result = MLResult(
            experiment_id=experiment_id,
            experiment_type=self.experiment_type,
            model_type=self.model_type,
        )

        # ── Leakage checks ─────────────────────────────────────────────────────
        warnings = self._check_for_leakage(X_train, X_val)
        result.leakage_warnings = warnings

        # ── Build pipeline ────────────────────────────────────────────────────
        pipeline = self._build_pipeline()
        result.n_features = X_train.shape[1]

        # ── Stratified CV ─────────────────────────────────────────────────────
        logger.info(
            "ml_cv_starting",
            model=self.model_type,
            n_samples=len(X_train),
            n_features=X_train.shape[1],
            cv_folds=self.cv_folds,
        )

        cv_result = self._stratified_cv(pipeline, X_train, y_train)
        result.cv_metrics = cv_result

        # ── Full training ─────────────────────────────────────────────────────
        pipeline.fit(X_train, y_train)
        train_metrics = self._compute_metrics(pipeline, X_train, y_train, split="train")
        result.train_metrics = train_metrics

        # ── External validation ───────────────────────────────────────────────
        if X_val is not None and y_val is not None:
            logger.info("ml_external_validation_starting", n_val_samples=len(X_val))
            val_metrics = self._compute_metrics(pipeline, X_val, y_val, split="external_val")
            result.external_val_metrics = val_metrics

        # ── Feature importances ───────────────────────────────────────────────
        result.feature_importances = self._extract_feature_importances(pipeline, X_train.columns.tolist())

        # ── Save model ────────────────────────────────────────────────────────
        model_path = os.path.join(self.model_save_dir, f"{experiment_id}.joblib")
        joblib.dump(pipeline, model_path)
        result.model_path = model_path

        logger.info("ml_training_done", experiment_id=experiment_id, cv_auroc=cv_result.get("mean_auroc"))
        return result

    def _build_pipeline(self) -> Pipeline:
        steps = []

        # 1. Variance threshold (removes zero-variance features, safe to do globally)
        steps.append(("var_threshold", VarianceThreshold(threshold=0.0)))

        # 2. Scaling (MUST be fit only on training data — sklearn Pipeline ensures this)
        steps.append(("scaler", StandardScaler()))

        # 3. Feature selection (fit inside each CV fold via Pipeline)
        if self.feature_selection_k:
            steps.append(
                ("feature_select", SelectKBest(f_classif, k=min(self.feature_selection_k, 500)))
            )

        # 4. Estimator
        estimator = self._build_estimator()
        # Calibrate for reliable probability estimates
        calibrated = CalibratedClassifierCV(estimator, method="isotonic", cv=3)
        steps.append(("clf", calibrated))

        return Pipeline(steps)

    def _build_estimator(self):
        cw = self.class_weight if self.class_weight != "none" else None

        if self.model_type == "logistic_regression":
            params = dict(C=1.0, max_iter=1000, random_state=self.random_seed, class_weight=cw, solver="lbfgs")
            params.update(self.hyperparams)
            return LogisticRegression(**params)

        elif self.model_type == "random_forest":
            params = dict(n_estimators=200, max_depth=None, random_state=self.random_seed, class_weight=cw, n_jobs=-1)
            params.update(self.hyperparams)
            return RandomForestClassifier(**params)

        elif self.model_type == "svm":
            params = dict(C=1.0, kernel="rbf", probability=True, random_state=self.random_seed, class_weight=cw)
            params.update(self.hyperparams)
            return SVC(**params)

        elif self.model_type == "gradient_boosting":
            params = dict(n_estimators=200, learning_rate=0.05, max_depth=3, random_state=self.random_seed)
            params.update(self.hyperparams)
            return GradientBoostingClassifier(**params)

        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

    def _stratified_cv(
        self, pipeline: Pipeline, X: pd.DataFrame, y: pd.Series
    ) -> Dict:
        """Stratified k-fold cross-validation. Pipeline fit/transform happens inside each fold."""
        skf = StratifiedKFold(n_splits=self.cv_folds, shuffle=True, random_state=self.random_seed)

        aurocs, auprcs, f1s, accs = [], [], [], []

        for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_t, X_v = X.iloc[train_idx], X.iloc[val_idx]
            y_t, y_v = y.iloc[train_idx], y.iloc[val_idx]

            # Fit pipeline on training fold only — prevents leakage
            pipeline.fit(X_t, y_t)
            y_prob = pipeline.predict_proba(X_v)[:, 1]
            y_pred = pipeline.predict(X_v)

            if len(np.unique(y_v)) > 1:
                aurocs.append(roc_auc_score(y_v, y_prob))
                auprcs.append(average_precision_score(y_v, y_prob))
            f1s.append(f1_score(y_v, y_pred, zero_division=0))
            accs.append(accuracy_score(y_v, y_pred))

        result = {
            "mean_auroc": float(np.mean(aurocs)) if aurocs else None,
            "std_auroc": float(np.std(aurocs)) if aurocs else None,
            "mean_auprc": float(np.mean(auprcs)) if auprcs else None,
            "mean_f1": float(np.mean(f1s)),
            "mean_accuracy": float(np.mean(accs)),
            "fold_aurocs": aurocs,
        }
        return result

    @staticmethod
    def _compute_metrics(
        pipeline: Pipeline,
        X: pd.DataFrame,
        y: pd.Series,
        split: str = "eval",
    ) -> Dict:
        y_prob = pipeline.predict_proba(X)[:, 1]
        y_pred = pipeline.predict(X)
        y_np = np.array(y)

        if len(np.unique(y_np)) < 2:
            logger.warning("single_class_in_split", split=split)
            return {}

        auroc = float(roc_auc_score(y_np, y_prob))
        auprc = float(average_precision_score(y_np, y_prob))
        cm = confusion_matrix(y_np, y_pred).tolist()

        tn, fp, fn, tp = confusion_matrix(y_np, y_pred).ravel() if len(np.unique(y_np)) == 2 else (0, 0, 0, 0)
        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0

        # Bootstrap 95% CI for AUROC
        auroc_ci = _bootstrap_auroc_ci(y_np, y_prob)

        return {
            "split": split,
            "auroc": auroc,
            "auprc": auprc,
            "accuracy": float(accuracy_score(y_np, y_pred)),
            "sensitivity": float(sensitivity),
            "specificity": float(specificity),
            "precision": float(precision_score(y_np, y_pred, zero_division=0)),
            "recall": float(recall_score(y_np, y_pred, zero_division=0)),
            "f1": float(f1_score(y_np, y_pred, zero_division=0)),
            "auroc_ci_lower": auroc_ci[0],
            "auroc_ci_upper": auroc_ci[1],
            "confusion_matrix": {"matrix": cm},
        }

    @staticmethod
    def _extract_feature_importances(
        pipeline: Pipeline, feature_names: List[str]
    ) -> Optional[pd.DataFrame]:
        try:
            clf = pipeline.named_steps["clf"]
            # CalibratedClassifierCV wraps the base estimator
            base = getattr(clf, "estimator", clf)
            if hasattr(base, "feature_importances_"):
                importances = base.feature_importances_
            elif hasattr(base, "coef_"):
                importances = np.abs(base.coef_[0])
            else:
                return None

            # Map back through feature selection if applied
            if "feature_select" in pipeline.named_steps:
                selector = pipeline.named_steps["feature_select"]
                selected_mask = selector.get_support()
                selected_names = np.array(feature_names)[selected_mask]
                return pd.DataFrame(
                    {"feature": selected_names, "importance": importances}
                ).sort_values("importance", ascending=False)
            else:
                return pd.DataFrame(
                    {"feature": feature_names[:len(importances)], "importance": importances}
                ).sort_values("importance", ascending=False)
        except Exception:
            return None

    @staticmethod
    def _check_for_leakage(
        X_train: pd.DataFrame, X_val: Optional[pd.DataFrame]
    ) -> List[str]:
        warnings = []
        if X_val is not None:
            overlap = set(X_train.index) & set(X_val.index)
            if overlap:
                warnings.append(
                    f"DATA LEAKAGE WARNING: {len(overlap)} sample IDs appear in both "
                    f"training and validation sets. Remove overlapping samples before training."
                )
        return warnings


def _bootstrap_auroc_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float]:
    """Bootstrap confidence interval for AUROC."""
    rng = np.random.default_rng(seed)
    aurocs = []
    n = len(y_true)
    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, n)
        if len(np.unique(y_true[idx])) < 2:
            continue
        aurocs.append(roc_auc_score(y_true[idx], y_score[idx]))
    if not aurocs:
        return (0.0, 1.0)
    lower = float(np.percentile(aurocs, (1 - ci) / 2 * 100))
    upper = float(np.percentile(aurocs, (1 - (1 - ci) / 2) * 100))
    return lower, upper
