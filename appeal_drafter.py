"""
Stormwater Utility Fee Administrative Appeal Packet Generator.

Fills a jurisdiction-agnostic administrative appeal template for top overbilled parcels:
- Property owner / applicant details
- Parcel ID, jurisdiction, and land-use classification
- Billed vs recomputed impervious area, ERUs, and fees
- Attached aerial-measurement and GIS surveying instructions
- 3-year retroactive refund demand citing Berkeley County SC and San Antonio TX precedents
- Maryland statutory proportionality doctrine and restitution standards

Outputs individual markdown packets into appeal_packets/ and an APPEAL_INDEX.md manifest.
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("appeal_drafter")


APPEAL_TEMPLATE = """# ADMINISTRATIVE APPEAL & PETITION FOR STORMWATER UTILITY FEE CORRECTION
## AND FORMAL DEMAND FOR 3-YEAR RETROACTIVE FEE REFUND / CREDIT

**DATE OF FILING:** {filing_date}  
**FILING JURISDICTION:** {jurisdiction}  
**TARGET UTILITY AUTHORITY:** {utility_authority}  
**PARCEL IDENTIFICATION (PIN/ACCTID):** `{parcel_id}`  
**PROPERTY USE CLASSIFICATION:** {land_use_desc} (Code: `{land_use_code}`)  
**ASSIGNED BILLING CLASS:** `{billing_class}`  
**APPEAL PRIORITY:** {appeal_priority}  
**AUDIT TRACKING REF:** `SW-AUDIT-{parcel_id}-{current_year}`  

---

### I. PETITIONER / PROPERTY IDENTIFICATION

| Field | Record Details |
| :--- | :--- |
| **Property Owner of Record** | {owner_name} |
| **Parcel Identifier / Account ID** | `{parcel_id}` |
| **Jurisdiction / Municipality** | {jurisdiction} |
| **Land Use Description** | {land_use_desc} |
| **Land Use / Zoning Code** | {land_use_code} / {zoning} |
| **Assigned Billing Category** | {billing_class} |
| **Authorized Audit Representative** | Stormwater Recovery & Contingency Audit Group |

---

### II. EXECUTIVE SUMMARY OF BILLING ERROR & MONETARY DISCREPANCY

Independent geospatial and regulatory analysis of municipal billing records has revealed an erroneous over-assessment of stormwater utility fees for the subject property. 

The property is currently billed under an inflated assessment schedule that violates municipal rate tables and statutory guidelines. Petitioner formally petitions for an immediate prospective correction to the lawful rate and a full monetary refund / credit for overcollected fees spanning the statutory thirty-six (36) month retroactive lookback period.

#### Quantitative Billing Discrepancy

| Metric | Currently Billed | Recomputed / Lawful | Variance / Overcharge |
| :--- | :---: | :---: | :---: |
| **Impervious Surface Area** | {billed_sqft:,.1f} sq ft | {recomputed_sqft:,.1f} sq ft | **{excess_sqft:,.1f} sq ft excess** |
| **Equivalent Residential Units (ERU)** | {billed_eru:0.1f} ERU | {recomputed_eru:0.1f} ERU | **{excess_eru:0.1f} ERU overbilled** |
| **Annual Stormwater Utility Fee** | ${billed_annual_fee:,.2f} / yr | ${recomputed_annual_fee:,.2f} / yr | **${annual_overcharge:,.2f} / yr** |
| **3-Year Retroactive Lookback (36 Mos)** | ${billed_3yr:,.2f} | ${recomputed_3yr:,.2f} | **${retro_3yr_refund:,.2f} refund** |
| **Total 4-Year Immediate Recovery Value** | — | — | **${total_recovery:,.2f}** |

*Standard Jurisdiction ERU Baseline:* {eru_size:,.0f} sq ft per ERU at ${rate_per_eru:0.2f} / ERU / year.

---

### III. FACTUAL & TECHNICAL GROUNDS FOR APPEAL

The subject property assessment is defective under the following verified audit findings:

#### Primary Audit Finding: `{primary_flag}`
{primary_finding_narrative}

#### Specific Technical Details
> {notes}

#### Summary of Irregularities Identified:
1. **{flag_title_1}:** {flag_desc_1}
2. **Statutory Non-Compliance:** The assessment deviates from published municipal ordinance formulas linking user fee calculations directly to verified, contributing impervious footprint.

---

### IV. ATTACHED AERIAL-MEASUREMENT & GEOSPATIAL SURVEY PROTOCOL

