"""
Unit tests for the preprocessing pipeline.
Uses a small synthetic expression matrix to validate pipeline behaviour.
This is TEST DATA only — never used in the production application.
"""
import pytest
import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.bio.preprocessing import PreprocessingPipeline, PreprocessingLog


def make_test_expression(n_genes: int = 200, n_samples: int = 20, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic expression matrix for testing purposes only."""
    rng = np.random.default_rng(seed)
    data = rng.negative_binomial(n=5, p=0.3, size=(n_genes, n_samples)).astype(float)
    gene_ids = [f"ENSG{str(i).zfill(11)}" for i in range(n_genes)]
    sample_ids = [f"SAMPLE_{i:03d}" for i in range(n_samples)]
    return pd.DataFrame(data, index=gene_ids, columns=sample_ids)


def make_test_metadata(sample_ids, healthy_frac=0.5) -> pd.DataFrame:
    n = len(sample_ids)
    n_healthy = int(n * healthy_frac)
    states = ['healthy'] * n_healthy + ['cancer'] * (n - n_healthy)
    return pd.DataFrame({'sample_id': sample_ids, 'disease_state': states})


class TestPreprocessingPipeline:
    def setup_method(self):
        self.expr = make_test_expression(200, 20)
        self.meta = make_test_metadata(self.expr.columns.tolist())

    def test_basic_run(self):
        pipeline = PreprocessingPipeline(normalization_method='log2cpm')
        cleaned, log = pipeline.run(self.expr, self.meta, 'test_dataset', 'human')
        assert cleaned.shape[0] > 0
        assert cleaned.shape[1] > 0
        assert log.n_genes_before == 200
        assert log.n_samples_before == 20

    def test_low_expression_filter(self):
        pipeline = PreprocessingPipeline(
            normalization_method='none',
            low_expr_threshold=100,   # very high threshold to trigger removal
            low_expr_min_samples=20,
        )
        # Make some genes all-zero
        expr = self.expr.copy()
        expr.iloc[:50] = 0  # 50 genes all zero
        cleaned, log = pipeline.run(expr, self.meta, 'test_filter', 'human')
        # Those 50 genes should have been removed
        assert cleaned.shape[0] < 200

    def test_duplicate_gene_handling(self):
        expr = self.expr.copy()
        # Duplicate first 5 genes
        expr.index = list(expr.index[:195]) + list(expr.index[:5])
        pipeline = PreprocessingPipeline(normalization_method='none', remove_duplicates=True)
        cleaned, log = pipeline.run(expr, self.meta, 'test_dups', 'human')
        assert cleaned.index.duplicated().sum() == 0

    def test_normalization_log2cpm(self):
        pipeline = PreprocessingPipeline(normalization_method='log2cpm')
        cleaned, log = pipeline.run(self.expr, self.meta, 'test_norm', 'human')
        # After log2CPM, values should be >= 0
        assert (cleaned >= 0).all().all()
        # Values should not be raw counts
        assert cleaned.max().max() < 100

    def test_normalization_none_passthrough(self):
        pipeline = PreprocessingPipeline(normalization_method='none',
                                          low_expr_threshold=0, min_gene_variance=0)
        cleaned, log = pipeline.run(self.expr, self.meta, 'test_passthrough', 'human')
        # Without filtering, shape should remain (approximately) the same
        assert cleaned.shape[0] == 200

    def test_missing_values_handled(self):
        expr = self.expr.copy().astype(float)
        expr.iloc[0, 0:5] = np.nan
        pipeline = PreprocessingPipeline(normalization_method='log2cpm', impute_missing=False)
        cleaned, log = pipeline.run(expr, self.meta, 'test_missing', 'human')
        # Pipeline should handle without crashing
        assert cleaned.shape[0] > 0

    def test_log_records_decisions(self):
        pipeline = PreprocessingPipeline(normalization_method='log2cpm', outlier_detection=True)
        _, log = pipeline.run(self.expr, self.meta, 'test_log', 'human')
        log_text = log.to_text()
        assert 'log2(CPM + 1)' in log_text
        assert 'ENSG' in log_text or 'Genes' in log_text

    def test_batch_correction_no_batch_column(self):
        """If metadata has no batch column, batch correction should be skipped gracefully."""
        meta_no_batch = self.meta.copy()
        pipeline = PreprocessingPipeline(normalization_method='none', batch_correct=True,
                                          low_expr_threshold=0, min_gene_variance=0)
        cleaned, log = pipeline.run(self.expr, meta_no_batch, 'test_batch', 'human')
        assert any('batch' in w.lower() for w in log.warnings)
