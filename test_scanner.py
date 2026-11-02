"""
Unit tests for Stormwater Fee Overcharge Scanner.
Ensures 100% offline testing with mock fixtures (no network calls).
"""

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from fetcher import (
    CONFIG_EASTON,
    CONFIG_SALISBURY,
    discover_layers,
    fetch_feature_layer,
    get_layer_metadata,
    get_service_metadata,
    normalize_url,
    resolve_layer_id,
)
from misbill_scorer import (
    NormalizedParcel,
    calculate_cohort_statistics,
    check_arithmetic_mismatch,
    check_exempt_billed,
    check_impervious_outlier,
    check_wrong_class,
    export_prospects_csv,
    normalize_parcel_record,
    score_parcel,
    score_parcels,
)
from appeal_drafter import draft_appeal_packet, draft_appeal_packets_from_csv


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(filename: str):
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 1. Fetcher Tests (Offline / Mocked)
# =============================================================================

class TestFetcher:
    def test_normalize_url(self):
        """Verify URL normalization enforces uppercase 'ArcGIS/rest' and trims slashes."""
        test_cases = [
            ("https://example.com/arcgis/rest/services/Layer/FeatureServer", "https://example.com/ArcGIS/rest/services/Layer/FeatureServer"),
            ("https://example.com/ARCGIS/REST/services/Layer/FeatureServer/", "https://example.com/ArcGIS/rest/services/Layer/FeatureServer"),
            ("https://example.com/ArcGIS/rest/services/Layer/FeatureServer", "https://example.com/ArcGIS/rest/services/Layer/FeatureServer"),
            ("  https://example.com/arcgis/rest/services/Test/FeatureServer/  ", "https://example.com/ArcGIS/rest/services/Test/FeatureServer"),
        ]
        for inp, expected in test_cases:
            assert normalize_url(inp) == expected

    @patch("fetcher.requests.Session")
    def test_discover_layers(self, mock_session_cls):
        """Verify discovery of layers from FeatureServer?f=json."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = load_fixture("salisbury_service_metadata.json")
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp

        layers = discover_layers("https://services6.arcgis.com/Hx8jJ6McXQ0jnqLk/ArcGIS/rest/services/Parcels_with_ERU1/FeatureServer", session=mock_session)
        assert len(layers) == 1
        assert layers[0]["id"] == 38
        assert layers[0]["name"] == "Parcels with ERU"

    @patch("fetcher.requests.Session")
    def test_resolve_layer_id_non_zero(self, mock_session_cls):
        """Test layer ID resolution when layer IDs are NOT zero (e.g., 38 for Salisbury, 1 for Easton)."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = load_fixture("salisbury_service_metadata.json")
        mock_session.get.return_value = mock_resp

        url = "https://services6.arcgis.com/Hx8jJ6McXQ0jnqLk/ArcGIS/rest/services/Parcels_with_ERU1/FeatureServer"
        
        # Test explicit layer id matching
        resolved_id = resolve_layer_id(url, preferred_layer_id=38, session=mock_session)
        assert resolved_id == 38

        # Test name hint matching
        resolved_hint = resolve_layer_id(url, name_hint="Parcels with ERU", session=mock_session)
        assert resolved_hint == 38

        # Test Easton layer resolution (layer ID 1)
        mock_resp_easton = MagicMock()
        mock_resp_easton.json.return_value = load_fixture("easton_service_metadata.json")
        mock_session.get.return_value = mock_resp_easton
        url_easton = "https://services2.arcgis.com/G6TP4SnXQoFs2r0T/ArcGIS/rest/services/EastonStormwaterUtilityParcels/FeatureServer"
        resolved_easton = resolve_layer_id(url_easton, preferred_layer_id=1, session=mock_session)
        assert resolved_easton == 1

    @patch("fetcher.requests.Session")
    def test_fetch_feature_layer_pagination(self, mock_session_cls):
        """Test multi-page pagination using mock fixture responses without network calls."""
        mock_session = MagicMock()
        
        meta_service = load_fixture("salisbury_service_metadata.json")
        meta_layer = load_fixture("salisbury_layer_metadata.json")
        page1 = load_fixture("salisbury_query_page1.json")
        page2 = load_fixture("salisbury_query_page2.json")

        def side_effect(url, **kwargs):
            m = MagicMock()
            m.raise_for_status.return_value = None
            if url.endswith("FeatureServer?f=json"):
                m.json.return_value = meta_service
            elif url.endswith("/38?f=json"):
                m.json.return_value = meta_layer
            elif "/38/query" in url:
                offset = kwargs.get("params", {}).get("resultOffset", 0)
                if offset == 0:
                    m.json.return_value = page1
                else:
                    m.json.return_value = page2
            return m

        mock_session.get.side_effect = side_effect

        features = fetch_feature_layer(
            service_url="https://services6.arcgis.com/Hx8jJ6McXQ0jnqLk/ArcGIS/rest/services/Parcels_with_ERU1/FeatureServer",
            layer_id=38,
            session=mock_session,
        )

        assert len(features) == 10  # 4 from page1 + 6 from page2
        assert features[0]["acctid"] == "SALIS-001"
        assert features[4]["acctid"] == "SALIS-005-OUTLIER"

    @patch("fetcher.requests.Session")
    def test_fetch_feature_layer_max_records_cap(self, mock_session_cls):
        """Verify fetcher respects max_records limit."""
        mock_session = MagicMock()
        meta_service = load_fixture("salisbury_service_metadata.json")
        meta_layer = load_fixture("salisbury_layer_metadata.json")
        page1 = load_fixture("salisbury_query_page1.json")

        def side_effect(url, **kwargs):
            m = MagicMock()
            m.raise_for_status.return_value = None
            if url.endswith("FeatureServer?f=json"):
                m.json.return_value = meta_service
            elif url.endswith("/38?f=json"):
                m.json.return_value = meta_layer
            elif "/38/query" in url:
                m.json.return_value = page1
            return m

        mock_session.get.side_effect = side_effect

        features = fetch_feature_layer(
            service_url="https://services6.arcgis.com/Hx8jJ6McXQ0jnqLk/ArcGIS/rest/services/Parcels_with_ERU1/FeatureServer",
            layer_id=38,
            max_records=2,
            session=mock_session,
        )
        assert len(features) == 2


