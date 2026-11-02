"""
Stormwater Misbilling Anomaly Scorer & Recovery Estimator.

Flags suspect parcels across four key audit vectors:
1. Fee-vs-impervious arithmetic mismatch (recomputing ERU = is_sqft / ERU_size and fee = ERU_rnd * rate vs billed)
2. Commercial parcel billed at wrong class
3. Extreme outlier impervious area for land-use code (statistical IQR/z-score)
4. Parcels with fee > 0 but land use classified as Exempt

Outputs ranked CSV overbilling_prospects.csv with estimated annual overcharge and 3-year retroactive refund recovery.
"""

import argparse
import csv
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("misbill_scorer")

# Default Jurisdiction ERU Constants
DEFAULT_SALISBURY_ERU_SIZE = 3344.0
DEFAULT_SALISBURY_RATE = 30.0

DEFAULT_EASTON_ERU_SIZE = 3900.0
DEFAULT_EASTON_RATE = 81.0  # Standard $6.75/month = $81.00/yr


@dataclass
class NormalizedParcel:
    parcel_id: str
    jurisdiction: str
    land_use_code: str
    land_use_desc: str
    billing_class: str
    impervious_sqft: float
    billed_eru: float
    billed_annual_fee: float
    eru_size_sqft: float
    rate_per_eru: float
    building_val: float = 0.0
    zoning: str = ""
    owner: str = "Property Owner of Record"
    raw_attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnomalyFlag:
    flag_type: str
    estimated_annual_overcharge: float
    confidence: float
    recomputed_eru: float
    recomputed_annual_fee: float
    description: str
    technical_details: str


@dataclass
class ProspectRecord:
    rank: int
    parcel_id: str
    jurisdiction: str
    land_use_code: str
    land_use_desc: str
    billing_class: str
    impervious_sqft: float
    billed_eru: float
    billed_annual_fee: float
    recomputed_eru: float
    recomputed_annual_fee: float
    estimated_annual_overcharge: float
    estimated_3yr_retro_refund: float
    estimated_total_recovery: float
    contingency_fee_potential: float
    flags: str
    primary_flag: str
    misbill_score: float
    appeal_priority: str
    notes: str


def normalize_parcel_record(raw: Dict[str, Any], jurisdiction_hint: Optional[str] = None) -> NormalizedParcel:
    """
    Map raw attributes from Salisbury, Easton, or generic FeatureServers
    into a standardized NormalizedParcel.
    """
    attrs = raw.get("attributes", raw)
    
    # Detect Salisbury MD schema
    if "acctid" in attrs or "is_sqft" in attrs or "eru_rnd" in attrs:
        pid = str(attrs.get("acctid") or attrs.get("objectid") or "")
        imp_sqft = float(attrs.get("is_sqft") or 0.0)
        billed_eru = float(attrs.get("eru_rnd") or 0.0)
        rate = float(attrs.get("indiv_fee") or DEFAULT_SALISBURY_RATE)
        billed_fee = float(attrs.get("annualrev") or (billed_eru * rate))
        eru_size = float(attrs.get("eru") or DEFAULT_SALISBURY_ERU_SIZE)
        lu_code = str(attrs.get("lu") or "").strip()
        lu_desc = str(attrs.get("desclu") or "").strip()
        bill_class = str(attrs.get("billablekey") or attrs.get("billing") or "").strip()
        zoning = str(attrs.get("zoning") or "").strip()
        return NormalizedParcel(
            parcel_id=pid,
            jurisdiction="Salisbury, MD",
            land_use_code=lu_code,
            land_use_desc=lu_desc,
            billing_class=bill_class,
            impervious_sqft=imp_sqft,
            billed_eru=billed_eru,
            billed_annual_fee=billed_fee,
            eru_size_sqft=eru_size,
            rate_per_eru=rate,
            building_val=0.0,
            zoning=zoning,
            raw_attributes=attrs,
        )

    # Detect Easton MD schema
    if "PARCELID" in attrs or "IMPAREA" in attrs or "NUM_ERUS" in attrs:
        pid = str(attrs.get("PARCELID") or attrs.get("OBJECTID") or "")
        imp_sqft = float(attrs.get("IMPAREA") or 0.0)
        billed_eru = float(attrs.get("NUM_ERUS") or 0.0)
        rate = DEFAULT_EASTON_RATE
        billed_fee = billed_eru * rate
        eru_size = DEFAULT_EASTON_ERU_SIZE
        lu_code = str(attrs.get("USECD") or "").strip()
        lu_desc = str(attrs.get("USEDSCRP") or "").strip()
        bill_class = str(attrs.get("CALCMETHOD") or "").strip()
        bldg_val = float(attrs.get("BLDGVAL") or 0.0)
        return NormalizedParcel(
            parcel_id=pid,
            jurisdiction="Easton, MD",
            land_use_code=lu_code,
            land_use_desc=lu_desc,
            billing_class=bill_class,
            impervious_sqft=imp_sqft,
            billed_eru=billed_eru,
            billed_annual_fee=billed_fee,
            eru_size_sqft=eru_size,
            rate_per_eru=rate,
            building_val=bldg_val,
            raw_attributes=attrs,
        )

    # Generic fallback
    pid = str(attrs.get("parcel_id") or attrs.get("id") or attrs.get("OBJECTID") or "UNKNOWN")
    imp_sqft = float(attrs.get("impervious_sqft") or attrs.get("imp_area") or 0.0)
    billed_eru = float(attrs.get("billed_eru") or attrs.get("eru") or 0.0)
    rate = float(attrs.get("rate") or 30.0)
    billed_fee = float(attrs.get("billed_fee") or (billed_eru * rate))
    eru_size = float(attrs.get("eru_size") or 3344.0)
    lu_code = str(attrs.get("land_use_code") or attrs.get("lu") or "").strip()
    lu_desc = str(attrs.get("land_use_desc") or attrs.get("desclu") or "").strip()
    bill_class = str(attrs.get("billing_class") or "").strip()

    return NormalizedParcel(
        parcel_id=pid,
        jurisdiction=jurisdiction_hint or "Municipal Stormwater Utility",
        land_use_code=lu_code,
        land_use_desc=lu_desc,
        billing_class=bill_class,
        impervious_sqft=imp_sqft,
        billed_eru=billed_eru,
        billed_annual_fee=billed_fee,
        eru_size_sqft=eru_size,
        rate_per_eru=rate,
        raw_attributes=attrs,
    )


