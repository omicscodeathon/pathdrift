import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.bio.gene_loss import GeneLossRiskModel, expression_loss_evidence, module_disruption_evidence, summarize_image


def test_summarize_image_returns_signal_metrics():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[8:24, 8:24] = 255
    summary = summarize_image(image)

    assert summary["width"] == 32
    assert summary["height"] == 32
    assert summary["mean_intensity"] >= 0
    assert summary["edge_density"] >= 0


def test_gene_loss_model_predicts_risk_for_gene_sets():
    genes = ["GENE_A", "GENE_B", "GENE_C", "GENE_D"]
    expression = {"GENE_A": 10.0, "GENE_B": 8.5, "GENE_C": 2.2, "GENE_D": 1.1}
    interactions = [
        ("GENE_A", "GENE_B"),
        ("GENE_A", "GENE_C"),
        ("GENE_B", "GENE_D"),
    ]
    model = GeneLossRiskModel()
    model.fit(genes, expression, interactions)
    scores = model.predict_risk(genes, expression, interactions)

    assert len(scores) == len(genes)
    assert scores["GENE_C"]["probability"] >= 0
    assert scores["GENE_C"]["predicted_loss"] in {True, False}


def test_expression_loss_only_includes_significant_downregulated_genes():
    import pandas as pd

    results = pd.DataFrame({
        "gene_id": ["G_DOWN", "G_UP", "G_NOT_SIGNIFICANT"],
        "log2fc": [-1.4, 1.2, -0.2],
        "padj": [0.01, 0.01, 0.8],
        "significant": [True, True, False],
    })

    evidence = expression_loss_evidence(results)

    assert list(evidence) == ["G_DOWN"]
    assert evidence["G_DOWN"]["log2fc"] == -1.4


def test_module_disruption_matches_modules_by_gene_overlap_not_module_label():
    import pandas as pd

    normal_features = pd.DataFrame({
        "gene_id": ["G1", "G2", "G3", "G4"],
        "module": ["M1", "M1", "M1", "M2"],
    })
    disease_features = pd.DataFrame({
        "gene_id": ["G1", "G2", "G3", "G4"],
        "module": ["M7", "M7", "M8", "M3"],
    })

    evidence = module_disruption_evidence(normal_features, disease_features)

    assert set(evidence) == {"G3"}
    assert evidence["G3"]["normal_module"] == "M1"
    assert evidence["G3"]["matched_disease_module"] == "M7"
    assert evidence["G3"]["disease_module"] == "M8"
