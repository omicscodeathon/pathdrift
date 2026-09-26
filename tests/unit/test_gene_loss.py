import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.bio.gene_loss import GeneLossRiskModel, summarize_image


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