# =============================================================================
# Audit Flag Evaluators
# =============================================================================

def check_exempt_billed(parcel: NormalizedParcel) -> Optional[AnomalyFlag]:
    """
    Flag 4: Parcels with fee > 0 but desclu / usecd is classified as Exempt.
    Churches, synagogues, charitable institutions, educational facilities,
    and municipal/government entities billed for stormwater fees.
    """
    desc_upper = parcel.land_use_desc.upper()
    code_upper = parcel.land_use_code.upper()
    class_upper = parcel.billing_class.upper()
    
    is_exempt = False
    
    # Explicit exempt keywords in description
    exempt_keywords = [
        "EXEMPT",
        "CHURCH",
        "SYNAGOGUE",
        "CHARITABLE",
        "RELIGIOUS",
        "PARSONAGE",
        "RECTORY",
        "MUNICIPAL",
        "TOWN OF",
        "COUNTY OF",
        "LIBRARIES",
        "MUSEUM",
        "COLLEGE OR UNIVERSITY PRIVATE",
        "VACANT EDUCATIONAL PRIVATE",
        "HOUSING, OTHER",
    ]
    for kw in exempt_keywords:
        if kw in desc_upper:
            is_exempt = True
            break
            
    # Salisbury code patterns
    if code_upper in ["E", "EC"] or "EXEMPT" in class_upper:
        is_exempt = True
        
    # Easton code patterns (9xxx denotes exempt / tax-exempt institutions)
    if code_upper.startswith("9") or class_upper == "EXEMPT":
        is_exempt = True

    if is_exempt and (parcel.billed_annual_fee > 0.0 or parcel.billed_eru > 0.0):
        overcharge = parcel.billed_annual_fee
        details = (
            f"Property is classified as '{parcel.land_use_desc}' (code '{parcel.land_use_code}') "
            f"with exempt status, but was billed {parcel.billed_eru:0.1f} ERUs "
            f"(${parcel.billed_annual_fee:0.2f}/year). Entitled to 100% exemption / $0 fee."
        )
        return AnomalyFlag(
            flag_type="EXEMPT_PROPERTY_BILLED",
            estimated_annual_overcharge=overcharge,
            confidence=0.98,
            recomputed_eru=0.0,
            recomputed_annual_fee=0.0,
            description="Exempt parcel billed stormwater fee (> $0)",
            technical_details=details,
        )
    return None


