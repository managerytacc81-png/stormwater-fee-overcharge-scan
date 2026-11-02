"""
End-to-End Stormwater Fee Overcharge Scanner & Appeal Automation Engine.

Orchestrates:
1. Fetching live FeatureServer parcel layers (Salisbury MD & Easton MD) with pagination
2. Scoring suspect parcels across 4 audit vectors (arithmetic mismatch, wrong class, impervious outlier, exempt billed)
3. Ranking overbilling prospects into overbilling_prospects.csv
4. Generating jurisdiction-agnostic administrative appeal packets into appeal_packets/
"""

import argparse
import logging
import os
import sys
from typing import List

from fetcher import (
    CONFIG_SALISBURY,
    CONFIG_EASTON,
    fetch_jurisdiction_data,
)
from misbill_scorer import score_parcels, export_prospects_csv, ProspectRecord
from appeal_drafter import draft_appeal_packets_from_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stormwater_scanner")


def run_full_pipeline(
    salisbury_limit: int = 0,
    easton_limit: int = 0,
    output_csv: str = "overbilling_prospects.csv",
    appeal_dir: str = "appeal_packets",
    top_appeals: int = 15,
    use_cache: bool = True,
    data_dir: str = "data",
) -> List[ProspectRecord]:
    """
    Run complete fetch -> score -> rank -> draft pipeline.
    """
    os.makedirs(data_dir, exist_ok=True)
    salisbury_cache = os.path.join(data_dir, "salisbury_parcels.json")
    easton_cache = os.path.join(data_dir, "easton_parcels.json")
    
    all_raw_parcels = []
    
    # 1. Salisbury MD Fetch
    salis_limit_val = None if salisbury_limit == 0 else salisbury_limit
    if use_cache and os.path.exists(salisbury_cache):
        logger.info("Loading cached Salisbury parcels from %s", salisbury_cache)
        import json
        with open(salisbury_cache, "r", encoding="utf-8") as f:
            salis_data = json.load(f)
            all_raw_parcels.extend(salis_data)
    else:
        logger.info("Fetching Salisbury MD FeatureServer layer 38 (Parcels with ERU)...")
        salis_data = fetch_jurisdiction_data(
            CONFIG_SALISBURY,
            max_records=salis_limit_val,
            output_path=salisbury_cache if use_cache else None,
        )
        all_raw_parcels.extend(salis_data)

    # 2. Easton MD Fetch
    easton_limit_val = None if easton_limit == 0 else easton_limit
    if use_cache and os.path.exists(easton_cache):
        logger.info("Loading cached Easton parcels from %s", easton_cache)
        import json
        with open(easton_cache, "r", encoding="utf-8") as f:
            easton_data = json.load(f)
            all_raw_parcels.extend(easton_data)
    else:
        logger.info("Fetching Easton MD FeatureServer layer 1 (Stormwater Utility Parcels)...")
        easton_data = fetch_jurisdiction_data(
            CONFIG_EASTON,
            max_records=easton_limit_val,
            output_path=easton_cache if use_cache else None,
        )
        all_raw_parcels.extend(easton_data)

    logger.info("Total raw parcels collected across jurisdictions: %d", len(all_raw_parcels))

    # 3. Score Misbilling Anomalies
    prospects = score_parcels(all_raw_parcels)
    
    # 4. Export Ranked CSV
    export_prospects_csv(prospects, output_csv)
    
    # 5. Draft Appeal Packets
    draft_appeal_packets_from_csv(
        csv_path=output_csv,
        output_dir=appeal_dir,
        top_n=top_appeals,
        min_overcharge=50.0,
    )
    
    return prospects


def parse_args():
    parser = argparse.ArgumentParser(description="Stormwater Fee Overcharge Scanner")
    parser.add_argument("--salisbury-limit", type=int, default=0, help="Limit records for Salisbury (0 = full)")
    parser.add_argument("--easton-limit", type=int, default=0, help="Limit records for Easton (0 = full)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass cached files and fetch fresh from live rails")
    parser.add_argument("--output-csv", default="overbilling_prospects.csv", help="Ranked prospects CSV output")
    parser.add_argument("--appeal-dir", default="appeal_packets", help="Directory for generated appeal packets")
    parser.add_argument("--top-appeals", type=int, default=15, help="Number of top appeal packets to draft")
    return parser.parse_args()


def main():
    args = parse_args()
    run_full_pipeline(
        salisbury_limit=args.salisbury_limit,
        easton_limit=args.easton_limit,
        output_csv=args.output_csv,
        appeal_dir=args.appeal_dir,
        top_appeals=args.top_appeals,
        use_cache=not args.no_cache,
    )


if __name__ == "__main__":
    main()
