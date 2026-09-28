"""Reads ingest's public.* tables into LoanHistory, one trust at a time so
memory stays bounded as history grows."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

import psycopg
from psycopg.types.numeric import FloatLoader

from .model import Companion, LoanHistory, LoanObservation, Property, PropertyObservation, Tenant

# Loans missing from their trust's latest report (paid off or removed
# without a liquidation code) are not live.
STALE_AFTER = timedelta(days=20)


def connect(dsn: str) -> psycopg.Connection:
    """A connection that returns numeric columns as float."""
    conn = psycopg.connect(dsn, autocommit=True)
    conn.adapters.register_loader("numeric", FloatLoader)
    return conn


class Loader:
    def __init__(self, conn: psycopg.Connection, include_inactive: bool = False):
        self.conn = conn
        # The backtest needs loans no longer in their trust's latest report.
        self.include_inactive = include_inactive
        self.other_trusts: dict[tuple[str, str], int] = {}
        # Same property name and location reported by several trusts: pari
        # passu notes of one whole loan. Rollups (portfolio names) have no
        # location and match on name alone.
        for trust, asset, n in conn.execute("""
            WITH p AS (
                SELECT DISTINCT trust_cik, asset_number,
                       lower(btrim(name)) AS n, coalesce(lower(city), '') AS c, coalesce(upper(state), '') AS s
                FROM properties WHERE name IS NOT NULL AND length(btrim(name)) > 3
            ), k AS (
                SELECT n, c, s, count(DISTINCT trust_cik) AS trusts FROM p GROUP BY n, c, s HAVING count(DISTINCT trust_cik) > 1
            )
            SELECT p.trust_cik, p.asset_number, max(k.trusts) - 1
            FROM p JOIN k USING (n, c, s) GROUP BY 1, 2"""):
            self.other_trusts[(trust, asset)] = n

    def trusts(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT trust_cik FROM loans ORDER BY 1")]

    def trust(self, trust: str) -> list[LoanHistory]:
        """Histories of a trust's live loans (all loans with include_inactive)."""
        loans: dict[str, LoanHistory] = {}
        order: list[str] = []
        for r in self.conn.execute("""
            SELECT asset_number, origination_date, maturity_date, ard_date, prepayment_lockout_end,
                   yield_maintenance_end, original_amount, debt_service_at_securitization, interest_only
            FROM loans WHERE trust_cik = %s ORDER BY asset_number""", (trust,)):
            h = LoanHistory(trust_cik=trust, asset_number=r[0], origination_date=r[1], maturity_date=r[2], ard_date=r[3],
                            prepayment_lockout_end=r[4], yield_maintenance_end=r[5], original_amount=r[6],
                            payment_at_sec=r[7], interest_only=r[8], other_trusts=self.other_trusts.get((trust, r[0]), 0))
            loans[h.asset_number] = h
            order.append(h.asset_number)

        for r in self.conn.execute("""
            SELECT asset_number, period_end, maturity_date, current_balance, current_rate, paid_through_date,
                   coalesce(payment_status, ''), coalesce(workout_strategy, ''), special_servicer_transfer_date,
                   master_servicer_return_date, pi_advances_outstanding, coalesce(liquidation_code, ''), modified,
                   liquidation_date, realized_loss, coalesce(modification_code, '')
            FROM loan_observations WHERE trust_cik = %s ORDER BY asset_number, period_end""", (trust,)):
            h = loans.get(r[0])
            if h is not None:
                h.observations.append(LoanObservation(
                    period_end=r[1], maturity_date=r[2], current_balance=r[3], current_rate=r[4], paid_through_date=r[5],
                    payment_status=r[6], workout_strategy=r[7], special_servicer_transfer_date=r[8],
                    master_servicer_return_date=r[9], pi_advances_outstanding=r[10], liquidation_code=r[11],
                    modified=r[12], liquidation_date=r[13], realized_loss=r[14], modification_code=r[15]))

        props: dict[tuple[str, int], Property] = {}
        for r in self.conn.execute("""
            SELECT asset_number, property_seq, is_rollup, coalesce(name, ''), coalesce(property_type, ''),
                   coalesce(city, ''), coalesce(state, ''), coalesce(net_rentable_sqft, sqft_at_securitization),
                   noi_at_securitization, ncf_at_securitization, dscr_at_securitization, dscr_ncf_at_securitization,
                   occupancy_at_securitization, valuation_at_securitization
            FROM properties WHERE trust_cik = %s ORDER BY asset_number, property_seq""", (trust,)):
            h = loans.get(r[0])
            if h is None:
                continue
            p = Property(seq=r[1], rollup=r[2], name=r[3], property_type=r[4], city=r[5], state=r[6], net_rentable=r[7],
                         noi_at_sec=r[8], ncf_at_sec=r[9], dscr_at_sec=r[10], dscr_ncf_at_sec=r[11],
                         occupancy_at_sec=r[12], valuation_at_sec=r[13])
            h.properties.append(p)
            props[(r[0], r[1])] = p

        for r in self.conn.execute("""
            SELECT asset_number, property_seq, period_end, coalesce(defeased_status, ''), occupancy,
                   financials_start_date, financials_end_date, noi, ncf, debt_service, valuation_amount,
                   coalesce(tenant1_name, ''), tenant1_sqft, tenant1_lease_exp,
                   coalesce(tenant2_name, ''), tenant2_sqft, tenant2_lease_exp,
                   coalesce(tenant3_name, ''), tenant3_sqft, tenant3_lease_exp
            FROM property_observations WHERE trust_cik = %s""", (trust,)):
            p = props.get((r[0], r[1]))
            if p is not None:
                p.observations[r[2]] = PropertyObservation(
                    defeased_status=r[3], occupancy=r[4], financials_start=r[5], financials_end=r[6], noi=r[7], ncf=r[8],
                    debt_service=r[9], valuation=r[10],
                    tenants=(Tenant(r[11], r[12], r[13]), Tenant(r[14], r[15], r[16]), Tenant(r[17], r[18], r[19])))

        group_companions(loans)

        # Keep loans in the trust's latest report.
        latest = max((h.observations[-1].period_end for h in loans.values() if h.observations), default=None)
        out = []
        for a in order:
            h = loans[a]
            if h.observations and (self.include_inactive or latest - h.observations[-1].period_end <= STALE_AFTER):
                out.append(h)
        return out