def check_arithmetic_mismatch(parcel: NormalizedParcel) -> Optional[AnomalyFlag]:
    """
    Flag 1: Fee-vs-impervious arithmetic mismatch.
    Recompute ERU = is_sqft / jurisdiction_eru_size, ERU_rnd = round(ERU),
    and fee = ERU_rnd * rate vs billed fee and billed ERU.
    """
    if parcel.eru_size_sqft <= 0.0:
        return None

    raw_eru = parcel.impervious_sqft / parcel.eru_size_sqft
    recomputed_eru = float(round(raw_eru))
    recomputed_fee = recomputed_eru * parcel.rate_per_eru
    
    # Zero impervious surface edge-case (billed ERU when no impervious area exists)
    if parcel.impervious_sqft <= 10.0 and (parcel.billed_eru > 0.0 or parcel.billed_annual_fee > 0.0):
        overcharge = parcel.billed_annual_fee
        details = (
            f"Parcel has negligible or 0 sq ft impervious surface ({parcel.impervious_sqft:0.1f} sqft), "
            f"yet is billed {parcel.billed_eru:0.1f} ERUs (${parcel.billed_annual_fee:0.2f}/year). "
            f"Recomputed fee is $0.00."
        )
        return AnomalyFlag(
            flag_type="ARITHMETIC_MISMATCH",
            estimated_annual_overcharge=overcharge,
            confidence=0.95,
            recomputed_eru=0.0,
            recomputed_annual_fee=0.0,
            description="Zero/negligible impervious area billed positive ERUs",
            technical_details=details,
        )

    # Standard rounding or fee calculation discrepancy
    eru_diff = parcel.billed_eru - recomputed_eru
    fee_diff = parcel.billed_annual_fee - recomputed_fee
    
    # Flag when billed is materially greater than recomputed
    if fee_diff >= 1.0 or eru_diff >= 1.0:
        overcharge = max(fee_diff, eru_diff * parcel.rate_per_eru)
        details = (
            f"Arithmetic discrepancy: Billed {parcel.billed_eru:0.1f} ERUs (${parcel.billed_annual_fee:0.2f}) "
            f"vs recomputed {recomputed_eru:0.1f} ERUs (${recomputed_fee:0.2f}) based on "
            f"{parcel.impervious_sqft:0.1f} sqft (ERU standard: {parcel.eru_size_sqft:0.0f} sqft @ "
            f"${parcel.rate_per_eru:0.2f}/ERU). Discrepancy: +{overcharge:0.2f}/year."
        )
        return AnomalyFlag(
            flag_type="ARITHMETIC_MISMATCH",
            estimated_annual_overcharge=overcharge,
            confidence=0.92,
            recomputed_eru=recomputed_eru,
            recomputed_annual_fee=recomputed_fee,
            description="Impervious area to ERU/fee arithmetic mismatch",
            technical_details=details,
        )

    return None


