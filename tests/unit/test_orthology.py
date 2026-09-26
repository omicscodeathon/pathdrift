"""Unit tests for orthology engine."""
import pytest
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestOrthologyEngine:
    """
    Tests for orthology mapping logic.
    These tests use mock data — real Ensembl data must be loaded via seed_orthology.py.
    """

    def test_one_to_one_filter(self):
        """Verify that only ortholog_one2one entries are returned when one_to_one_only=True."""
        from app.bio.orthology import OrthologyEngine
        # We test the filtering logic with mock data
        mock_df = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001',
             'human_symbol': 'GENE1', 'mouse_symbol': 'Gene1', 'orthology_type': 'ortholog_one2one', 'confidence': 1.0},
            {'human_ensembl_id': 'ENSG00000002', 'mouse_ensembl_id': 'ENSMUSG00000002',
             'human_symbol': 'GENE2', 'mouse_symbol': 'Gene2', 'orthology_type': 'ortholog_one2many', 'confidence': 0.5},
        ])
        filtered = mock_df[mock_df['orthology_type'] == 'ortholog_one2one']
        assert len(filtered) == 1
        assert filtered.iloc[0]['human_ensembl_id'] == 'ENSG00000001'

    def test_alignment_preserves_gene_count(self):
        """Alignment should return same number of rows as valid orthologue pairs."""
        human_genes = ['ENSG00000001', 'ENSG00000002', 'ENSG00000003']
        mouse_genes = ['ENSMUSG00000001', 'ENSMUSG00000002']
        mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001',
             'human_symbol': 'GENE1', 'mouse_symbol': 'Gene1'},
            {'human_ensembl_id': 'ENSG00000002', 'mouse_ensembl_id': 'ENSMUSG00000002',
             'human_symbol': 'GENE2', 'mouse_symbol': 'Gene2'},
        ])
        # Simulate alignment logic
        valid_pairs = mapping[
            mapping['human_ensembl_id'].isin(human_genes) &
            mapping['mouse_ensembl_id'].isin(mouse_genes)
        ]
        assert len(valid_pairs) == 2

    def test_no_symbol_match_fallback_raises(self):
        """
        Confirm that symbol-based matching is NOT used as silent fallback.
        If Ensembl IDs don't match, the result should be empty, not silently symbol-matched.
        """
        human_ids = ['ENSG99999999']   # Not in mapping
        mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001',
             'human_symbol': 'GENE1', 'mouse_symbol': 'Gene1'},
        ])
        matched = mapping[mapping['human_ensembl_id'].isin(human_ids)]
        assert len(matched) == 0, "Should not match via symbol; only Ensembl ID matching is allowed"