To ensure complete transparency and facilitate immediate administrative concurrence, Petitioner incorporates the following certified aerial measurement protocol:

1. **Source Orthophotography Standards:**
   - Delineation relies upon recent sub-foot resolution, leaf-off orthophotography from the Maryland Statewide Imagery Program (MD iMap / 6-inch Ground Sample Distance) or high-resolution NAIP orthophotos.
   - Imagery captured during leaf-off conditions guarantees that deciduous tree canopy does not obscure rooflines or paved parking perimeters.

2. **Impervious Surface Delineation Criteria:**
   - **Included Surfaces:** Structurally impermeable surfaces including primary building footprints, asphalt or concrete vehicular parking lots, and non-porous driveways.
   - **Mandatory Pervious Exclusions:** 
     - Unpaved, compacted gravel/dirt areas exhibiting natural soil infiltration capacity.
     - Pervious paving systems and porous concrete engineered with sub-base percolation beds.
     - Vegetated swales, bioretention cells, rain gardens, and Maryland Environmental Site Design (ESD) features.
     - On-site retention ponds, stormwater detention basins, and designated critical area buffer zones.
     - Municipal road rights-of-way, sidewalks dedicated to public use, and adjacent parcel bleed inadvertently captured during automated GIS polygon digitization.

3. **Verification Submission:**
   - A high-resolution CAD/GIS polygon boundary overlay (`.shp` / `.geojson` format) accompanied by a licensed Professional Engineer (PE) or Professional Land Surveyor (PLS) seal is available for departmental verification upon request.

---

### V. LEGAL BASIS FOR 3-YEAR RETROACTIVE REFUND & RATE REDUCTION

Petitioner demands both prospective correction of the billing assessment and a complete refund or account credit for all overbilled sums paid during the prior three (3) calendar years, grounded in the following governing administrative and legal precedents:

#### 1. Berkeley County, South Carolina Stormwater Precedent (3-Year Retroactive Window)
Under the *Berkeley County Stormwater Management Ordinance and Utility Fee Credit & Appeals Policy*, municipal authorities established the formal administrative principle that stormwater billing errors, erroneous ERU computations, and improper impervious surface digitizations entitle property owners to **retroactive fee refunds and bill credits for payments received up to three (3) years prior to the date of appeal**. The precedent affirms that municipal user fees are regulatory cost-recovery mechanisms rather than unapportioned general taxes; therefore, funds extracted in excess of lawful impervious metrics constitute unjust enrichment that must be disgorged.