def check_wrong_class(parcel: NormalizedParcel) -> Optional[AnomalyFlag]:
    """
    Flag 2: Commercial parcel billed at wrong class.
    Commercial / industrial / multi-family parcels inappropriately assigned
    single-family residential flat rates, assigned erroneous billing multipliers,
    or misclassified into residential tiers.
    """
    desc_upper = parcel.land_use_desc.upper()
    code_upper = parcel.land_use_code.upper()
    class_upper = parcel.billing_class.upper()
    
    is_commercial = (
        code_upper in ["C", "I", "M"]
        or any(
            k in desc_upper
            for k in [
                "COMMERCIAL",
                "INDUSTRIAL",
                "WAREHOUSE",
                "WHSES",
                "STORE",
                "SHOPPING",
                "OFFICE",
                "AUTO",
                "HOTEL",
                "APARTMENTS",
                "APT",
            ]
        )
        or code_upper.startswith(("3", "4", "01"))
    )
    
    if not is_commercial:
        return None

    # Check for wrong billing class assignment
    wrong_class = False
    details = ""
    
    # Salisbury: Commercial parcel classified under Single Family residential schedule
    if "SINGLE FAMILY" in class_upper or ("RESIDENTIAL" in class_upper and "NSF" not in class_upper and parcel.impervious_sqft > 5000):
        wrong_class = True
        details = (
            f"Commercial parcel ('{parcel.land_use_desc}') improperly billed under "
            f"residential schedule '{parcel.billing_class}' instead of commercial non-residential schedule."
        )
    # Salisbury: Commercial parcel with 0 sqft billed under '1 ERU, NSF Residential'
    elif parcel.impervious_sqft <= 10.0 and "1 ERU" in class_upper:
        wrong_class = True
        details = (
            f"Commercial parcel with 0 impervious sqft misassigned to residential minimum tier "
            f"'{parcel.billing_class}' incurring ${parcel.billed_annual_fee:0.2f}/yr."
        )
    # Easton: Commercial property billed with residential flat method 'Assigned' instead of 'Calculated'
    elif class_upper == "ASSIGNED":
        wrong_class = True
        details = (
            f"Commercial parcel ('{parcel.land_use_desc}') assessed under flat residential "
            f"CALCMETHOD 'Assigned' rather than surveyed 'Calculated' method."
        )

    if wrong_class:
        raw_eru = parcel.impervious_sqft / parcel.eru_size_sqft
        recomputed_eru = float(round(raw_eru))
        recomputed_fee = recomputed_eru * parcel.rate_per_eru
        overcharge = max(0.0, parcel.billed_annual_fee - recomputed_fee)
        if overcharge <= 0.0 and parcel.billed_annual_fee > 0.0:
            # If billed fee matches recomputed but class is wrong, potential audit value is present
            overcharge = min(parcel.rate_per_eru, parcel.billed_annual_fee)

        return AnomalyFlag(
            flag_type="WRONG_CLASS_MISBILL",
            estimated_annual_overcharge=overcharge,
            confidence=0.85,
            recomputed_eru=recomputed_eru,
            recomputed_annual_fee=recomputed_fee,
            description="Commercial property billed under incorrect rate class",
            technical_details=details,
        )

    return None


def calculate_cohort_statistics(parcels: List[NormalizedParcel]) -> Dict[str, Dict[str, float]]:
    """
    Calculate statistical distributions (mean, std, Q25, Q50, Q75, IQR)
    of impervious surface by land use category for outlier detection.
    """
    cohorts: Dict[str, List[float]] = {}
    for p in parcels:
        key = p.land_use_desc if p.land_use_desc else p.land_use_code
        if not key:
            continue
        if key not in cohorts:
            cohorts[key] = []
        if p.impervious_sqft > 0:
            cohorts[key].append(p.impervious_sqft)

    stats: Dict[str, Dict[str, float]] = {}
    for key, values in cohorts.items():
        if len(values) < 5:
            continue
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        mean_val = sum(sorted_vals) / n
        variance = sum((x - mean_val) ** 2 for x in sorted_vals) / n
        std_val = math.sqrt(variance)
        
        q25 = sorted_vals[int(n * 0.25)]
        median = sorted_vals[int(n * 0.50)]
        q75 = sorted_vals[int(n * 0.75)]
        iqr = q75 - q25
        
        stats[key] = {
            "count": float(n),
            "mean": mean_val,
            "std": std_val,
            "q25": q25,
            "median": median,
            "q75": q75,
            "iqr": iqr,
            "upper_bound": q75 + 3.0 * iqr,
        }
    return stats


def check_impervious_outlier(
    parcel: NormalizedParcel, cohort_stats: Dict[str, Dict[str, float]]
) -> Optional[AnomalyFlag]:
    """
    Flag 3: Extreme outlier impervious for land-use code.
    Identifies GIS polygon tracing errors where impervious polygons
    inadvertently envelop pervious terrain, retention basins, or adjacent rights-of-way.
    """
    key = parcel.land_use_desc if parcel.land_use_desc else parcel.land_use_code
    if not key or key not in cohort_stats:
        return None

    stats = cohort_stats[key]
    upper_bound = stats["upper_bound"]
    std_val = stats["std"]
    mean_val = stats["mean"]
    
    # Must be > 10,000 sq ft and exceed 3x IQR above Q75 or 3 standard deviations
    is_outlier = False
    z_score = (parcel.impervious_sqft - mean_val) / std_val if std_val > 0 else 0.0
    
    if parcel.impervious_sqft > 10000.0 and (parcel.impervious_sqft > upper_bound or z_score >= 3.0):
        is_outlier = True

    if is_outlier:
        # Benchmark excess impervious surface against 75th percentile + 1.5 * IQR
        benchmark_sqft = stats["q75"] + 1.5 * stats["iqr"]
        excess_sqft = max(0.0, parcel.impervious_sqft - benchmark_sqft)
        excess_eruts = round(excess_sqft / parcel.eru_size_sqft)
        overcharge = excess_eruts * parcel.rate_per_eru
        
        if overcharge >= parcel.rate_per_eru:
            corrected_eru = max(1.0, parcel.billed_eru - excess_eruts)
            recomputed_fee = corrected_eru * parcel.rate_per_eru
            details = (
                f"Extreme impervious outlier: {parcel.impervious_sqft:0.0f} sqft is {z_score:0.1f} std devs "
                f"above cohort mean ({mean_val:0.0f} sqft, median {stats['median']:0.0f} sqft) for '{key}'. "
                f"Probable GIS boundary/digitization overage including pervious/detention acreage. "
                f"Estimated excess: {excess_sqft:0.0f} sqft (~{excess_eruts} ERUs, ${overcharge:0.2f}/yr)."
            )
            return AnomalyFlag(
                flag_type="OUTLIER_IMPERVIOUS",
                estimated_annual_overcharge=overcharge,
                confidence=0.75,
                recomputed_eru=corrected_eru,
                recomputed_annual_fee=recomputed_fee,
                description="Extreme impervious outlier for land-use class",
                technical_details=details,
            )
            
    return None


