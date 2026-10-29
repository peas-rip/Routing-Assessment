import { useEffect } from "react";
import L from "leaflet";
import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, Marker, useMap } from "react-leaflet";
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

function pinIcon(label: string, color: string) {
  return L.divIcon({
    className: "route-pin",
    html: `<div class="route-pin-inner" style="background:${color}">${label}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function FitBounds({ coords }: { coords: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (coords.length > 0) {
      map.fitBounds(coords, { padding: [40, 40] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coords.length]);
  return null;
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
  const selected = routes.find((r) => r.id === selectedId) ?? routes[0];

  const origin = routes[0]?.checkpoints?.[0];
  const destination = routes[0]?.checkpoints?.[routes[0].checkpoints.length - 1];

  const center: [number, number] = origin
    ? [origin.latitude, origin.longitude]
    : [40, -90];

  const fitCoords: [number, number][] = routes[0]?.geometry?.coordinates?.map(
    ([lon, lat]) => [lat, lon] as [number, number],
  ) ?? [];

  return (
    <MapContainer center={center} zoom={6} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitBounds coords={fitCoords} />

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

      {routes.map((r) => {
        const isRec = r.id === recommendedId;
        const isSel = r.id === selected?.id;
        return (
          <Polyline
            key={r.id}
            positions={r.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number])}
            pathOptions={{
              color: isRec ? "#22c55e" : isSel ? "#3b82f6" : "#94a3b8",
              weight: isRec || isSel ? 6 : 3,
              opacity: isRec || isSel ? 1 : 0.5,
              lineJoin: "round",
            }}
            eventHandlers={{ click: () => onSelect(r.id) }}
          />
        );
      })}

      {selected?.checkpoints.map((cp) => {
        const level = riskByCheckpoint[cp.id];
        return (
          <CircleMarker
            key={cp.id}
            center={[cp.latitude, cp.longitude]}
            radius={5}
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

      {origin && (
        <Marker position={[origin.latitude, origin.longitude]} icon={pinIcon("A", "#22c55e")}>
          <Tooltip>Origin</Tooltip>
        </Marker>
      )}
      {destination && (
        <Marker position={[destination.latitude, destination.longitude]} icon={pinIcon("B", "#ef4444")}>
          <Tooltip>Destination</Tooltip>
        </Marker>
      )}
    </MapContainer>
  );
}