# =============================================================================
# 2. Misbilling Scorer Tests
# =============================================================================

class TestMisbillScorer:
    def test_normalize_parcel_salisbury(self):
        """Verify normalization of Salisbury schema attributes."""
        raw = {
            "acctid": "2305001234",
            "zoning": "GC",
            "lu": "C",
            "desclu": "Commercial",
            "is_sqft": 10032.0,
            "eru": 3344,
            "indiv_eru": 3.0,
            "eru_rnd": 3,
            "indiv_fee": 30.0,
            "annualrev": 90.0,
            "billablekey": "Greater than 1 ERU, NSF Residential",
        }
        p = normalize_parcel_record(raw)
        assert p.parcel_id == "2305001234"
        assert p.jurisdiction == "Salisbury, MD"
        assert p.impervious_sqft == 10032.0
        assert p.billed_eru == 3.0
        assert p.billed_annual_fee == 90.0
        assert p.eru_size_sqft == 3344.0

    def test_normalize_parcel_easton(self):
        """Verify normalization of Easton schema attributes."""
        raw = {
            "PARCELID": "10R-6",
            "BILLNO": "26022",
            "IMPAREA": 311061.0,
            "NUM_ERUS": 80,
            "USECD": "4010",
            "USEDSCRP": "ND WHSES MDL-96",
            "CALCMETHOD": "Calculated",
            "BLDGVAL": 18521400.0,
        }
        p = normalize_parcel_record(raw)
        assert p.parcel_id == "10R-6"
        assert p.jurisdiction == "Easton, MD"
        assert p.impervious_sqft == 311061.0
        assert p.billed_eru == 80.0
        assert p.billed_annual_fee == 80.0 * 81.0
        assert p.eru_size_sqft == 3900.0

    def test_flag_exempt_property_billed(self):
        """Flag 4: Property with fee > 0 but classified as Exempt."""
        p = NormalizedParcel(
            parcel_id="EXEMPT-01",
            jurisdiction="Salisbury, MD",
            land_use_code="EC",
            land_use_desc="Exempt Commercial",
            billing_class="Greater than 1 ERU, NSF Residential",
            impervious_sqft=800000.0,
            billed_eru=240.0,
            billed_annual_fee=7200.0,
            eru_size_sqft=3344.0,
            rate_per_eru=30.0,
        )
        flag = check_exempt_billed(p)
        assert flag is not None
        assert flag.flag_type == "EXEMPT_PROPERTY_BILLED"
        assert flag.estimated_annual_overcharge == 7200.0
        assert flag.recomputed_annual_fee == 0.0

    def test_flag_arithmetic_mismatch(self):
        """Flag 1: Arithmetic mismatch between impervious area / ERU size and billed fee."""
        # 6,688 sq ft / 3,344 = 2 ERUs ($60 lawful), but billed 6 ERUs ($180)
        p = NormalizedParcel(
            parcel_id="ARITH-01",
            jurisdiction="Salisbury, MD",
            land_use_code="C",
            land_use_desc="Commercial",
            billing_class="Greater than 1 ERU, NSF Residential",
            impervious_sqft=6688.0,
            billed_eru=6.0,
            billed_annual_fee=180.0,
            eru_size_sqft=3344.0,
            rate_per_eru=30.0,
        )
        flag = check_arithmetic_mismatch(p)
        assert flag is not None
        assert flag.flag_type == "ARITHMETIC_MISMATCH"
        assert flag.recomputed_eru == 2.0
        assert flag.recomputed_annual_fee == 60.0
        assert flag.estimated_annual_overcharge == 120.0

    def test_flag_zero_sqft_billed(self):
        """Flag 1 Edge-Case: 0 sq ft impervious surface billed positive ERU."""
        p = NormalizedParcel(
            parcel_id="ZERO-IMP",
            jurisdiction="Salisbury, MD",
            land_use_code="C",
            land_use_desc="Commercial",
            billing_class="1 ERU, NSF Residential",
            impervious_sqft=0.0,
            billed_eru=1.0,
            billed_annual_fee=30.0,
            eru_size_sqft=3344.0,
            rate_per_eru=30.0,
        )
        flag = check_arithmetic_mismatch(p)
        assert flag is not None
        assert flag.estimated_annual_overcharge == 30.0
        assert flag.recomputed_annual_fee == 0.0

    def test_flag_wrong_class(self):
        """Flag 2: Commercial parcel billed under incorrect residential class."""
        p = NormalizedParcel(
            parcel_id="CLASS-01",
            jurisdiction="Salisbury, MD",
            land_use_code="C",
            land_use_desc="Commercial Warehouse",
            billing_class="Single Family",
            impervious_sqft=25000.0,
            billed_eru=10.0,
            billed_annual_fee=300.0,
            eru_size_sqft=3344.0,
            rate_per_eru=30.0,
        )
        flag = check_wrong_class(p)
        assert flag is not None
        assert flag.flag_type == "WRONG_CLASS_MISBILL"

    def test_flag_impervious_outlier(self):
        """Flag 3: Extreme outlier impervious area for land-use class."""
        cohort_parcels = [
            NormalizedParcel(f"C-{i}", "Salisbury, MD", "C", "Commercial", "NSF", sqft, 5, 150, 3344, 30)
            for i, sqft in enumerate([15000, 16000, 17000, 18000, 19000, 20000])
        ]
        stats = calculate_cohort_statistics(cohort_parcels)

        # Huge outlier property: 350,000 sq ft
        outlier_parcel = NormalizedParcel(
            parcel_id="OUTLIER-01",
            jurisdiction="Salisbury, MD",
            land_use_code="C",
            land_use_desc="Commercial",
            billing_class="NSF",
            impervious_sqft=350000.0,
            billed_eru=105.0,
            billed_annual_fee=3150.0,
            eru_size_sqft=3344.0,
            rate_per_eru=30.0,
        )
        flag = check_impervious_outlier(outlier_parcel, stats)
        assert flag is not None
        assert flag.flag_type == "OUTLIER_IMPERVIOUS"
        assert flag.estimated_annual_overcharge > 0

    def test_end_to_end_scoring_and_ranking(self):
        """Verify full scoring pipeline ranks prospects and computes 3-year retroactive refunds."""
        p1 = load_fixture("salisbury_query_page1.json")["features"]
        p2 = load_fixture("salisbury_query_page2.json")["features"]
        raw = p1 + p2

        prospects = score_parcels(raw)
        assert len(prospects) == 4
        # Verify rank 1 is highest overcharge
        assert prospects[0].rank == 1
        assert prospects[0].parcel_id == "SALIS-003-EXEMPT"
        assert prospects[0].estimated_annual_overcharge == 7200.0
        assert prospects[0].estimated_3yr_retro_refund == 21600.0
        assert prospects[0].estimated_total_recovery == 28800.0
        assert prospects[0].contingency_fee_potential == 8640.0

        # Export CSV verification
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            export_prospects_csv(prospects, tmp_path)
            assert os.path.exists(tmp_path)
            with open(tmp_path, "r", encoding="utf-8") as f:
                header = f.readline().strip()
                assert "parcel_id" in header
                assert "estimated_annual_overcharge" in header
                assert "estimated_3yr_retro_refund" in header
                assert "primary_flag" in header
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# =============================================================================
# 3. Appeal Drafter Tests
# =============================================================================

