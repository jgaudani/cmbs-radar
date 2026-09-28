import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { api, loanHref } from "../api";
import { Chart, type ChartClick } from "../charts/Chart";
import { maturityWallOption } from "../charts/options";
import { Badge, Transition } from "../components/Badge";
import { ClassCards } from "../components/ClassCards";
import { PageHeader } from "../components/Layout";
import { OpportunityMap } from "../components/OpportunityMap";
import { money, months, pct, quarterMonths } from "../format";
import { useLoad } from "../hooks";
import { useMeta } from "../meta";
import { demoQuery } from "../query";
import type { LoanClass, Opportunity } from "../types";

const ACTIONABLE = "class=distressed,gap_refi,clean_refi,watch";

export function HomePage() {
  const { meta, error } = useMeta();
  const navigate = useNavigate();
  const summary = useLoad("all", () => api.summary(""));
  const points = useLoad("map", () => api.map(ACTIONABLE));
  const gaps = useLoad("gaps", () => api.opportunities("class=distressed,gap_refi&max_months=24&sort=gap&limit=8"));
  const moved = useLoad("moved", () => api.opportunities("changed=class&class=distressed,gap_refi,clean_refi,watch&sort=gap&limit=8"));

  const onWall = (e: ChartClick) => {
    const q = (e.data as { quarter?: string } | undefined)?.quarter;
    if (!q || !e.seriesId) return;
    const [from, to] = quarterMonths(q);
    const first = summary.data?.maturity_wall[0]?.quarter === q; // the first bar also holds loans past their refi date
    navigate(`/loans?${new URLSearchParams({ class: e.seriesId, ...(first ? {} : { refi_from: from }), refi_to: to, sort: "gap" })}`);
  };

  return (
    <>
      <PageHeader
        title="Refinance radar"
        sub="Public CMBS loans scored for refinance risk and routed to the Newmark team that can act"
      >
        {meta && (
          <Link className="button primary" to={`/loans?${demoQuery(meta.data_as_of)}`} title="Office loans in the NYC metro, refi within 18 months, with a refi gap">
            Demo: NYC office, 18 mo, gap
          </Link>
        )}
      </PageHeader>
      {(error || summary.error) && <p className="err">Couldn't load data: {error || summary.error}</p>}

      <ClassCards summary={summary.data} teams={meta?.teams ?? {}} onPick={(c: LoanClass) => navigate(`/loans?class=${c}`)} />

      <div className="two wide-left">
        <section className="card">
          <h3>Maturity wall <span className="muted">whole-loan balance by refi quarter · click a bar to see its loans</span></h3>
          <Chart option={maturityWallOption(summary.data?.maturity_wall ?? [])} height={280} label="Maturity wall" onClick={onWall} />
        </section>
        <section className="card flush">
          <h3>Where <span className="muted">actionable loans by metro · click to filter</span></h3>
          <OpportunityMap
            points={points.data ?? []}
            onPickMetro={(metro) => navigate(`/loans?metro=${metro}&${ACTIONABLE}`)}
          />
        </section>
      </div>

      <div className="two">
        <LoanList
          title="Largest refi gaps, next 24 months"
          more={`/loans?class=distressed,gap_refi&max_months=24`}
          rows={gaps.data?.opportunities}
          total={gaps.data?.total}
          right={(o) => <><b>{money(o.refi_gap_whole)}</b><div className="ploc">{pct(o.refi_gap_pct)} of {money(o.whole_balance)}</div></>}
          badge={(o) => <Badge cls={o.class} />}
        />
        <LoanList
          title="Changed class since last report"
          more="/loans?changed=class"
          rows={moved.data?.opportunities}
          total={moved.data?.total}
          right={(o) => <><b>{money(o.refi_gap_whole)}</b><div className="ploc">{months(o.months_to_refi)}</div></>}
          badge={(o) => (o.prev_class ? <Transition from={o.prev_class as LoanClass} to={o.class} /> : <Badge cls={o.class} />)}
        />
      </div>
      {meta && <p className="muted foot">{meta.limits} Whole-loan balances for loans split across trusts are estimates. Map points are metro or state centers.</p>}
    </>
  );
}

interface ListProps {
  title: string;
  more: string;
  rows?: Opportunity[];
  total?: number;
  right: (o: Opportunity) => ReactNode;
  badge: (o: Opportunity) => ReactNode;
}

function LoanList({ title, more, rows, total, right, badge }: ListProps) {
  return (
    <section className="card">
      <h3>{title}</h3>
      {!rows && <p className="muted">Loading…</p>}
      {rows?.length === 0 && <p className="muted">None this month.</p>}
      <ul className="loan-list">
        {rows?.map((o) => (
          <li key={o.id}>
            <Link to={loanHref(o.id)}>
              <div>
                <div className="pname">{o.name || "(unnamed)"}</div>
                <div className="ploc">{o.city}, {o.state} · {o.property_type_label} · {badge(o)}</div>
              </div>
              <div className="num">{right(o)}</div>
            </Link>
          </li>
        ))}
      </ul>
      {total != null && total > (rows?.length ?? 0) && <Link className="more" to={more}>All {total.toLocaleString()} →</Link>}
    </section>
  );
}
