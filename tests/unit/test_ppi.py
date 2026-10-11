import httpx
import pytest
from fastapi import HTTPException

from app.api.routes.ppi import _string_error_detail, _validate_identifier
from app.bio.ppi import normalize_string_network


def test_validate_identifier_accepts_symbols_and_rejects_autocomplete_labels():
    assert _validate_identifier(" TP53 ") == "TP53"
    assert _validate_identifier("ENSG00000141510") == "ENSG00000141510"
    with pytest.raises(HTTPException, match="Enter one gene symbol"):
        _validate_identifier("TP53 · ENSG00000141510")


def test_string_error_detail_removes_html_from_error_message():
    response = httpx.Response(
        400,
        json=[{"ErrorMessage": "<b>Illegal Characters</b><br/>Use a gene identifier."}],
    )

    assert _string_error_detail(response, "identifier mapping") == (
        "STRING identifier mapping returned HTTP 400: Illegal Characters Use a gene identifier."
    )


def test_normalize_string_network_filters_confidence_and_counts_real_rows():
    seed = {"string_id": "9606.seed", "preferred_name": "BRCA1", "query": "BRCA1"}
    interactions = [
        {"stringId_A": "9606.seed", "stringId_B": "9606.rad51", "preferredName_A": "BRCA1", "preferredName_B": "RAD51", "score": 0.91, "escore": 0.8, "dscore": 0.7},
        {"stringId_A": "9606.seed", "stringId_B": "9606.palb2", "preferredName_A": "BRCA1", "preferredName_B": "PALB2", "score": 0.55, "escore": 0.2, "dscore": 0.3},
        {"stringId_A": "9606.seed", "stringId_B": "9606.tp53", "preferredName_A": "BRCA1", "preferredName_B": "TP53", "score": 0.33, "escore": 0.1, "dscore": 0.1},
    ]

    high = normalize_string_network(seed, interactions, "high")
    medium = normalize_string_network(seed, interactions, "medium")
    all_scores = normalize_string_network(seed, interactions, "all")

    assert high["node_count"] == 2
    assert high["interaction_count"] == 1
    assert medium["interaction_count"] == 2
    assert all_scores["interaction_count"] == 3
    assert high["interactions"][0]["preferred_name_b"] == "RAD51"