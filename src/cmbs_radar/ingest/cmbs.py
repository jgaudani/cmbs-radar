"""Parses SEC Form ABS-EE EX-102 asset data files for commercial mortgages
(Regulation AB II, Schedule AL Item 2).

Values are kept as reported; percentages are not rescaled (scoring
normalizes them). Fields are keyed by their database column, from one
declarative mapping, so the store and the parity check read them directly.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import IO, Any, Callable, Iterator

from lxml import etree

# (column, EX-102 element, type). SEC element names contain quirks that must
# be matched exactly; each has a test.
LOAN_STATIC = [
    ("originator", "originatorName", "str"), ("origination_date", "originationDate", "date"),
    ("original_amount", "originalLoanAmount", "num"),
    ("balance_at_securitization", "scheduledPrincipalBalanceSecuritizationAmount", "num"),
    ("original_term_months", "originalTermLoanNumber", "int"),
    ("original_amortization_months", "originalAmortizationTermNumber", "int"),
    ("original_io_term_months", "originalInterestOnlyTermNumber", "int"),
    ("original_rate", "originalInterestRatePercentage", "num"),
    ("rate_at_securitization", "interestRateSecuritizationPercentage", "num"),
    ("debt_service_at_securitization", "periodicPrincipalAndInterestPaymentSecuritizationAmount", "num"),
    ("interest_only", "interestOnlyIndicator", "bool"), ("balloon", "balloonIndicator", "bool"),
    ("payment_type", "paymentTypeCode", "str"), ("loan_structure", "loanStructureCode", "str"),
    ("lien_position", "lienPositionSecuritizationCode", "str"),
    ("properties_at_securitization", "NumberPropertiesSecuritization", "int"),
    # Refinance timing. For ARD loans the anticipated repayment date is the
    # effective refi date; lockout / yield maintenance define the window.
    ("maturity_date", "maturityDate", "date"), ("ard_date", "hyperAmortizingDate", "date"),
    ("prepayment_lockout_end", "prepaymentLockOutEndDate", "date"),
    ("yield_maintenance_end", "yieldMaintenanceEndDate", "date"),
    ("prepayment_premium_end", "prepaymentPremiumsEndDate", "date"),
]
LOAN_OBS = [
    ("maturity_date", "maturityDate", "date"),  # can move on modification: tracked per period
    ("current_balance", "reportPeriodEndActualBalanceAmount", "num"),
    ("scheduled_balance", "reportPeriodEndScheduledLoanBalanceAmount", "num"),
    ("current_rate", "reportPeriodInterestRatePercentage", "num"), ("paid_through_date", "paidThroughDate", "date"),
    ("payment_status", "paymentStatusLoanCode", "str"), ("modified", "modifiedIndicator", "bool"),
    ("modified_this_period", "reportPeriodModificationIndicator", "bool"),
    ("workout_strategy", "workoutStrategyCode", "str"),
    # Only reported for loans that were transferred.
    ("special_servicer_transfer_date", "mostRecentSpecialServicerTransferDate", "date"),
    ("non_recoverable", "nonRecoverabilityIndicator", "bool"),
    ("pi_advances_outstanding", "totalPrincipalInterestAdvancedOutstandingAmount", "num"),
    ("realized_loss", "realizedLossToTrustAmount", "num"), ("number_of_properties", "NumberProperties", "int"),
    ("primary_servicer", "primaryServicerName", "str"),
    # Outcomes, needed by the backtest.
    ("liquidation_code", "liquidationPrepaymentCode", "str"), ("liquidation_date", "liquidationPrepaymentDate", "date"),
    ("modification_code", "modificationCode", "str"), ("last_modification_date", "lastModificationDate", "date"),
    ("post_mod_maturity_date", "postModificationMaturityDate", "date"),
    ("post_mod_rate", "postModificationInterestPercentage", "num"),
    ("master_servicer_return_date", "mostRecentMasterServicerReturnDate", "date"),
]
PROP_STATIC = [
    ("name", "propertyName", "str"), ("address", "propertyAddress", "str"), ("city", "propertyCity", "str"),
    ("state", "propertyState", "str"), ("zip", "propertyZip", "str"), ("county", "propertyCounty", "str"),
    ("property_type", "propertyTypeCode", "str"), ("year_built", "yearBuiltNumber", "int"),
    ("year_renovated", "yearLastRenovated", "int"), ("net_rentable_sqft", "netRentableSquareFeetNumber", "num"),
    ("units", "unitsBedsRoomsNumber", "num"),
    ("sqft_at_securitization", "netRentableSquareFeetSecuritizationNumber", "num"),
    ("units_at_securitization", "unitsBedsRoomsSecuritizationNumber", "num"),
    ("valuation_at_securitization", "valuationSecuritizationAmount", "num"),
    ("valuation_date_at_securitization", "valuationSecuritizationDate", "date"),
    ("valuation_source_at_securitization", "valuationSourceSecuritizationCode", "str"),
    ("financials_date_at_securitization", "financialsSecuritizationDate", "date"),
    ("revenue_at_securitization", "revenueSecuritizationAmount", "num"),
    ("opex_at_securitization", "operatingExpensesSecuritizationAmount", "num"),
    ("noi_at_securitization", "netOperatingIncomeSecuritizationAmount", "num"),
    ("ncf_at_securitization", "netCashFlowFlowSecuritizationAmount", "num"),  # sic: "FlowFlow"
    ("dscr_at_securitization", "debtServiceCoverageNetOperatingIncomeSecuritizationPercentage", "num"),
    ("dscr_ncf_at_securitization", "debtServiceCoverageNetCashFlowSecuritizationPercentage", "num"),
    ("dscr_code_at_securitization", "debtServiceCoverageSecuritizationCode", "str"),
    ("noi_ncf_code_at_securitization", "netOperatingIncomeNetCashFlowSecuritizationCode", "str"),
    ("occupancy_at_securitization", "physicalOccupancySecuritizationPercentage", "num"),
    ("defeasance_option_start", "defeasanceOptionStartDate", "date"),
]
PROP_OBS = [
    ("status", "propertyStatusCode", "str"), ("defeased_status", "DefeasedStatusCode", "str"),  # sic: capital D
    ("valuation_amount", "mostRecentValuationAmount", "num"), ("valuation_date", "mostRecentValuationDate", "date"),
    ("valuation_source", "mostRecentValuationSourceCode", "str"),
    ("occupancy", "mostRecentPhysicalOccupancyPercentage", "num"),
    ("financials_start_date", "mostRecentFinancialsStartDate", "date"),
    ("financials_end_date", "mostRecentFinancialsEndDate", "date"), ("revenue", "mostRecentRevenueAmount", "num"),
    ("opex", "operatingExpensesAmount", "num"), ("noi", "mostRecentNetOperatingIncomeAmount", "num"),
    ("ncf", "mostRecentNetCashFlowAmount", "num"), ("debt_service", "mostRecentDebtServiceAmount", "num"),
    ("dscr", "mostRecentDebtServiceCoverageNetOperatingIncomePercentage", "num"),
    ("dscr_ncf", "mostRecentDebtServiceCoverageNetCashFlowpercentage", "num"),  # sic: lowercase "p"
    ("dscr_code", "mostRecentDebtServiceCoverageCode", "str"), ("noi_ncf_code", "netOperatingIncomeNetCashFlowCode", "str"),
    ("tenant1_name", "largestTenant", "str"), ("tenant1_sqft", "squareFeetLargestTenantNumber", "num"),
    ("tenant1_lease_exp", "leaseExpirationLargestTenantDate", "date"),
    ("tenant2_name", "secondLargestTenant", "str"), ("tenant2_sqft", "squareFeetSecondLargestTenantNumber", "num"),
    ("tenant2_lease_exp", "leaseExpirationSecondLargestTenantDate", "date"),
    ("tenant3_name", "thirdLargestTenant", "str"), ("tenant3_sqft", "squareFeetThirdLargestTenantNumber", "num"),
    ("tenant3_lease_exp", "leaseExpirationThirdLargestTenantDate", "date"),
]

# Present in EX-102 but deliberately not stored: servicing mechanics and
# per-period cash accounting that don't inform refinance analysis.
INTENTIONALLY_UNMAPPED = {
    "asset.assetTypeNumber", "asset.GroupID", "asset.assetAddedIndicator", "asset.assetSubjectDemandIndicator",
    "asset.firstLoanPaymentDueDate", "asset.graceDaysAllowedNumber", "asset.interestAccrualMethodCode",
    "asset.negativeAmortizationIndicator", "asset.originalInterestRateTypeCode",
    "asset.otherExpensesAdvancedOutstandingAmount", "asset.otherInterestAdjustmentAmount",
    "asset.otherPrincipalAdjustmentAmount", "asset.paymentFrequencyCode", "asset.prepaymentPremiumIndicator",
    "asset.reportPeriodBeginningScheduleLoanBalanceAmount", "asset.scheduledInterestAmount",
    "asset.scheduledPrincipalAmount", "asset.servicerTrusteeFeeRatePercentage", "asset.servicingAdvanceMethodCode",
    "asset.totalScheduledPrincipalInterestDueAmount", "asset.totalTaxesInsuranceAdvancesOutstandingAmount",
    "asset.underwritingIndicator", "asset.unscheduledPrincipalCollectedAmount", "asset.deferredInterestCollectedAmount",
    "asset.deferredInterestCumulativeAmount", "asset.nextInterestRatePercentage",
    "asset.postModificationAmortizationPeriodAmount", "asset.postModificationPaymentAmount",
    "asset.prepaymentPremiumYieldMaintenanceReceivedAmount", "asset.repurchaseAmount",
    "property.mostRecentAnnualLeaseRolloverReviewDate",
}

# The only leaf elements a portfolio member <assets> block carries besides
# its <property>.
_MEMBER_IDENTITY = {"assetTypeNumber", "assetNumber", "GroupID", "assetAddedIndicator",
                    "reportingPeriodBeginningDate", "reportingPeriodEndDate"}


@dataclass(slots=True)
class Property:
    """One <property> block. Portfolio loans come in two shapes: several
    <property> blocks under the loan (seq = order), or a rollup <property>
    on the loan and each collateral property as its own <assets> block
    numbered after the parent ("1.01", "3-001"). parse_filing folds those
    members into the parent: the rollup gets seq 0, members their suffix."""

    seq: int
    source_asset: str
    rollup: bool = False
    static: dict[str, Any] = field(default_factory=dict)  # properties columns
    obs: dict[str, Any] = field(default_factory=dict)  # property_observations columns


@dataclass(slots=True)
class Loan:
    asset_number: str
    period_begin: date | None = None
    period_end: date | None = None
    portfolio_member: bool = False
    static: dict[str, Any] = field(default_factory=dict)  # loans columns
    obs: dict[str, Any] = field(default_factory=dict)  # loan_observations columns
    properties: list[Property] = field(default_factory=list)


class ParseError(Exception):
    pass


# ---- coverage -----------------------------------------------------------------


class Coverage:
    """Compares the elements present in real EX-102 data with the elements
    the parser reads: mapped fields that never appear (wrong name?), fill
    rates, present-but-unmapped fields, values that failed to parse."""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self.loans = self.members = self.properties = 0
        self.present: dict[str, int] = {}
        self.used: set[str] = set()
        self.bad: dict[str, list[str]] = {}
        self.bad_count: dict[str, int] = {}

    def seen(self, scope: str, name: str) -> None:
        with self._mu:
            k = f"{scope}.{name}"
            self.present[k] = self.present.get(k, 0) + 1

    def use(self, scope: str, name: str) -> None:
        with self._mu:
            self.used.add(f"{scope}.{name}")

    def record_bad(self, scope: str, name: str, value: str) -> None:
        with self._mu:
            k = f"{scope}.{name}"
            self.bad_count[k] = self.bad_count.get(k, 0) + 1
            if len(self.bad.setdefault(k, [])) < 3:
                self.bad[k].append(value)

    def count(self, what: str) -> None:
        with self._mu:
            setattr(self, what, getattr(self, what) + 1)

    def presence(self, key: str) -> float:
        denom = self.properties if key.startswith("property.") else self.loans
        return self.present.get(key, 0) / denom if denom else 0.0

    def mapped_but_missing(self) -> list[str]:
        return sorted(k for k in self.used if self.present.get(k, 0) == 0)

    def present_but_unmapped(self) -> list[str]:
        return sorted(k for k in self.present if k not in self.used and k not in INTENTIONALLY_UNMAPPED)

    def report(self) -> str:
        lines = [f"\n=== EX-102 field coverage ({self.loans} loans, {self.members} portfolio member blocks, "
                 f"{self.properties} properties) ===",
                 "\nMapped but never present (wrong name, or just empty in this sample):"]
        lines += [f"  {k}" for k in self.mapped_but_missing()] or ["  (none)"]
        lines.append("\nMapped field fill rate (lowest first):")
        mapped = sorted((k for k in self.used if self.present.get(k)), key=lambda k: (self.presence(k), k))
        lines += [f"  {100 * self.presence(k):5.1f}%  {k}" for k in mapped]
        lines.append("\nPresent but unmapped (new fields to review):")
        lines += [f"  {k:<70} {self.present[k]}" for k in self.present_but_unmapped()] or ["  (none)"]
        lines.append("\nUnparseable values:")
        lines += [f"  {k} ({self.bad_count[k]}), e.g. {self.bad[k]}" for k in sorted(self.bad)] or ["  (none)"]
        return "\n".join(lines)


# ---- parsing ------------------------------------------------------------------


def parse(f: IO[bytes], cov: Coverage | None = None) -> Iterator[Loan]:
    """Stream an EX-102 file, yielding one Loan per <assets> block. Memory is
    bounded by the largest block, not the file."""
    try:
        for _, el in etree.iterparse(f, events=("end",), recover=False, huge_tree=True, remove_comments=True):
            if etree.QName(el).localname != "assets":
                continue
            yield _to_loan(el, cov)
            el.clear(keep_tail=False)
            while el.getprevious() is not None:  # free processed siblings
                del el.getparent()[0]
    except etree.XMLSyntaxError as e:
        raise ParseError(f"EX-102 xml: {e}") from e


def parse_filing(f: IO[bytes], cov: Coverage | None = None) -> tuple[list[Loan], list[str]]:
    """Parse a whole EX-102 and fold portfolio member blocks into their parent
    loans. Members whose parent isn't in the file are returned as loans and
    listed in orphans."""
    loans: list[Loan] = []
    members: list[Loan] = []
    by_asset: dict[str, int] = {}
    for l in parse(f, cov):
        if l.portfolio_member:
            members.append(l)
        else:
            by_asset[l.asset_number] = len(loans)
            loans.append(l)
    orphans = []
    for m in members:
        parent_seq = _member_of(m.asset_number)
        if parent_seq is None or parent_seq[0] not in by_asset:
            orphans.append(m.asset_number)
            loans.append(m)
            continue
        parent, seq = loans[by_asset[parent_seq[0]]], parent_seq[1]
        if not any(p.rollup for p in parent.properties):
            # The parent's own blocks describe the whole portfolio.
            for j, p in enumerate(parent.properties):
                p.rollup, p.seq = True, -j  # 0 for the usual single rollup
        for p in m.properties:
            p.seq = seq
            parent.properties.append(p)
    return loans, orphans


_MEMBER_NUMBER = re.compile(r"^(.+?)[.-](\d+)$")


def _member_of(asset: str) -> tuple[str, int] | None:
    m = _MEMBER_NUMBER.match(asset)
    if not m or int(m.group(2)) < 1:
        return None
    return m.group(1), int(m.group(2))


def _leaves(el) -> tuple[list[tuple[str, str]], list]:
    """Leaf (name, text) children in order, and nested elements."""
    leaves, nested = [], []
    for c in el:
        if not isinstance(c.tag, str):
            continue
        if len(c):
            nested.append(c)
        else:
            leaves.append((etree.QName(c).localname, (c.text or "").strip()))
    return leaves, nested


class _Fields:
    """Typed accessor over one element's leaf children; reports every lookup
    to Coverage. The first occurrence of a duplicated element wins."""

    def __init__(self, leaves: list[tuple[str, str]], scope: str, cov: Coverage | None):
        self.vals: dict[str, str] = {}
        self.scope, self.cov = scope, cov
        for name, text in leaves:
            self.vals.setdefault(name, text)
            if cov:
                cov.seen(scope, name)

    def get(self, name: str, kind: str) -> Any:
        if self.cov:
            self.cov.use(self.scope, name)
        s = self.vals.get(name, "")
        if kind == "str":
            return s
        if s == "":
            return None
        v = {"num": _num, "int": _int, "bool": _bool, "date": _date}[kind](s)
        if v is None and self.cov:
            self.cov.record_bad(self.scope, name, s if kind != "bool" else s.lower())
        return v

    def columns(self, mapping: list[tuple[str, str, str]]) -> dict[str, Any]:
        return {col: self.get(el, kind) for col, el, kind in mapping}


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _int(s: str) -> int | None:
    v = _num(s)
    return None if v is None else int(v)  # truncates toward zero


def _bool(s: str) -> bool | None:
    s = s.lower()
    if s in ("true", "1", "y", "yes"):
        return True
    if s in ("false", "0", "n", "no"):
        return False
    return None


# Dates in ABS-EE are MM-DD-YYYY; accept the other common shapes rather than
# dropping data. Two-digit fields are required; anything else is reported as
# unparseable in the coverage report instead of guessed.
_DATE_FORMATS = [(re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%m-%d-%Y"), (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
                 (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%m/%d/%Y"), (re.compile(r"^\d{2}-\d{4}$"), "%m-%Y"),
                 (re.compile(r"^\d{4}-\d{2}$"), "%Y-%m")]


def _date(s: str) -> date | None:
    for rx, fmt in _DATE_FORMATS:
        if rx.match(s):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                return None
    return None


def _to_loan(el, cov: Coverage | None) -> Loan:
    leaves, nested = _leaves(el)
    has_property = any(etree.QName(n).localname == "property" for n in nested)
    member = has_property and all(name in _MEMBER_IDENTITY for name, _ in leaves)
    # Loan-level fill rates are about loans, not member blocks.
    f = _Fields(leaves, "asset", None if member else cov)
    loan = Loan(asset_number=f.get("assetNumber", "str"), period_begin=f.get("reportingPeriodBeginningDate", "date"),
                period_end=f.get("reportingPeriodEndDate", "date"), portfolio_member=member,
                static=f.columns(LOAN_STATIC), obs=f.columns(LOAN_OBS))
    if not loan.asset_number:
        raise ParseError("EX-102 <assets> block without assetNumber")
    if cov:
        cov.count("members" if member else "loans")
    seq = 0
    for n in nested:
        if etree.QName(n).localname != "property":
            continue
        seq += 1
        if cov:
            cov.count("properties")
        pl, _ = _leaves(n)
        pf = _Fields(pl, "property", cov)
        loan.properties.append(Property(seq=seq, source_asset=loan.asset_number,
                                        static=pf.columns(PROP_STATIC), obs=pf.columns(PROP_OBS)))
    return loan
