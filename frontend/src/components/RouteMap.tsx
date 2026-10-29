import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { riskColor, riskLabel } from "../risk";

export interface Checkpoint {
  id: string;
  sequence: number;
  mile_marker: string;
  latitude: number;
  longitude: number;
  estimated_arrival: string;
}

export interface RouteOption {
  id: string;
  route_index: number;
  name: string;
  distance_miles: string;
  duration_minutes: number;
  geometry: { coordinates: [number, number][] };
  checkpoints: Checkpoint[];
}

export interface HeatPoint {
  lat: number;
  lon: number;
  risk_level: string;
  risk_score: number;
}

export default function RouteMap({
  routes,
  recommendedId,
  selectedId,
  onSelect,
  riskByCheckpoint,
  heat,
}: {
  routes: RouteOption[];
  recommendedId: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  riskByCheckpoint: Record<string, string>;
  heat: HeatPoint[];
}) {
  const center: [number, number] = routes[0]?.geometry?.coordinates?.[0]
    ? [routes[0].geometry.coordinates[0][1], routes[0].geometry.coordinates[0][0]]
    : [40, -90];

  const selected = routes.find((r) => r.id === selectedId) ?? routes[0];

  return (
    <MapContainer center={center} zoom={6} style={{ height: "100%", width: "100%" }}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />

      {/* Weather heatmap points */}
      {heat.map((p, i) => (
        <CircleMarker
          key={`h-${i}`}
          center={[p.lat, p.lon]}
          radius={7}
          pathOptions={{ color: riskColor(p.risk_level), fillColor: riskColor(p.risk_level), fillOpacity: 0.4 }}
        >
          <Tooltip>{`${riskLabel(p.risk_level)} (${p.risk_score.toFixed(1)})`}</Tooltip>
        </CircleMarker>
      ))}

      {/* Route polylines */}
      {routes.map((r) => {
        const isRec = r.id === recommendedId;
        const isSel = r.id === selected?.id;
        return (
          <Polyline
            key={r.id}
            positions={r.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number])}
            pathOptions={{
              color: isRec ? "#22c55e" : isSel ? "#3b82f6" : "#94a3b8",
              weight: isRec || isSel ? 5 : 3,
              opacity: isRec || isSel ? 1 : 0.6,
            }}
            eventHandlers={{ click: () => onSelect(r.id) }}
          />
        );
      })}

      {/* Checkpoints for the selected route */}
      {selected?.checkpoints.map((cp) => {
        const level = riskByCheckpoint[cp.id];
        return (
          <CircleMarker
            key={cp.id}
            center={[cp.latitude, cp.longitude]}
            radius={6}
            pathOptions={{ color: riskColor(level), fillColor: "#0f172a", fillOpacity: 1, weight: 2 }}
          >
            <Tooltip>
              <div className="text-xs">
                <div>#{cp.sequence} · mile {cp.mile_marker}</div>
                <div>Risk: {riskLabel(level)}</div>
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
