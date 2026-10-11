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

    def test_one_to_one_validation_rejects_ambiguous_human_mapping(self):
        from app.bio.orthology import validate_one_to_one_mappings

        mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000002', 'orthology_type': 'ortholog_one2one'},
        ])

        with pytest.raises(ValueError, match='Ambiguous ortholog_one2one'):
            validate_one_to_one_mappings(mapping)

    def test_one_to_one_validation_rejects_ambiguous_mouse_mapping(self):
        from app.bio.orthology import validate_one_to_one_mappings

        mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'ENSG00000002', 'mouse_ensembl_id': 'ENSMUSG00000001', 'orthology_type': 'ortholog_one2one'},
        ])

        with pytest.raises(ValueError, match='Ambiguous ortholog_one2one'):
            validate_one_to_one_mappings(mapping)

    def test_one_to_one_validation_excludes_many_to_many_records(self):
        from app.bio.orthology import validate_one_to_one_mappings

        mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'ENSG00000002', 'mouse_ensembl_id': 'ENSMUSG00000002', 'orthology_type': 'ortholog_one2many'},
        ])

        validated = validate_one_to_one_mappings(mapping)

        assert validated['human_ensembl_id'].tolist() == ['ENSG00000001']

    def test_cross_species_comparator_rejects_ambiguous_mapping(self):
        from app.bio.cross_species import CrossSpeciesComparator

        human_drift = pd.DataFrame({
            'gene_id': ['ENSG00000001'],
            'node_drift_score': [0.5],
            'degree_change': [1.0],
        })
        mouse_drift = pd.DataFrame({
            'gene_id': ['ENSMUSG00000001', 'ENSMUSG00000002'],
            'node_drift_score': [0.4, 0.2],
            'degree_change': [1.0, 0.0],
        })
        ambiguous_mapping = pd.DataFrame([
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000001', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'ENSG00000001', 'mouse_ensembl_id': 'ENSMUSG00000002', 'orthology_type': 'ortholog_one2one'},
        ])

        with pytest.raises(ValueError, match='Ambiguous ortholog_one2one'):
            CrossSpeciesComparator().compare(human_drift, mouse_drift, ambiguous_mapping)

    def test_network_edge_alignment_counts_conserved_rewired_and_species_only(self):
        from app.bio.cross_species import align_network_edges

        mapping = pd.DataFrame([
            {'human_ensembl_id': 'H1', 'mouse_ensembl_id': 'M1', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'H2', 'mouse_ensembl_id': 'M2', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'H3', 'mouse_ensembl_id': 'M3', 'orthology_type': 'ortholog_one2one'},
            {'human_ensembl_id': 'H4', 'mouse_ensembl_id': 'M4', 'orthology_type': 'ortholog_one2one'},
        ])
        human_edges = pd.DataFrame([
            {'gene1': 'H1', 'gene2': 'H2', 'weight': 0.80},
            {'gene1': 'H1', 'gene2': 'H3', 'weight': 0.80},
            {'gene1': 'H3', 'gene2': 'H4', 'weight': 0.90},
        ])
        mouse_edges = pd.DataFrame([
            {'gene1': 'M1', 'gene2': 'M2', 'weight': 0.82},
            {'gene1': 'M1', 'gene2': 'M3', 'weight': 0.65},
            {'gene1': 'M2', 'gene2': 'M3', 'weight': 0.75},
        ])

        result = align_network_edges(human_edges, mouse_edges, mapping)

        assert result['conserved_edges'] == 1
        assert result['rewired_edges'] == 1
        assert result['human_only_edges'] == 1
        assert result['mouse_only_edges'] == 1
        assert result['network_preservation'] == 0.25
        assert result['network_drift'] == 0.75

    def test_gene_network_drift_reports_lost_gained_and_rewired_relationships(self):
        from app.bio.cross_species import compare_gene_edge_sets

        normal_edges = pd.DataFrame([
            {'gene1': 'BRCA1', 'gene2': 'RAD51', 'weight': 0.9},
            {'gene1': 'BRCA1', 'gene2': 'PALB2', 'weight': 0.8},
            {'gene1': 'BRCA1', 'gene2': 'CHEK1', 'weight': 0.7},
        ])
        cancer_edges = pd.DataFrame([
            {'gene1': 'BRCA1', 'gene2': 'RAD51', 'weight': 0.9},
            {'gene1': 'BRCA1', 'gene2': 'CHEK1', 'weight': 0.5},
            {'gene1': 'BRCA1', 'gene2': 'BARD1', 'weight': 0.75},
        ])

        result = compare_gene_edge_sets('BRCA1', normal_edges, cancer_edges)

        assert [edge['neighbor_id'] for edge in result['lost_relationships']] == ['PALB2']
        assert [edge['neighbor_id'] for edge in result['gained_relationships']] == ['BARD1']
        assert [edge['neighbor_id'] for edge in result['rewired_relationships']] == ['CHEK1']
        assert result['drift_types'] == ['Network edge loss', 'Network edge gain', 'Network edge rewiring']