# =============================================================================
# Scoring & Ranking Pipeline
# =============================================================================

def score_parcel(
    parcel: NormalizedParcel, cohort_stats: Dict[str, Dict[str, float]]
) -> Optional[ProspectRecord]:
    """
    Evaluate all 4 audit vectors against a single parcel,
    aggregate findings, and compute recovery projections.
    """
    flags: List[AnomalyFlag] = []
    
    # Flag 4: Exempt property billed
    f_exempt = check_exempt_billed(parcel)
    if f_exempt:
        flags.append(f_exempt)

    # Flag 1: Arithmetic mismatch
    f_arith = check_arithmetic_mismatch(parcel)
    if f_arith:
        flags.append(f_arith)

    # Flag 2: Wrong class misbill
    f_class = check_wrong_class(parcel)
    if f_class:
        flags.append(f_class)

    # Flag 3: Impervious outlier
    f_outlier = check_impervious_outlier(parcel, cohort_stats)
    if f_outlier:
        flags.append(f_outlier)

    if not flags:
        return None

    # Determine primary overcharge and recomputed values
    # If exempt flag triggered, 100% of bill is overcharge
    if f_exempt:
        est_annual_overcharge = f_exempt.estimated_annual_overcharge
        recomputed_eru = 0.0
        recomputed_fee = 0.0
        primary_flag = "EXEMPT_PROPERTY_BILLED"
    else:
        # Pick the highest confident flag
        flags_sorted = sorted(flags, key=lambda x: (x.estimated_annual_overcharge, x.confidence), reverse=True)
        primary = flags_sorted[0]
        primary_flag = primary.flag_type
        est_annual_overcharge = min(primary.estimated_annual_overcharge, parcel.billed_annual_fee)
        recomputed_eru = primary.recomputed_eru
        recomputed_fee = primary.recomputed_annual_fee

    if est_annual_overcharge <= 0.0:
        return None

    # Statutory 3-year retroactive refund (Berkeley County SC / San Antonio precedents)
    retro_3yr_refund = est_annual_overcharge * 3.0
    total_recovery = est_annual_overcharge + retro_3yr_refund
    contingency_fee = total_recovery * 0.30  # Standard 30% contingency fee
    
    # Calculate composite misbill score (0 - 100)
    flag_type_scores = {
        "EXEMPT_PROPERTY_BILLED": 95.0,
        "ARITHMETIC_MISMATCH": 90.0,
        "WRONG_CLASS_MISBILL": 82.0,
        "OUTLIER_IMPERVIOUS": 72.0,
    }
    base_score = flag_type_scores.get(primary_flag, 70.0)
    # Add bonus for multi-flag confirmation and high dollar value
    value_bonus = min(10.0, math.log10(max(10.0, est_annual_overcharge)) * 2.5)
    multi_bonus = 5.0 if len(flags) > 1 else 0.0
    misbill_score = min(100.0, round(base_score + value_bonus + multi_bonus, 1))

    # Priority tier
    if est_annual_overcharge >= 1000.0 or primary_flag == "EXEMPT_PROPERTY_BILLED":
        priority = "CRITICAL"
    elif est_annual_overcharge >= 300.0:
        priority = "HIGH"
    else:
        priority = "MEDIUM"

    flag_names = "; ".join([f.flag_type for f in flags])
    notes = " | ".join([f.technical_details for f in flags])

    return ProspectRecord(
        rank=0,  # Assigned after global sort
        parcel_id=parcel.parcel_id,
        jurisdiction=parcel.jurisdiction,
        land_use_code=parcel.land_use_code,
        land_use_desc=parcel.land_use_desc,
        billing_class=parcel.billing_class,
        impervious_sqft=parcel.impervious_sqft,
        billed_eru=parcel.billed_eru,
        billed_annual_fee=parcel.billed_annual_fee,
        recomputed_eru=recomputed_eru,
        recomputed_annual_fee=recomputed_fee,
        estimated_annual_overcharge=round(est_annual_overcharge, 2),
        estimated_3yr_retro_refund=round(retro_3yr_refund, 2),
        estimated_total_recovery=round(total_recovery, 2),
        contingency_fee_potential=round(contingency_fee, 2),
        flags=flag_names,
        primary_flag=primary_flag,
        misbill_score=misbill_score,
        appeal_priority=priority,
        notes=notes,
    )