class TestAppealDrafter:
    def test_appeal_packet_template_contents(self):
        """Verify appeal template incorporates all required sections and precedent citations."""
        prospect_data = {
            "parcel_id": "2308020191",
            "jurisdiction": "Salisbury, MD",
            "land_use_desc": "Exempt Commercial",
            "land_use_code": "EC",
            "billing_class": "Greater than 1 ERU, NSF Residential",
            "impervious_sqft": 802958.3,
            "billed_eru": 240.0,
            "billed_annual_fee": 7200.0,
            "recomputed_eru": 0.0,
            "recomputed_annual_fee": 0.0,
            "estimated_annual_overcharge": 7200.0,
            "estimated_3yr_retro_refund": 21600.0,
            "estimated_total_recovery": 28800.0,
            "primary_flag": "EXEMPT_PROPERTY_BILLED",
            "appeal_priority": "CRITICAL",
            "notes": "Property classified as Exempt Commercial with fee > 0.",
        }

        packet_text = draft_appeal_packet(prospect_data)

        # Check critical required content:
        assert "ADMINISTRATIVE APPEAL" in packet_text
        assert "2308020191" in packet_text
        assert "Salisbury, MD" in packet_text
        assert "$7,200.00" in packet_text
        assert "$21,600.00" in packet_text
        assert "ATTACHED AERIAL-MEASUREMENT & GEOSPATIAL SURVEY PROTOCOL" in packet_text
        assert "Mandatory Pervious Exclusions" in packet_text
        
        # Verify statutory and legal precedents explicitly cited:
        assert "Berkeley County, South Carolina Stormwater Precedent" in packet_text
        assert "City of San Antonio / San Antonio Water System (SAWS) Drainage Precedent" in packet_text
        assert "Maryland Environment Code" in packet_text

    def test_draft_appeal_packets_from_csv(self):
        """Test batch drafting of appeal packets from CSV file."""
        temp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(temp_dir, "test_prospects.csv")

        # Create a test CSV
        p1 = load_fixture("salisbury_query_page1.json")["features"]
        prospects = score_parcels(p1)
        export_prospects_csv(prospects, csv_path)

        packets_dir = os.path.join(temp_dir, "appeal_packets")
        generated = draft_appeal_packets_from_csv(csv_path, output_dir=packets_dir, top_n=5, min_overcharge=10.0)

        assert len(generated) > 0
        for path in generated:
            assert os.path.exists(path)
            assert path.endswith(".md")

        # Check index file
        index_file = os.path.join(packets_dir, "APPEAL_INDEX.md")
        assert os.path.exists(index_file)
        with open(index_file, "r", encoding="utf-8") as f:
            idx_content = f.read()
            assert "Priority Appeal Docket" in idx_content
            assert "SALIS-003-EXEMPT" in idx_content

        shutil.rmtree(temp_dir)
