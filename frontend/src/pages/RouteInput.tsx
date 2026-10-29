import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import GeocodeInput from "../components/GeocodeInput";
import type { Place } from "../components/GeocodeInput";

const DEFAULT_ORIGIN: Place = {
  address: "New York, NY, USA",
  latitude: 40.7128,
  longitude: -74.006,
};
const DEFAULT_DEST: Place = {
  address: "Chicago, IL, USA",
  latitude: 41.8781,
  longitude: -87.6298,
};

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
      const res = await api.post("/routes/generate/", {
        origin,
        destination,
        departure_time: departure,
        load_weight_lbs: Number(loadWeight),
        checkpoint_interval_miles: Number(interval),
      });
      sessionStorage.setItem("routeTaskId", res.data.data.task_id);
      sessionStorage.setItem("routeMeta", JSON.stringify({ loadWeight, interval }));
      navigate("/results");
    } catch (e: any) {
      const err = e?.response?.data?.error;
      setError(err?.message || "Route generation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="card fade-in w-full max-w-md space-y-4 bg-slate-900 p-6 rounded-xl border border-slate-800 shadow-2xl">
        <h1 className="text-2xl font-bold">Weather-Aware Truck Routing</h1>
        <p className="text-sm text-slate-400">Pick the safest route by balancing weather and time.</p>

        <GeocodeInput label="Origin" value={origin} onSelect={setOrigin} />
        <GeocodeInput label="Destination" value={destination} onSelect={setDestination} />

        <div>
          <label className="block text-sm text-slate-400 mb-1">Departure time</label>
          <input
            type="datetime-local"
            className="w-full p-2 rounded bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={departAt}
            onChange={(e) => setDepartAt(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Load weight (lb)</label>
            <input
              type="number"
              className="w-full p-2 rounded bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={loadWeight}
              onChange={(e) => setLoadWeight(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Checkpoint interval (mi)</label>
            <select
              className="w-full p-2 rounded bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={interval}
              onChange={(e) => setIntervalMiles(Number(e.target.value))}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </div>
        </div>

        {error && <div className="text-sm text-red-400">{error}</div>}

        <button
          className="w-full bg-blue-600 hover:bg-blue-500 p-2 rounded disabled:opacity-50"
          onClick={submit}
          disabled={loading}
        >
          {loading ? "Generating…" : "Generate Routes"}
        </button>
      </div>
    </div>
  );
}