def score_parcels(
    raw_records: List[Dict[str, Any]], jurisdiction_hint: Optional[str] = None
) -> List[ProspectRecord]:
    """
    Score a list of raw parcel attribute dictionaries and return ranked prospects.
    """
    logger.info("Normalizing %d raw parcel records...", len(raw_records))
    parcels = [normalize_parcel_record(r, jurisdiction_hint=jurisdiction_hint) for r in raw_records]
    
    logger.info("Computing cohort statistics for outlier detection...")
    cohort_stats = calculate_cohort_statistics(parcels)
    
    logger.info("Evaluating audit vectors and scoring suspect parcels...")
    prospects: List[ProspectRecord] = []
    for p in parcels:
        res = score_parcel(p, cohort_stats)
        if res:
            prospects.append(res)
            
    # Sort descending by estimated annual overcharge, then misbill score
    prospects.sort(key=lambda x: (x.estimated_annual_overcharge, x.misbill_score), reverse=True)
    
    # Assign ranks
    for idx, p in enumerate(prospects, start=1):
        p.rank = idx

    logger.info(
        "Scoring complete. Flagged %d suspect overbilled parcels out of %d total evaluated.",
        len(prospects),
        len(parcels),
    )
    return prospects


def export_prospects_csv(prospects: List[ProspectRecord], output_path: str):
    """
    Export ranked prospects to CSV file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fields = [
        "rank",
        "parcel_id",
        "jurisdiction",
        "land_use_code",
        "land_use_desc",
        "billing_class",
        "impervious_sqft",
        "billed_eru",
        "billed_annual_fee",
        "recomputed_eru",
        "recomputed_annual_fee",
        "estimated_annual_overcharge",
        "estimated_3yr_retro_refund",
        "estimated_total_recovery",
        "contingency_fee_potential",
        "flags",
        "primary_flag",
        "misbill_score",
        "appeal_priority",
        "notes",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for p in prospects:
            writer.writerow(asdict(p))
    logger.info("Saved %d ranked prospects to %s", len(prospects), output_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Stormwater Fee Misbilling Anomaly Scorer")
    parser.add_argument("--input", required=True, help="Path to input JSON file containing parcel records")
    parser.add_argument(
        "--output",
        default="overbilling_prospects.csv",
        help="Output CSV path (default: overbilling_prospects.csv)",
    )
    parser.add_argument("--jurisdiction", help="Jurisdiction hint (e.g. 'Salisbury, MD' or 'Easton, MD')")
    parser.add_argument("--min-overcharge", type=float, default=10.0, help="Minimum annual overcharge to include")
    return parser.parse_args()


def main():
    args = parse_args()
    if not os.path.exists(args.input):
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)
        
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if isinstance(data, dict) and "features" in data:
        data = data["features"]
    elif not isinstance(data, list):
        logger.error("Invalid JSON format in %s: expected list of parcels or object with 'features'", args.input)
        sys.exit(1)
        
    prospects = score_parcels(data, jurisdiction_hint=args.jurisdiction)
    if args.min_overcharge > 0:
        prospects = [p for p in prospects if p.estimated_annual_overcharge >= args.min_overcharge]
        for idx, p in enumerate(prospects, start=1):
            p.rank = idx
            
    export_prospects_csv(prospects, args.output)


if __name__ == "__main__":
    main()
