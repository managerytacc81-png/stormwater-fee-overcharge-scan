"""
ArcGIS FeatureServer Stormwater Utility Parcel Fetcher.

Pulls public ArcGIS FeatureServer stormwater billing parcel layers with pagination.
Handles non-zero layer IDs by inspecting FeatureServer?f=json metadata first.
Ensures correct uppercase 'ArcGIS/rest' formatting in REST service URLs.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stormwater_fetcher")


# Verified Rails Configuration
SALISBURY_URL = (
    "https://services6.arcgis.com/Hx8jJ6McXQ0jnqLk/ArcGIS/rest/services/Parcels_with_ERU1/FeatureServer"
)
SALISBURY_TARGET_LAYER = 38
SALISBURY_FIELDS = [
    "acctid",
    "zoning",
    "lu",
    "desclu",
    "is_sqft",
    "indiv_eru",
    "eru_rnd",
    "indiv_fee",
    "annualrev",
    "billablekey",
]

EASTON_URL = (
    "https://services2.arcgis.com/G6TP4SnXQoFs2r0T/ArcGIS/rest/services/EastonStormwaterUtilityParcels/FeatureServer"
)
EASTON_TARGET_LAYER = 1
EASTON_FIELDS = [
    "PARCELID",
    "BILLNO",
    "IMPAREA",
    "NUM_ERUS",
    "USECD",
    "BLDGVAL",
    "USEDSCRP",
    "CALCMETHOD",
    "NUMUNITS",
    "UNITIMPAREA",
]


@dataclass
class JurisdictionConfig:
    name: str
    feature_server_url: str
    target_layer_id: Optional[int]
    target_layer_name_hint: str
    fields: List[str]
    eru_size_sqft: float
    annual_rate_per_eru: float
    parcel_id_field: str
    imp_area_field: str
    billed_eru_field: str
    billed_fee_field: Optional[str]
    land_use_desc_field: str
    land_use_code_field: str
    billing_class_field: str
    bldg_val_field: Optional[str] = None


CONFIG_SALISBURY = JurisdictionConfig(
    name="Salisbury, MD",
    feature_server_url=SALISBURY_URL,
    target_layer_id=SALISBURY_TARGET_LAYER,
    target_layer_name_hint="Parcels with ERU",
    fields=SALISBURY_FIELDS,
    eru_size_sqft=3344.0,
    annual_rate_per_eru=30.0,
    parcel_id_field="acctid",
    imp_area_field="is_sqft",
    billed_eru_field="eru_rnd",
    billed_fee_field="annualrev",
    land_use_desc_field="desclu",
    land_use_code_field="lu",
    billing_class_field="billablekey",
    bldg_val_field=None,
)

CONFIG_EASTON = JurisdictionConfig(
    name="Easton, MD",
    feature_server_url=EASTON_URL,
    target_layer_id=EASTON_TARGET_LAYER,
    target_layer_name_hint="Stormwater Utility Parcels",
    fields=EASTON_FIELDS,
    eru_size_sqft=3900.0,
    annual_rate_per_eru=81.0,  # $6.75/month standard ERU rate = $81.00/yr
    parcel_id_field="PARCELID",
    imp_area_field="IMPAREA",
    billed_eru_field="NUM_ERUS",
    billed_fee_field=None,  # Derived as NUM_ERUS * annual_rate_per_eru
    land_use_desc_field="USEDSCRP",
    land_use_code_field="USECD",
    billing_class_field="CALCMETHOD",
    bldg_val_field="BLDGVAL",
)

PRESETS = {
    "salisbury": CONFIG_SALISBURY,
    "easton": CONFIG_EASTON,
}


def normalize_url(url: str) -> str:
    """
    Ensure the ArcGIS REST URL uses uppercase 'ArcGIS/rest'.
    Trims trailing slashes and normalizes case patterns.
    """
    clean = url.strip().rstrip("/")
    # Replace any variant of /arcgis/rest/ with uppercase /ArcGIS/rest/
    normalized = re.sub(r"/arcgis/rest/", "/ArcGIS/rest/", clean, flags=re.IGNORECASE)
    return normalized


def get_service_metadata(service_url: str, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """
    Fetch FeatureServer root metadata (?f=json) to inspect layer listings.
    """
    sess = session or requests.Session()
    norm_url = normalize_url(service_url)
    req_url = f"{norm_url}?f=json"
    
    logger.info("Reading FeatureServer metadata from: %s", req_url)
    resp = sess.get(req_url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"ArcGIS server error: {data['error']}")
    return data


def discover_layers(service_url: str, session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
    """
    Read layer list from FeatureServer?f=json first.
    Returns list of dicts with 'id', 'name', 'type', etc.
    """
    metadata = get_service_metadata(service_url, session=session)
    layers = metadata.get("layers", [])
    logger.info("Discovered %d layer(s) on FeatureServer", len(layers))
    for lyr in layers:
        logger.info(" - Layer ID %s: '%s' (%s)", lyr.get("id"), lyr.get("name"), lyr.get("type"))
    return layers


def resolve_layer_id(
    service_url: str,
    preferred_layer_id: Optional[int] = None,
    name_hint: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> int:
    """
    Resolve and verify layer id from FeatureServer metadata.
    Enforces reading layer list first as layer IDs are NOT always 0.
    """
    layers = discover_layers(service_url, session=session)
    if not layers:
        raise ValueError(f"No layers discovered at {service_url}")

    # If preferred_layer_id specified, verify it exists
    if preferred_layer_id is not None:
        matching = [lyr for lyr in layers if lyr.get("id") == preferred_layer_id]
        if matching:
            logger.info("Confirmed specified layer ID %d ('%s')", preferred_layer_id, matching[0].get("name"))
            return preferred_layer_id
        logger.warning(
            "Specified layer ID %d not found in layer list. Discovered IDs: %s",
            preferred_layer_id,
            [lyr.get("id") for lyr in layers],
        )

    # If name hint provided, search by name
    if name_hint:
        hint_lower = name_hint.lower()
        for lyr in layers:
            if hint_lower in str(lyr.get("name", "")).lower():
                lid = lyr.get("id")
                logger.info("Matched layer by name hint '%s': ID %s ('%s')", name_hint, lid, lyr.get("name"))
                return int(lid)

    # Search for common stormwater keywords
    keywords = ["parcel", "eru", "stormwater", "utility"]
    for kw in keywords:
        for lyr in layers:
            if kw in str(lyr.get("name", "")).lower():
                lid = lyr.get("id")
                logger.info("Matched layer by keyword '%s': ID %s ('%s')", kw, lid, lyr.get("name"))
                return int(lid)

    # Default to the first layer in metadata
    first_id = int(layers[0]["id"])
    logger.info("Defaulting to first discovered layer ID %d ('%s')", first_id, layers[0].get("name"))
    return first_id


def get_layer_metadata(
    service_url: str, layer_id: int, session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    """
    Get detailed layer metadata including maxRecordCount and field definitions.
    """
    sess = session or requests.Session()
    norm_url = normalize_url(service_url)
    req_url = f"{norm_url}/{layer_id}?f=json"
    logger.info("Fetching layer metadata from: %s", req_url)
    resp = sess.get(req_url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"ArcGIS layer metadata error: {data['error']}")
    return data


def fetch_feature_layer(
    service_url: str,
    layer_id: Optional[int] = None,
    fields: Optional[List[str]] = None,
    where: str = "1=1",
    max_records: Optional[int] = None,
    batch_size: Optional[int] = None,
    name_hint: Optional[str] = None,
    session: Optional[requests.Session] = None,
    retry_attempts: int = 3,
    retry_delay: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Fetch records from an ArcGIS FeatureServer layer with robust pagination.
    
    1. Reads layer list from FeatureServer?f=json first to resolve layer ID.
    2. Queries layer metadata to determine server maxRecordCount.
    3. Paginates across resultOffset and resultRecordCount until completion or max_records.
    4. Returns list of attribute dictionaries.
    """
    sess = session or requests.Session()
    norm_url = normalize_url(service_url)
    
    # Enforce reading layer list from FeatureServer?f=json first
    target_layer_id = resolve_layer_id(
        norm_url, preferred_layer_id=layer_id, name_hint=name_hint, session=sess
    )
    
    layer_meta = get_layer_metadata(norm_url, target_layer_id, session=sess)
    server_max = layer_meta.get("maxRecordCount", 1000)
    
    # Calculate effective batch size
    effective_batch = server_max
    if batch_size is not None and batch_size > 0:
        effective_batch = min(batch_size, server_max)
    
    query_url = f"{norm_url}/{target_layer_id}/query"
    out_fields_str = ",".join(fields) if fields else "*"
    
    all_features: List[Dict[str, Any]] = []
    offset = 0
    
    logger.info(
        "Starting pagination query for layer %d at %s (batch size %d, max_records=%s)",
        target_layer_id,
        query_url,
        effective_batch,
        max_records,
    )
    
    while True:
        # Determine remaining records if limit specified
        records_to_request = effective_batch
        if max_records is not None:
            remaining = max_records - len(all_features)
            if remaining <= 0:
                break
            records_to_request = min(effective_batch, remaining)
            
        params = {
            "where": where,
            "outFields": out_fields_str,
            "returnGeometry": "false",
            "resultOffset": offset,
            "resultRecordCount": records_to_request,
            "f": "json",
        }
        
        # Retry loop for resilience
        data = None
        for attempt in range(1, retry_attempts + 1):
            try:
                resp = sess.get(query_url, params=params, timeout=45)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise ValueError(f"ArcGIS query returned error: {data['error']}")
                break
            except Exception as exc:
                if attempt == retry_attempts:
                    logger.error("Failed query offset %d after %d attempts: %s", offset, attempt, exc)
                    raise
                logger.warning("Query failed (attempt %d/%d): %s. Retrying in %0.1fs...", attempt, retry_attempts, exc, retry_delay)
                time.sleep(retry_delay * attempt)
                
        features = data.get("features", [])
        if not features:
            logger.info("No more features returned at offset %d. Pagination complete.", offset)
            break
            
        for feat in features:
            attrs = feat.get("attributes", feat)
            all_features.append(attrs)
            if max_records is not None and len(all_features) >= max_records:
                break
                
        logger.info(
            "Fetched %d features (offset %d, total accumulated: %d)",
            len(features),
            offset,
            len(all_features),
        )
        
        if max_records is not None and len(all_features) >= max_records:
            logger.info("Reached requested max_records limit (%d).", max_records)
            break
            
        # Check termination condition:
        # If server indicates exceededTransferLimit is False, and count < batch, we reached the end
        exceeded = data.get("exceededTransferLimit", False)
        if len(features) < records_to_request and not exceeded:
            logger.info("End of dataset reached (returned %d < requested %d).", len(features), records_to_request)
            break
            
        offset += len(features)
        
    logger.info("Finished fetching %d total records from layer %d.", len(all_features), target_layer_id)
    return all_features


