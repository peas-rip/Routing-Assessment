import { useState } from "react";

const STORAGE_KEY = "routing_info_dismissed";

export default function InfoModal() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) !== "1";
    } catch {
      return true;
    }
  });

  const close = (dontShowAgain: boolean) => {
    if (dontShowAgain) {
      try {
        localStorage.setItem(STORAGE_KEY, "1");
      } catch {
        /* ignore */
      }
    }
    setOpen(false);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-w-lg w-full bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold">How to use this app</h2>

        <div className="space-y-2 text-sm text-slate-300">
          <p>1. Type an origin and destination, then <b>pick a suggestion</b> from the dropdown (required).</p>
          <p>2. Departure time must be within the next <b>48 hours</b>.</p>
          <p>3. Load weight: <b>10,000–80,000 lb</b>. Checkpoint interval: <b>10 / 25 / 50 mi</b>.</p>
          <p>4. Click <b>Generate Routes</b>. Routes, weather, and risk load automatically.</p>
        </div>

        <div className="space-y-2 text-sm text-slate-300">
          <h3 className="font-semibold text-slate-100">What to expect (free tier)</h3>
          <p>• Route generation can take <b>15–60s</b> (weather fetch for many checkpoints).</p>
          <p>• You may get <b>1–3 routes</b> depending on the road network (long trips often return fewer).</p>
          <p>• Weather is <b>US-only</b> (NWS). Risk depends on the live forecast.</p>
          <p>• Heatmap: use the <b>dropdown</b> (not rapid dragging) to avoid rate limits.</p>
          <p>• First request may be slow (~30s cold start on free hosting).</p>
        </div>

        <div className="space-y-2 text-sm text-slate-300">
          <h3 className="font-semibold text-slate-100">Risk legend</h3>
          <div className="flex flex-wrap gap-3">
            <span style={{ color: "#22c55e" }}>● Low</span>
            <span style={{ color: "#eab308" }}>● Moderate</span>
            <span style={{ color: "#f97316" }}>● High</span>
            <span style={{ color: "#ef4444" }}>● Severe</span>
            <span style={{ color: "#7c2d12" }}>● No Travel</span>
          </div>
        </div>

        <div className="space-y-2 text-sm text-slate-300">
          <h3 className="font-semibold text-slate-100">Demo tips</h3>
          <p>• Short route (e.g., New York → Newark) for fast generation.</p>
          <p>• Long route (e.g., New York → Chicago) to show the single-route fallback.</p>
          <p>• Load ≥ 40,000 lb to trigger load rules.</p>
          <p>• Wait for the recommendation to appear (retries automatically).</p>
        </div>

        <div className="flex items-center justify-between pt-2">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input type="checkbox" onChange={(e) => close(e.target.checked)} />
            Don't show again
          </label>
          <button
            className="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm"
            onClick={() => close(false)}
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
