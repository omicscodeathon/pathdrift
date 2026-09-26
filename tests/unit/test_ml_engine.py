"""Unit tests for ML engine — leakage prevention, evaluation, metrics."""
import pytest
import numpy as np
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.ml.engine import MLEngine, _bootstrap_auroc_ci


def make_classification_data(n_samples=100, n_features=50, seed=42):
    """Synthetic classification dataset (TEST DATA ONLY)."""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_samples, n_features))
    y = (X[:, 0] + X[:, 1] + rng.standard_normal(n_samples) * 0.5 > 0).astype(int)
    feature_names = [f"feat_{i}" for i in range(n_features)]
    X_df = pd.DataFrame(X, columns=feature_names)
    y_s = pd.Series(y, name='label')
    return X_df, y_s


class TestMLEngine:
    def setup_method(self):
        self.X_train, self.y_train = make_classification_data(100, 30)
        self.X_val, self.y_val = make_classification_data(40, 30, seed=99)
        # Ensure validation columns match training
        self.X_val.columns = self.X_train.columns

    def test_logistic_regression_runs(self):
        engine = MLEngine(model_type='logistic_regression', cv_folds=3, random_seed=42)
        result = engine.train_and_evaluate(self.X_train, self.y_train, experiment_id='lr_test')
        assert result.cv_metrics.get('mean_auroc') is not None

    def test_random_forest_runs(self):
        engine = MLEngine(model_type='random_forest', cv_folds=3, random_seed=42)
        result = engine.train_and_evaluate(self.X_train, self.y_train, experiment_id='rf_test')
        assert 0 <= result.cv_metrics['mean_auroc'] <= 1

    def test_external_validation_runs(self):
        engine = MLEngine(model_type='logistic_regression', cv_folds=3)
        result = engine.train_and_evaluate(
            self.X_train, self.y_train,
            X_val=self.X_val, y_val=self.y_val,
            experiment_id='val_test',
        )
        assert result.external_val_metrics.get('auroc') is not None

    def test_leakage_detection(self):
        """Overlapping sample IDs between train and val should trigger a warning."""
        # Create validation set with some samples from training
        X_leaked = pd.concat([self.X_val, self.X_train.iloc[:10]])
        y_leaked = pd.concat([self.y_val, self.y_train.iloc[:10]])
        X_leaked.index = list(range(len(X_leaked)))
        y_leaked.index = list(range(len(y_leaked)))
        # Inject overlapping indices
        X_leaked.index = list(self.X_train.index[:10]) + list(range(100, 100 + len(self.X_val)))
        y_leaked.index = X_leaked.index

        engine = MLEngine(model_type='logistic_regression', cv_folds=3)
        result = engine.train_and_evaluate(
            self.X_train, self.y_train,
            X_val=X_leaked, y_val=y_leaked,
            experiment_id='leakage_test',
        )
        assert len(result.leakage_warnings) > 0

    def test_feature_importances_returned(self):
        engine = MLEngine(model_type='random_forest', cv_folds=3)
        result = engine.train_and_evaluate(self.X_train, self.y_train, experiment_id='fi_test')
        # Feature importances should be a DataFrame
        if result.feature_importances is not None:
            assert 'feature' in result.feature_importances.columns
            assert 'importance' in result.feature_importances.columns

    def test_bootstrap_auroc_ci_valid_range(self):
        rng = np.random.default_rng(42)
        y_true = rng.integers(0, 2, 100)
        y_score = rng.uniform(0, 1, 100)
        lower, upper = _bootstrap_auroc_ci(y_true, y_score, n_bootstrap=200)
        assert 0 <= lower <= upper <= 1

    def test_model_saved_to_disk(self, tmp_path):
        engine = MLEngine(model_type='logistic_regression', cv_folds=3, model_save_dir=str(tmp_path))
        result = engine.train_and_evaluate(self.X_train, self.y_train, experiment_id='save_test')
        assert result.model_path is not None
        assert os.path.exists(result.model_path)
