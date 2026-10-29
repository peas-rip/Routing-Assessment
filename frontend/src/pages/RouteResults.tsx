import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import RouteMap from "../components/RouteMap";
import type { HeatPoint, RouteOption } from "../components/RouteMap";
import { riskColor, riskLabel } from "../risk";

interface Weather {
  checkpoint_id: string;
  temperature_f: string;
  conditions: string;
  wind_speed_mph: string;
  precipitation_type: string;
}

export default function RouteResults() {
  const navigate = useNavigate();
  const [routes, setRoutes] = useState<RouteOption[]>([]);
  const [recommendedId, setRecommendedId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [weather, setWeather] = useState<Record<string, Weather>>({});
  const [riskByCheckpoint, setRiskByCheckpoint] = useState<Record<string, string>>({});
  const [hour, setHour] = useState(0);
  const [heat, setHeat] = useState<HeatPoint[]>([]);
  const [status, setStatus] = useState("Loading…");
  const [error, setError] = useState("");

  // Poll route generation until completed.
  useEffect(() => {
    const taskId = sessionStorage.getItem("routeTaskId");
    if (!taskId) {
      navigate("/");
      return;
    }
    let stop = false;
    const poll = async () => {
      try {
        const res = await api.get(`/routes/${taskId}/`);
        const d = res.data.data;
        if (stop) return;
        if (d.routes) {
          setRoutes(d.routes);
          setSelectedId((prev) => prev ?? d.routes[0]?.id ?? null);
          setStatus("");
        } else {
          setStatus(d.message || "Generating routes…");
        }
      } catch (e: any) {
        if (stop) return;
        setError(e?.response?.data?.error?.message || "Failed to load routes.");
        setStatus("");
      }
    };
    poll();
    const interval = setInterval(poll, 2500);
    return () => {
      stop = true;
      clearInterval(interval);
    };
  }, [navigate]);

  const selected = routes.find((r) => r.id === selectedId) ?? routes[0];

  // Risk recommendation: calculate risk for every route first (the
  // recommendation endpoint needs assessments for at least two routes), then
  // retry until scoring is ready (weather can take a while).
  useEffect(() => {
    if (routes.length === 0) return;
    const meta = JSON.parse(sessionStorage.getItem("routeMeta") || "{}");
    const lw = meta.loadWeight ?? 30000;
    const iv = meta.interval ?? 25;
    let cancelled = false;
    const run = async () => {
      await Promise.all(
        routes.map((r) =>
          api
            .post("/risk/calculate/", {
              route_id: r.id,
              load_weight_lbs: lw,
              checkpoint_interval_miles: iv,
            })
            .catch(() => {}),
        ),
      );
      if (cancelled) return;
      for (let i = 0; i < 12; i++) {
        try {
          const res = await api.get(`/risk/recommendation/${routes[0].id}/`);
          if (cancelled) return;
          setRecommendedId(res.data.data.recommended_route_id);
          setSelectedId((prev) => prev ?? res.data.data.recommended_route_id);
          return;
        } catch {
          await new Promise((r) => setTimeout(r, 3000));
        }
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [routes]);

  // Per-checkpoint risk via the risk calculate endpoint for the selected route.
  useEffect(() => {
    if (!selected) return;
    const meta = JSON.parse(sessionStorage.getItem("routeMeta") || "{}");
    api
      .post("/risk/calculate/", {
        route_id: selected.id,
        load_weight_lbs: meta.loadWeight ?? 30000,
        checkpoint_interval_miles: meta.interval ?? 25,
      })
      .then((res) => {
        const map: Record<string, string> = {};
        for (const c of res.data.data.checkpoints ?? []) {
          map[c.checkpoint_id] = c.risk?.combined_risk;
        }
        setRiskByCheckpoint(map);
      })
      .catch(() => {});
  }, [selected]);

  // Weather for selected route checkpoints.
  useEffect(() => {
    if (!selected || selected.checkpoints.length === 0) return;
    const ids = selected.checkpoints.map((c) => c.id).join(",");
    api
      .get("/weather/checkpoints/", { params: { checkpoint_ids: ids } })
      .then((res) => {
        const map: Record<string, Weather> = {};
        for (const w of res.data.data) map[w.checkpoint_id] = w;
        setWeather(map);
      })
      .catch(() => setWeather({}));
  }, [selected]);

  // Weather heatmap grid for selected route at the chosen forecast hour.
  const loadHeat = useCallback(async () => {
    if (!selected) return;
    try {
      const res = await api.get("/weather/heatmap/", {
        params: { route_id: selected.id, hour },
      });
      setHeat(res.data.data.grid ?? []);
    } catch {
      setHeat([]);
    }
  }, [selected, hour]);

  useEffect(() => {
    loadHeat();
  }, [loadHeat]);

  const back = () => {
    sessionStorage.removeItem("routeTaskId");
    navigate("/");
  };

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-6">
        <div className="text-red-400">{error}</div>
        <button className="bg-slate-700 px-4 py-2 rounded" onClick={back}>New Search</button>
      </div>
    );
  }

  return (
    <div className="h-screen p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 h-[40vh] lg:h-full rounded overflow-hidden border border-slate-800">
        <RouteMap
          routes={routes}
          recommendedId={recommendedId}
          selectedId={selectedId}
          onSelect={setSelectedId}
          riskByCheckpoint={riskByCheckpoint}
          heat={heat}
        />
      </div>

      <div className="space-y-4 overflow-y-auto">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Route Options</h1>
          <button className="bg-slate-700 px-3 py-1 rounded text-sm" onClick={back}>New Search</button>
        </div>

        {status && <div className="text-slate-400 text-sm animate-pulse">{status}</div>}

        {routes.map((r) => {
          const isRec = r.id === recommendedId;
          const isSel = r.id === selected?.id;
          return (
            <div
              key={r.id}
              onClick={() => setSelectedId(r.id)}
              className={`p-4 rounded cursor-pointer border ${
                isSel ? "border-blue-500 bg-slate-800" : "border-slate-800 bg-slate-900"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">{r.name}</span>
                {isRec && <span className="text-xs bg-green-600 px-2 py-0.5 rounded">Recommended</span>}
              </div>
              <div className="text-sm text-slate-300 mt-1">
                {Number(r.distance_miles).toFixed(1)} mi · {r.duration_minutes} min ·{" "}
                {r.checkpoints.length} checkpoints
              </div>
            </div>
          );
        })}

        {selected && (
          <div className="bg-slate-900 border border-slate-800 rounded p-4 space-y-3">
            <h2 className="font-semibold">{selected.name} checkpoints</h2>
            <ul className="space-y-2 text-sm">
              {selected.checkpoints.map((cp) => {
                const w = weather[cp.id];
                const level = riskByCheckpoint[cp.id];
                return (
                  <li key={cp.id} className="flex items-center justify-between border-b border-slate-800 pb-1">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="inline-block w-2 h-2 rounded-full" style={{ background: riskColor(level) }} />
                        #{cp.sequence} · mile {Number(cp.mile_marker).toFixed(1)}
                      </div>
                      <div className="text-slate-400 text-xs">
                        {w ? `${w.temperature_f}°F · ${w.conditions}` : "weather loading…"}
                      </div>
                    </div>
                    <span className="text-xs capitalize" style={{ color: riskColor(level) }}>
                      {riskLabel(level)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="bg-slate-900 border border-slate-800 rounded p-4 space-y-2">
          <h2 className="font-semibold">Weather heatmap</h2>
          <label className="block text-sm text-slate-400">Forecast hour</label>
          <select
            value={hour}
            onChange={(e) => setHour(Number(e.target.value))}
            className="w-full p-2 rounded bg-slate-800 border border-slate-700"
          >
            {[0, 6, 12, 18, 24, 30, 36, 42, 48].map((h) => (
              <option key={h} value={h}>
                {h === 0 ? "Now" : `+${h}h`}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
