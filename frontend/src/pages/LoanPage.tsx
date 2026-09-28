import { Link, useLocation, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { LoanDetail } from "../components/LoanDetail";
import { PageHeader } from "../components/Layout";
import { ShareButton } from "../components/ShareButton";
import { WatchButton } from "../components/WatchButton";
import { place } from "../format";
import { useLoad } from "../hooks";

export function LoanPage() {
  const { trust = "", asset = "" } = useParams();
  const id = `${trust}/${asset}`;
  const navigate = useNavigate();
  const location = useLocation();
  const { data: d, error } = useLoad(id, () => api.detail(id));
  const loaded = d?.id === id ? d : null;

  // Back to the list the user came from (its filters are in its URL), else all loans.
  const back = () => (location.key !== "default" ? navigate(-1) : navigate("/loans"));

  return (
    <>
      <button className="link back" onClick={back}>← Back</button>
      <PageHeader
        title={loaded ? loaded.name || "(unnamed)" : error ? "Loan not found" : "Loading…"}
        sub={loaded && <>{place(loaded.city, loaded.state)} · {loaded.property_type_label || loaded.property_type} · {loaded.trust_name} (loan {loaded.asset_number}) · report {loaded.as_of_report}</>}
      >
        {loaded && <WatchButton loan={{ id: loaded.id, name: loaded.name }} />}
        <ShareButton title="Copy a link to this loan" />
      </PageHeader>
      {error && <p className="err">{error} <Link to="/loans">All loans</Link></p>}
      {loaded && <LoanDetail d={loaded} />}
    </>
  );
}
