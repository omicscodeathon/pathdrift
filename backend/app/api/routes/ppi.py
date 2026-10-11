"""Live STRING protein interaction network routes."""
import asyncio
import html
import json
import re
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.bio.ppi import CONFIDENCE_THRESHOLDS, normalize_string_network
from app.models import SpeciesEnum, User

router = APIRouter()

STRING_API = "https://string-db.org/api/json"
STRING_TAXON = {SpeciesEnum.HUMAN: 9606, SpeciesEnum.MOUSE: 10090}


def _string_error_detail(response: httpx.Response, operation: str) -> str:
    response_text = response.text.strip()
    try:
        payload = response.json()
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            response_text = str(payload[0].get("ErrorMessage") or payload[0].get("error") or response_text)
    except ValueError:
        pass
    response_text = html.unescape(re.sub(r"<[^>]*>", " ", response_text))
    response_text = " ".join(response_text.split())
    detail = f"STRING {operation} returned HTTP {response.status_code}"
    if response_text:
        detail = f"{detail}: {response_text[:300]}"
    return detail


def _validate_identifier(value: str) -> str:
    identifier = value.strip()
    if not identifier or not re.fullmatch(r"[A-Za-z0-9_.:-]+", identifier):
        raise HTTPException(
            status_code=400,
            detail="Enter one gene symbol or identifier using only letters, numbers, periods, underscores, colons, or hyphens.",
        )
    return identifier


class PPINetworkRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=100)
    species: SpeciesEnum
    confidence: Literal["high", "medium", "all"] = "high"


@router.post("/network")
async def get_string_ppi_network(
    payload: PPINetworkRequest,
    current_user: User = Depends(get_current_user),
):
    identifier = _validate_identifier(payload.identifier)

    taxon = STRING_TAXON[payload.species]
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "PathDrift/1.0"}) as client:
        try:
            mapping_response = await client.post(
                f"{STRING_API}/get_string_ids",
                data={
                    "identifiers": identifier,
                    "species": taxon,
                    "caller_identity": "PathDrift",
                },
            )
        except httpx.RequestError as error:
            raise HTTPException(status_code=502, detail="Could not connect to STRING identifier mapping") from error

        if mapping_response.status_code == 404:
            raise HTTPException(status_code=404, detail="STRING could not map this identifier for the selected species")
        if mapping_response.is_error:
            status_code = 400 if mapping_response.status_code == 400 else 502
            raise HTTPException(status_code=status_code, detail=_string_error_detail(mapping_response, "identifier mapping"))
        try:
            mappings = mapping_response.json()
        except ValueError as error:
            raise HTTPException(status_code=502, detail="STRING returned an invalid identifier response") from error

        mapping = next(
            (item for item in mappings if str(item.get("ncbiTaxonId")) == str(taxon)),
            None,
        )
        if not mapping or not mapping.get("stringId"):
            raise HTTPException(status_code=404, detail="STRING could not map this identifier for the selected species")

        await asyncio.sleep(1)
        try:
            network_response = await client.post(
                f"{STRING_API}/network",
                data={
                    "identifiers": mapping["stringId"],
                    "species": taxon,
                    "network_type": "physical",
                    "network_flavor": "confidence",
                    "add_nodes": 20,
                    "required_score": round(CONFIDENCE_THRESHOLDS[payload.confidence] * 1000),
                    "caller_identity": "PathDrift",
                },
            )
        except httpx.RequestError as error:
            raise HTTPException(status_code=502, detail="Could not connect to STRING interaction network") from error

    if network_response.is_error:
        raise HTTPException(status_code=502, detail=_string_error_detail(network_response, "network request"))
    try:
        interactions = network_response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="STRING returned an invalid interaction response") from error
    if not isinstance(interactions, list):
        raise HTTPException(status_code=502, detail="STRING returned an unexpected interaction format")

    try:
        network = normalize_string_network(
            {
                "string_id": mapping["stringId"],
                "preferred_name": mapping.get("preferredName"),
                "query": identifier,
            },
            interactions,
            payload.confidence,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not normalize STRING interaction data") from error

    return {
        "source": "STRING",
        "species": payload.species.value,
        "taxon_id": taxon,
        "network_type": "physical",
        "query_identifier": identifier,
        "mapped_query": {
            "string_id": mapping["stringId"],
            "preferred_name": mapping.get("preferredName"),
            "annotation": mapping.get("annotation"),
        },
        "add_nodes_requested": 20,
        "confidence_level": network["confidence"],
        "minimum_combined_score": network["minimum_score"],
        "node_count": network["node_count"],
        "interaction_count": network["interaction_count"],
        "nodes": network["nodes"],
        "interactions": network["interactions"],
        "string_search_url": f"https://string-db.org/cgi/network?identifiers={mapping['stringId']}&species={taxon}&network_type=physical",
    }