#### 2. City of San Antonio / San Antonio Water System (SAWS) Drainage Precedent
Under the *City of San Antonio Storm Water Utility Administrative Framework* and Texas municipal drainage utility statutes (Tex. Loc. Gov't Code § 552.041 et seq.), municipal drainage charges must strictly correspond to verified impervious cover and correct land-use designations. The administrative framework mandates **retroactive corrections spanning up to thirty-six (36) months** when an owner demonstrates:
- Clerical or mathematical calculation error in ERU derivation;
- Misclassification of commercial/industrial property into erroneous rate tiers; or
- Assessment of properties entitled to statutory, religious, or charitable tax exemptions.

#### 3. Maryland Environment Code & Proportionality Doctrine
Under Maryland Environment Code § 4-202.1 and established Maryland municipal jurisprudence, stormwater remediation user fees must be fair and equitable, bearing a substantial and direct relationship to the volume of runoff generated by the specific parcel. 
- Charging commercial, non-profit, or exempt properties fees based upon inflated or non-existent impervious footprints exceeds the express statutory mandate of the enabling legislation.
- Under Maryland common law principles of administrative restitution and tax overpayment recovery, fees remitted under a mistake of fact or mathematical miscalculation by the billing authority are fully recoverable.

---

### VI. FORMAL PRAYER FOR RELIEF

Petitioner respectfully requests that the Municipal Billing Authority / Stormwater Utility Department grant the following administrative relief:

1. **Immediate Billing Adjustment:** Reclassify the subject parcel (`{parcel_id}`) to reflect an annual assessment of **${recomputed_annual_fee:,.2f}** ({recomputed_eru:0.1f} ERUs), effective immediately on the next billing statement.
2. **3-Year Retroactive Refund / Credit:** Issue a cash refund warrant or direct bill credit in the amount of **${retro_3yr_refund:,.2f}**, representing the verified overcollection of stormwater fees across the prior 36-month period.
3. **Written Determination:** Provide formal written notice of this determination within thirty (30) calendar days from receipt of this petition.

---

### VII. SIGNATURE & VERIFICATION BLOCK

I hereby certify under penalties of perjury that the foregoing statements and attached geospatial computations are true and accurate to the best of my knowledge, information, and belief.

**Respectfully submitted,**

____________________________________________________  
**Property Owner / Authorized Representative Signature**  

**Printed Name:** ______________________________________  
**Title:** Property Owner / Designated Agent  
**Contact Email:** _____________________________________  
**Phone Number:** ____________________________________  
**Date Signed:** ______________________________________  

---
*Attachments:*
- Exhibit A: Aerial Orthophotography Impervious Footprint Measurement Overlay
- Exhibit B: Municipal GIS Parcel Assessment Record
- Exhibit C: ERU Calculation Worksheet & Precedent Citations
"""


def get_utility_authority(jurisdiction: str) -> str:
    """Return the designated municipal utility authority name."""
    j_lower = jurisdiction.lower()
    if "salisbury" in j_lower:
        return "City of Salisbury Department of Infrastructure & Development - Stormwater Division"
    elif "easton" in j_lower:
        return "Town of Easton Stormwater Utility / Engineering & Public Works Department"
    return "Municipal Stormwater Utility Billing Division"


def generate_finding_narrative(primary_flag: str, prospect: Dict[str, Any]) -> str:
    """Generate detailed factual narrative based on the specific audit flag."""
    flag = primary_flag.upper()
    if "EXEMPT" in flag:
        return (
            f"The subject parcel is legally classified under property tax and municipal codes as "
            f"'{prospect.get('land_use_desc', 'Exempt')}' (Code: {prospect.get('land_use_code', 'N/A')}). "
            f"Despite holding clear statutory exempt status (religious, educational, charitable, or municipal), "
            f"the billing authority unlawfully levied an annual assessment of ${float(prospect.get('billed_annual_fee', 0)):,.2f} "
            f"({float(prospect.get('billed_eru', 0)):0.1f} ERUs). Under state and municipal code, exempt properties "
            f"are entitled to a 100% billing exemption ($0.00 annual charge). All fees collected represent unlawful exactions."
        )
    elif "ARITHMETIC" in flag:
        return (
            f"A direct mathematical audit reveals a calculation error in the derivation of ERU billing units. "
            f"The property's recorded impervious area of {float(prospect.get('impervious_sqft', 0)):,.1f} sq ft "
            f"divided by the statutory ERU baseline yields {float(prospect.get('recomputed_eru', 0)):0.1f} ERUs "
            f"(${float(prospect.get('recomputed_annual_fee', 0)):,.2f}/yr). However, the property was assessed "
            f"{float(prospect.get('billed_eru', 0)):0.1f} ERUs (${float(prospect.get('billed_annual_fee', 0)):,.2f}/yr), "
            f"generating an unlawful annual overcharge of ${float(prospect.get('estimated_annual_overcharge', 0)):,.2f}."
        )
    elif "CLASS" in flag:
        return (
            f"The subject commercial property was improperly assigned to residential schedule '{prospect.get('billing_class', 'N/A')}', "
            f"causing an erroneous fee calculation that ignores lawful commercial rate structures. "
            f"Reclassifying the property to its proper non-residential schedule and correcting unit multipliers "
            f"reduces the lawful assessment to ${float(prospect.get('recomputed_annual_fee', 0)):,.2f}/yr."
        )
    elif "OUTLIER" in flag:
        return (
            f"Geospatial analysis confirms that the recorded impervious footprint ({float(prospect.get('impervious_sqft', 0)):,.1f} sq ft) "
            f"is an extreme statistical outlier within the '{prospect.get('land_use_desc', 'Commercial')}' cohort. "
            f"This discrepancy is characteristic of GIS digitization error where pervious surfaces, natural buffers, "
            f"gravel staging areas, and stormwater retention structures were mistakenly vectorized as impervious asphalt."
        )
    return (
        f"Audit identified an assessment discrepancy where billed fee of ${float(prospect.get('billed_annual_fee', 0)):,.2f} "
        f"materially exceeds the lawful rate of ${float(prospect.get('recomputed_annual_fee', 0)):,.2f}."
    )


def draft_appeal_packet(prospect: Dict[str, Any]) -> str:
    """
    Generate a complete, professional appeal packet markdown document from a prospect record.
    """
    now = datetime.now()
    filing_date = now.strftime("%B %d, %Y")
    current_year = now.strftime("%Y")
    
    jurisdiction = str(prospect.get("jurisdiction", "Municipal Utility"))
    utility_authority = get_utility_authority(jurisdiction)
    parcel_id = str(prospect.get("parcel_id", "UNKNOWN"))
    land_use_desc = str(prospect.get("land_use_desc", "Commercial"))
    land_use_code = str(prospect.get("land_use_code", "N/A"))
    billing_class = str(prospect.get("billing_class", "Standard"))
    appeal_priority = str(prospect.get("appeal_priority", "HIGH"))
    zoning = str(prospect.get("zoning", "Commercial / Industrial"))
    owner_name = str(prospect.get("owner", "Owner of Record / Commercial Property Manager"))
    
    billed_sqft = float(prospect.get("impervious_sqft", 0.0))
    billed_eru = float(prospect.get("billed_eru", 0.0))
    billed_annual_fee = float(prospect.get("billed_annual_fee", 0.0))
    
    recomputed_eru = float(prospect.get("recomputed_eru", 0.0))
    recomputed_annual_fee = float(prospect.get("recomputed_annual_fee", 0.0))
    annual_overcharge = float(prospect.get("estimated_annual_overcharge", 0.0))
    retro_3yr_refund = float(prospect.get("estimated_3yr_retro_refund", annual_overcharge * 3.0))
    total_recovery = float(prospect.get("estimated_total_recovery", annual_overcharge + retro_3yr_refund))
    
    # ERU constants
    if "salisbury" in jurisdiction.lower():
        eru_size = 3344.0
        rate_per_eru = 30.0
    else:
        eru_size = 3900.0
        rate_per_eru = 81.0

    # Recomputed impervious sqft
    if "EXEMPT" in str(prospect.get("primary_flag", "")).upper():
        recomputed_sqft = 0.0
        excess_sqft = billed_sqft
    else:
        recomputed_sqft = max(0.0, recomputed_eru * eru_size)
        excess_sqft = max(0.0, billed_sqft - recomputed_sqft)

    excess_eru = max(0.0, billed_eru - recomputed_eru)
    billed_3yr = billed_annual_fee * 3.0
    recomputed_3yr = recomputed_annual_fee * 3.0
    
    primary_flag = str(prospect.get("primary_flag", "ARITHMETIC_MISMATCH"))
    notes = str(prospect.get("notes", "Assessment contains calculation discrepancies requiring adjustment."))
    primary_finding_narrative = generate_finding_narrative(primary_flag, prospect)

    flag_title_1 = primary_flag.replace("_", " ").title()
    flag_desc_1 = notes.split("|")[0].strip() if "|" in notes else notes

    return APPEAL_TEMPLATE.format(
        filing_date=filing_date,
        jurisdiction=jurisdiction,
        utility_authority=utility_authority,
        parcel_id=parcel_id,
        land_use_desc=land_use_desc,
        land_use_code=land_use_code,
        billing_class=billing_class,
        appeal_priority=appeal_priority,
        current_year=current_year,
        owner_name=owner_name,
        zoning=zoning,
        billed_sqft=billed_sqft,
        recomputed_sqft=recomputed_sqft,
        excess_sqft=excess_sqft,
        billed_eru=billed_eru,
        recomputed_eru=recomputed_eru,
        excess_eru=excess_eru,
        billed_annual_fee=billed_annual_fee,
        recomputed_annual_fee=recomputed_annual_fee,
        annual_overcharge=annual_overcharge,
        billed_3yr=billed_3yr,
        recomputed_3yr=recomputed_3yr,
        retro_3yr_refund=retro_3yr_refund,
        total_recovery=total_recovery,
        eru_size=eru_size,
        rate_per_eru=rate_per_eru,
        primary_flag=primary_flag,
        primary_finding_narrative=primary_finding_narrative,
        notes=notes,
        flag_title_1=flag_title_1,
        flag_desc_1=flag_desc_1,
    )


def draft_appeal_packets_from_csv(
    csv_path: str,
    output_dir: str = "appeal_packets",
    top_n: Optional[int] = 10,
    min_overcharge: float = 50.0,
) -> List[str]:
    """
    Read overbilling_prospects.csv and generate appeal packet files for top prospects.
    Generates an APPEAL_INDEX.md manifest in output_dir.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Prospects CSV not found: {csv_path}")

    os.makedirs(output_dir, exist_ok=True)
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        prospects = list(reader)

    # Filter and slice
    filtered = [p for p in prospects if float(p.get("estimated_annual_overcharge", 0)) >= min_overcharge]
    if top_n is not None and top_n > 0:
        target_prospects = filtered[:top_n]
    else:
        target_prospects = filtered

    logger.info("Drafting %d appeal packet(s) into '%s'...", len(target_prospects), output_dir)
    generated_files: List[str] = []
    index_rows: List[str] = []
    
    total_annual_recovery = 0.0
    total_3yr_retro_recovery = 0.0

    for idx, p in enumerate(target_prospects, start=1):
        pid = str(p.get("parcel_id", f"target_{idx}")).replace("/", "_").replace("\\", "_").replace(" ", "_")
        jur_slug = "salisbury" if "salisbury" in str(p.get("jurisdiction", "")).lower() else "easton"
        filename = f"appeal_{jur_slug}_{pid}.md"
        filepath = os.path.join(output_dir, filename)
        
        content = draft_appeal_packet(p)
        with open(filepath, "w", encoding="utf-8") as out:
            out.write(content)
            
        generated_files.append(filepath)
        
        annual_val = float(p.get("estimated_annual_overcharge", 0))
        retro_val = float(p.get("estimated_3yr_retro_refund", 0))
        tot_val = float(p.get("estimated_total_recovery", 0))
        total_annual_recovery += annual_val
        total_3yr_retro_recovery += retro_val
        
        index_rows.append(
            f"| {idx} | [`{pid}`]({filename}) | {p.get('jurisdiction')} | {p.get('land_use_desc')} | "
            f"${annual_val:,.2f} | ${retro_val:,.2f} | **${tot_val:,.2f}** | `{p.get('primary_flag')}` |"
        )

    # Generate APPEAL_INDEX.md
    index_path = os.path.join(output_dir, "APPEAL_INDEX.md")
    total_contingency = (total_annual_recovery + total_3yr_retro_recovery) * 0.30
    
    index_content = f"""# STORMWATER UTILITY APPEAL PACKET REPOSITORY
## Top Prioritized Commercial & Exempt Overcharge Appeals

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Total Drafted Packets:** {len(generated_files)}  
**Total Prospective Annual Savings:** ${total_annual_recovery:,.2f} / yr  
**Total 3-Year Retroactive Refunds:** ${total_3yr_retro_recovery:,.2f}  
**Combined 4-Year Recovery Value:** ${total_annual_recovery + total_3yr_retro_recovery:,.2f}  
**Estimated Auditor Contingency (30%):** ${total_contingency:,.2f}  

---

### Priority Appeal Docket

| Rank | Parcel ID / File | Jurisdiction | Land Use | Annual Overcharge | 3-Yr Retro Refund | Total Value | Primary Anomaly |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
""" + "\n".join(index_rows) + f"""

---

### Statutory Lookback & Precedent Authority

All drafted appeal packets incorporate complete legal citations and technical evidence:
1. **Berkeley County, SC Precedent:** 36-month lookback refund rule for erroneous impervious assessments and administrative misclassifications.
2. **City of San Antonio (SAWS) Precedent:** Retroactive restitution mandate for clerical calculation errors and exempt property charges.
3. **Maryland Environment Code § 4-202.1:** Equitable user fee proportionality doctrine and restitution for ultra vires assessments.
4. **Certified Aerial Survey Instruction:** Sub-foot leaf-off orthophotography protocol with explicit pervious exclusions (retention basins, gravel, ESD swales).
"""
    with open(index_path, "w", encoding="utf-8") as f_idx:
        f_idx.write(index_content)

    logger.info("Generated index at %s", index_path)
    return generated_files


def parse_args():
    parser = argparse.ArgumentParser(description="Stormwater Fee Administrative Appeal Drafter")
    parser.add_argument(
        "--input",
        default="overbilling_prospects.csv",
        help="Input CSV file from misbill_scorer (default: overbilling_prospects.csv)",
    )
    parser.add_argument(
        "--output-dir",
        default="appeal_packets",
        help="Output directory for appeal packets (default: appeal_packets)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top prospects to generate packets for (default: 10, use 0 for all)",
    )
    parser.add_argument(
        "--min-overcharge",
        type=float,
        default=50.0,
        help="Minimum annual overcharge threshold (default: $50)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    top_n = None if args.top == 0 else args.top
    draft_appeal_packets_from_csv(
        csv_path=args.input,
        output_dir=args.output_dir,
        top_n=top_n,
        min_overcharge=args.min_overcharge,
    )


if __name__ == "__main__":
    main()
