import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { LABEL, money } from "../format";
import type { LoanClass, MapPoint, Metro } from "../types";

// Leaflet can't read CSS variables: the class palette, mirrored from styles.css.
const COLOR: Record<string, string> = {
  distressed: "#c0392b", gap_refi: "#d68910", clean_refi: "#1e8449", watch: "#2e6fb7", none: "#9aa4b1",
};

function View({ metro }: { metro?: Metro }) {
  const map = useMap();
  useEffect(() => {
    if (metro) map.setView([metro.lat, metro.lon], 8);
    else map.setView([38.5, -96], 4); // lower 48; HI, AK and PR stay reachable by panning
  }, [map, metro]);
  return null;
}

interface Props {
  points: MapPoint[];
  metro?: Metro;
  onPickMetro: (id: string) => void;
}

/** Filtered loans aggregated by metro (else state), sized by balance and
 * colored by the class holding most of it. EX-102 has no coordinates. */
export function OpportunityMap({ points, metro, onPickMetro }: Props) {
  const max = Math.max(1, ...points.map((p) => p.whole_balance));
  return (
    <MapContainer className="map" center={[38.5, -96]} zoom={4} scrollWheelZoom={false}>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={12}
      />
      <View metro={metro} />
      {points.map((p) => {
        const byClass = Object.entries(p.by_class).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)) as [LoanClass, number][];
        const color = COLOR[byClass[0]?.[0] ?? "none"] ?? COLOR.none;
        return (
          <CircleMarker
            key={p.key}
            center={[p.lat, p.lon]}
            radius={5 + 28 * Math.sqrt(p.whole_balance / max)}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.45, weight: 1.5 }}
            eventHandlers={{ click: () => p.metro && onPickMetro(p.metro) }}
          >
            <Tooltip>
              <b>{p.label}</b>
              <br />
              {p.loans} loans · {money(p.whole_balance)}
              {byClass.map(([c, v]) => (
                <div key={c}>{LABEL[c] ?? c}: {money(v)}</div>
              ))}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