def fetch_jurisdiction_data(
    config: JurisdictionConfig,
    max_records: Optional[int] = None,
    batch_size: Optional[int] = None,
    output_path: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch parcel records for a preconfigured jurisdiction and optionally save to disk.
    """
    records = fetch_feature_layer(
        service_url=config.feature_server_url,
        layer_id=config.target_layer_id,
        fields=config.fields,
        name_hint=config.target_layer_name_hint,
        max_records=max_records,
        batch_size=batch_size,
        session=session,
    )
    
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        logger.info("Saved %d records to %s", len(records), output_path)
        
    return records


def parse_args():
    parser = argparse.ArgumentParser(description="Public ArcGIS FeatureServer Stormwater Parcel Fetcher")
    parser.add_argument(
        "--jurisdiction",
        choices=["salisbury", "easton", "custom"],
        default="salisbury",
        help="Target jurisdiction preset or 'custom'",
    )
    parser.add_argument("--url", help="Custom ArcGIS FeatureServer URL")
    parser.add_argument("--layer", type=int, help="Layer ID (reads layer list from FeatureServer?f=json first)")
    parser.add_argument("--fields", help="Comma-separated field list")
    parser.add_argument("--limit", type=int, help="Maximum number of records to fetch")
    parser.add_argument("--batch-size", type=int, help="Batch size for pagination")
    parser.add_argument("--output", help="Path to save JSON output")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.jurisdiction in PRESETS:
        cfg = PRESETS[args.jurisdiction]
        output = args.output or f"data/{args.jurisdiction}_parcels.json"
        fetch_jurisdiction_data(cfg, max_records=args.limit, batch_size=args.batch_size, output_path=output)
    elif args.jurisdiction == "custom":
        if not args.url:
            logger.error("--url is required when using --jurisdiction custom")
            sys.exit(1)
        fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
        output = args.output or "data/custom_parcels.json"
        records = fetch_feature_layer(
            service_url=args.url,
            layer_id=args.layer,
            fields=fields,
            max_records=args.limit,
            batch_size=args.batch_size,
        )
        if output:
            os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            logger.info("Saved %d records to %s", len(records), output)


if __name__ == "__main__":
    main()