_NOTE_SUFFIX = re.compile(r"^(\d+)([A-Z])$")


def group_companions(loans: dict[str, LoanHistory]) -> None:
    """Fold notes of one loan held by the same trust (1, 1A, 1B) into the note
    that carries the financials. A suffixed note is a companion only if it has
    no financials of its own and a sibling does."""
    groups: dict[str, list[LoanHistory]] = defaultdict(list)
    for a, h in loans.items():
        m = _NOTE_SUFFIX.match(a)
        if m:
            groups[m.group(1)].append(h)
    for base, members in groups.items():
        if base in loans:
            members = members + [loans[base]]
        if len(members) < 2:
            continue
        members.sort(key=lambda h: h.asset_number)
        primary = next((h for h in members if _has_financials(h)), None)  # unsuffixed base sorts first
        if primary is None:
            continue
        for h in members:
            if h is primary or _has_financials(h):
                continue
            c = Companion(asset_number=h.asset_number, payment_at_sec=h.payment_at_sec)
            for o in h.observations:
                if o.current_balance is not None:
                    c.balances[o.period_end] = o.current_balance
                if o.current_rate is not None:
                    c.rates[o.period_end] = o.current_rate
            primary.companions.append(c)
            h.companion_of = primary.asset_number


def _has_financials(h: LoanHistory) -> bool:
    for p in h.properties:
        if p.noi_at_sec is not None or p.ncf_at_sec is not None:
            return True
        if any(o.noi is not None or o.ncf is not None for o in p.observations.values()):
            return True
    return False
