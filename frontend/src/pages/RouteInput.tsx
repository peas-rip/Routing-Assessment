import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import GeocodeInput from "../components/GeocodeInput";
import type { Place } from "../components/GeocodeInput";

const DEFAULT_ORIGIN: Place = { address: "New York, NY, USA", latitude: 40.7128, longitude: -74.006 };
const DEFAULT_DEST: Place = { address: "Chicago, IL, USA", latitude: 41.8781, longitude: -87.6298 };

export default function RouteInput() {
  const [origin, setOrigin] = useState<Place | null>(DEFAULT_ORIGIN);
  const [destination, setDestination] = useState<Place | null>(DEFAULT_DEST);
  const [loadWeight, setLoadWeight] = useState(30000);
  const [interval, setIntervalMiles] = useState(25);
  const [departAt, setDepartAt] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async () => {
    setError("");
    if (!origin || !destination) {
      setError("Please select both origin and destination from the suggestions.");
      return;
    }
    setLoading(true);
    try {
      const departure = departAt ? new Date(departAt).toISOString() : new Date().toISOString();
      const res = await api.post("/routes/generate/", { origin, destination, departure_time: departure, load_weight_lbs: Number(loadWeight), checkpoint_interval_miles: Number(interval) });
      sessionStorage.setItem("routeTaskId", res.data.data.task_id);
      sessionStorage.setItem("routeMeta", JSON.stringify({ loadWeight, interval }));
      navigate("/results");
    } catch (e: any) {
      const d = e?.response?.data;
      setError(d?.message || d?.error || "Route generation failed.");
    } finally { setLoading(false); }
  };

  return (
    <main className="app-shell flex min-h-screen items-center justify-center px-4 py-8 sm:px-6">
      <section className="glass-panel w-full max-w-2xl overflow-hidden rounded-2xl">
        <div className="border-b border-slate-700/50 px-5 py-6 sm:px-8 sm:py-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-sky-400/15 text-lg text-sky-300" aria-hidden="true">RA</div>
            <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Route assessment</p><p className="text-xs text-slate-500">Weather-aware planning</p></div>
          </div>
          <h1 className="max-w-xl text-3xl font-bold tracking-tight text-white sm:text-4xl">Plan a safer drive before you roll.</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400 sm:text-base">Compare route options with weather checkpoints, risk levels, and estimated travel time in one view.</p>
        </div>

        <div className="flex flex-col gap-6 px-5 py-6 sm:px-8 sm:py-8">
          <div className="grid gap-4 sm:grid-cols-2">
            <GeocodeInput label="Starting point" value={origin} onSelect={setOrigin} />
            <GeocodeInput label="Destination" value={destination} onSelect={setDestination} />
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div><label className="field-label" htmlFor="departAt">Departure time <span className="font-normal text-slate-500">(optional)</span></label><input id="departAt" type="datetime-local" className="field-control" value={departAt} onChange={(e) => setDepartAt(e.target.value)} /></div>
            <div><label className="field-label" htmlFor="loadWeight">Load weight <span className="font-normal text-slate-500">(lb)</span></label><input id="loadWeight" type="number" min="0" className="field-control" value={loadWeight} onChange={(e) => setLoadWeight(Number(e.target.value))} /></div>
            <div><label className="field-label" htmlFor="interval">Checkpoints <span className="font-normal text-slate-500">(mi)</span></label><select id="interval" className="field-control" value={interval} onChange={(e) => setIntervalMiles(Number(e.target.value))}><option value={10}>Every 10 miles</option><option value={25}>Every 25 miles</option><option value={50}>Every 50 miles</option></select></div>
          </div>
          {error && <div role="alert" className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">{error}</div>}
          <button className="primary-action" onClick={submit} disabled={loading}>{loading ? "Generating route options…" : "Generate route options"}</button>
          <p className="text-center text-xs text-slate-500">You can review weather and checkpoint risk before choosing a route.</p>
        </div>
      </section>
    </main>
  );
}
