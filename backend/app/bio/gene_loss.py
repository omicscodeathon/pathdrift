from __future__ import annotations

import base64
import io
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


def summarize_image(image: np.ndarray | list | str | None) -> Dict[str, float | int]:
    """Compute a compact summary for a microscopy or pathology image.

    The summary is intentionally lightweight and deterministic so it can be used in a
    real-time UI without external image-processing libraries.
    """
    if image is None:
        return {"width": 0, "height": 0, "mean_intensity": 0.0, "edge_density": 0.0}

    arr = np.asarray(image)
    if arr.size == 0:
        return {"width": 0, "height": 0, "mean_intensity": 0.0, "edge_density": 0.0}

    if arr.ndim == 2:
        gray = arr.astype(np.float32)
    elif arr.ndim == 3:
        gray = arr[:, :, :3].mean(axis=2).astype(np.float32)
    else:
        raise ValueError("Image input must be 2D grayscale or 3-channel RGB data.")

    height, width = gray.shape
    mean_intensity = float(gray.mean())

    vertical_edges = np.abs(np.diff(gray, axis=0))
    horizontal_edges = np.abs(np.diff(gray, axis=1))
    edge_strength = vertical_edges if vertical_edges.size >= horizontal_edges.size else horizontal_edges

    edge_density = float(edge_strength.mean() / max(gray.max(), 1.0)) if edge_strength.size else 0.0

    return {
        "width": int(width),
        "height": int(height),
        "mean_intensity": mean_intensity,
        "edge_density": edge_density,
    }


def decode_image_from_data_url(data_url: str) -> np.ndarray:
    if not data_url.startswith("data:image"):
        raise ValueError("Image payload must be a base64 data URL.")
    header, payload = data_url.split(",", 1)
    if ";base64" not in header:
        raise ValueError("Only base64-encoded image data is supported.")
    raw = base64.b64decode(payload)
    image = np.asarray(_read_image_bytes(raw))
    if image.size == 0:
        raise ValueError("Image payload could not be decoded.")
    return image


def _read_image_bytes(raw: bytes) -> np.ndarray:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            return np.array(img.convert("RGB"))
    except Exception:
        return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 1)


class GeneLossRiskModel:
    """A lightweight gene-loss risk model based on expression loss + PPI context."""

    def __init__(self) -> None:
        self._expression_min: Optional[float] = None
        self._expression_max: Optional[float] = None
        self._degree_max: Optional[int] = None
        self._graph: Dict[str, set[str]] = {}

    def fit(
        self,
        genes: Sequence[str],
        expression: Dict[str, float],
        interactions: Sequence[Tuple[str, str]],
    ) -> "GeneLossRiskModel":
        self._graph = self._build_graph(genes, interactions)
        values = [float(expression.get(g, 0.0)) for g in genes]
        self._expression_min = min(values) if values else 0.0
        self._expression_max = max(values) if values else 1.0
        self._degree_max = max(len(v) for v in self._graph.values()) if self._graph else 1
        return self

    def predict_risk(
        self,
        genes: Sequence[str],
        expression: Dict[str, float],
        interactions: Sequence[Tuple[str, str]],
    ) -> Dict[str, Dict[str, float | bool]]:
        graph = self._build_graph(genes, interactions)
        gene_set = list(dict.fromkeys(genes))
        if not gene_set:
            return {}

        if self._expression_min is None or self._expression_max is None:
            self.fit(gene_set, expression, interactions)

        results: Dict[str, Dict[str, float | bool]] = {}
        max_degree = max(len(v) for v in graph.values()) if graph else 1
        for gene in gene_set:
            expr = float(expression.get(gene, 0.0))
            degree = len(graph.get(gene, set()))
            neighbours = [expression.get(n, 0.0) for n in graph.get(gene, set())]
            neighbor_support = float(np.mean(neighbours)) if neighbours else 0.0

            expr_norm = 1.0 - self._normalize_value(expr, self._expression_min, self._expression_max)
            degree_norm = degree / max(max_degree, 1)
            support_penalty = 1.0 - self._normalize_value(neighbor_support, self._expression_min, self._expression_max)
            risk_score = float(np.clip(0.5 * expr_norm + 0.25 * support_penalty + 0.25 * degree_norm, 0.0, 1.0))
            probability = float(np.clip(risk_score, 0.0, 1.0))
            results[gene] = {
                "risk_score": risk_score,
                "probability": probability,
                "predicted_loss": probability >= 0.5,
            }
        return results

    @staticmethod
    def _build_graph(genes: Sequence[str], interactions: Sequence[Tuple[str, str]]) -> Dict[str, set[str]]:
        graph: Dict[str, set[str]] = {gene: set() for gene in genes}
        for left, right in interactions:
            if left not in graph:
                graph[left] = set()
            if right not in graph:
                graph[right] = set()
            graph[left].add(right)
            graph[right].add(left)
        return graph

    @staticmethod
    def _normalize_value(value: float, minimum: float, maximum: float) -> float:
        if maximum == minimum:
            return 0.0
        return float((value - minimum) / (maximum - minimum))


def build_ppi_network(genes: Sequence[str], interactions: Sequence[Tuple[str, str]]) -> Dict[str, List[Dict[str, object]]]:
    graph = GeneLossRiskModel._build_graph(genes, interactions)
    nodes = [
        {"id": gene, "label": gene, "degree": len(graph.get(gene, set()))}
        for gene in genes
    ]
    edges = [
        {"source": left, "target": right}
        for left, right in interactions
        if left in graph and right in graph
    ]
    return {"nodes": nodes, "edges": edges}
