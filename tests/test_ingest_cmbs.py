"""EX-102 parsing: SEC schema quirks, coverage, portfolio assembly."""

import io

import pytest

from cmbs_radar.ingest.cmbs import Coverage, ParseError, parse, parse_filing
from conftest import ex102


def test_parse_fixture():
    cov = Coverage()
    loans = list(parse(io.BytesIO(ex102()), cov))
    assert len(loans) == 2
    l = loans[0]
    assert (l.asset_number, l.static["originator"], l.obs["primary_servicer"]) == ("1", "Example Bank", "Example Servicing LLC")
    assert l.static["maturity_date"].isoformat() == "2027-01-06" == l.obs["maturity_date"].isoformat()
    assert l.obs["current_balance"] == 75_000_000
    assert l.static["interest_only"] is True and l.obs["modified"] is False
    assert l.static["original_term_months"] == 120
    assert l.obs["workout_strategy"] == "" and l.obs["special_servicer_transfer_date"] is None
    assert l.static["ard_date"] and l.static["yield_maintenance_end"] and l.obs["paid_through_date"]

    p = l.properties[0]
    assert (p.static["city"], p.static["property_type"], p.obs["dscr"], p.obs["occupancy"]) == ("New York", "OF", 1.30, 0.71)
    # SEC quirks: capital-D DefeasedStatusCode at property level, lowercase-p
    # "...NetCashFlowpercentage", doubled "netCashFlowFlow...".
    assert (p.obs["defeased_status"], p.obs["dscr_ncf"], p.static["ncf_at_securitization"]) == ("N", 1.21, 7_900_000)
    assert p.obs["financials_end_date"].isoformat() == "2026-03-31" and p.obs["debt_service"] is not None
    assert p.obs["tenant1_name"] == "Example Law LLP" and p.obs["tenant1_lease_exp"] is None  # "not a date"
    assert p.obs["tenant2_name"] == "Example Capital LP" and p.obs["tenant2_lease_exp"].isoformat() == "2027-06-30"

    ps = loans[1].properties
    assert len(ps) == 2 and ps[1].seq == 2 and ps[1].static["name"] == "Warehouse B"

    assert "asset.someFutureField" in cov.present_but_unmapped()
    assert "asset.assetTypeNumber" not in cov.present_but_unmapped() and "asset.GroupID" not in cov.present_but_unmapped()
    assert cov.presence("asset.assetNumber") == 1 and cov.presence("asset.originatorName") == 0.5
    assert cov.presence("property.propertyName") == 1
    assert "asset.workoutStrategyCode" in cov.mapped_but_missing()
    assert "property.leaseExpirationLargestTenantDate" in cov.report()


def test_requires_asset_number():
    with pytest.raises(ParseError):
        list(parse(io.BytesIO(b"<assetData><assets><maturityDate>01-01-2030</maturityDate></assets></assetData>")))


PORTFOLIO = b"""<assetData xmlns="http://www.sec.gov/edgar/document/absee/cmbs/assetdata">
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>1</assetNumber>
  <originationDate>05-06-2016</originationDate><reportPeriodEndActualBalanceAmount>150000000</reportPeriodEndActualBalanceAmount>
  <liquidationPrepaymentCode>2</liquidationPrepaymentCode><liquidationPrepaymentDate>07-11-2026</liquidationPrepaymentDate>
  <modificationCode>4</modificationCode><postModificationMaturityDate>06-01-2028</postModificationMaturityDate>
  <postModificationInterestPercentage>0.0525</postModificationInterestPercentage>
  <property><propertyName>Storage Portfolio</propertyName><mostRecentNetOperatingIncomeAmount>13990707</mostRecentNetOperatingIncomeAmount>
    <mostRecentValuationAmount>180000000</mostRecentValuationAmount><mostRecentValuationDate>03-01-2026</mostRecentValuationDate></property>
</assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>1.01</assetNumber>
  <reportingPeriodEndDate>07-31-2026</reportingPeriodEndDate>
  <property><propertyName>Storage A</propertyName><propertyState>NV</propertyState></property></assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>3</assetNumber>
  <originationDate>01-06-2017</originationDate>
  <property><propertyName>Shadow Anchored Portfolio</propertyName></property></assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>1.02</assetNumber><assetAddedIndicator>false</assetAddedIndicator>
  <property><propertyName>Storage B</propertyName><propertyState>AZ</propertyState></property></assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>3-012</assetNumber>
  <property><propertyName>Shawnee Shopping Center</propertyName></property></assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>9.01</assetNumber>
  <property><propertyName>Parent Not In File</propertyName></property></assets>
<assets><assetTypeNumber>Prospectus Loan ID</assetTypeNumber><assetNumber>10.5</assetNumber>
  <originationDate>01-06-2017</originationDate></assets>
</assetData>"""


def test_parse_filing_assembles_portfolios():
    """Members ("1.01", "3-001") fold into the parent in any order; the
    parent's own block becomes the rollup; "10.5" with loan data is a loan."""
    cov = Coverage()
    loans, orphans = parse_filing(io.BytesIO(PORTFOLIO), cov)
    assert [l.asset_number for l in loans] == ["1", "3", "10.5", "9.01"] and orphans == ["9.01"]
    ps = loans[0].properties
    assert len(ps) == 3
    assert ps[0].rollup and ps[0].seq == 0 and ps[0].static["name"] == "Storage Portfolio" and ps[0].obs["noi"] == 13990707
    assert not ps[1].rollup and ps[1].seq == 1 and ps[1].static["state"] == "NV" and ps[1].source_asset == "1.01"
    assert ps[2].seq == 2 and ps[2].static["state"] == "AZ"
    p3 = loans[1].properties
    assert len(p3) == 2 and p3[0].rollup and p3[1].seq == 12 and p3[1].source_asset == "3-012"
    assert loans[2].properties == []
    o = loans[0].obs
    assert (o["liquidation_code"], o["modification_code"], o["post_mod_rate"]) == ("2", "4", 0.0525)
    assert o["liquidation_date"] and o["post_mod_maturity_date"].isoformat() == "2028-06-01"
    assert ps[0].obs["valuation_amount"] == 180e6 and ps[0].obs["valuation_date"]
    assert cov.presence("asset.originationDate") == 1  # member blocks don't dilute loan fill rates
    assert cov.presence("property.propertyName") == 1
