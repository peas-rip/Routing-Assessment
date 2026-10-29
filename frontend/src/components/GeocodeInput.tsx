import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export interface Place { address: string; latitude: number; longitude: number; }
interface GeocodeResult { place_id: string; display_name: string; latitude: number; longitude: number; }

export default function GeocodeInput({ label, value, onSelect }: { label: string; value: Place | null; onSelect: (p: Place) => void }) {
  const [text, setText] = useState(value?.address ?? "");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => setText(value?.address ?? ""), [value]);
  const onType = (q: string) => {
    setText(q); setOpen(true); window.clearTimeout(timer.current);
    if (q.trim().length < 2) { setResults([]); return; }
    timer.current = window.setTimeout(async () => { try { const res = await api.get("/geocoding/search/", { params: { q, limit: 5 } }); setResults(res.data.data); } catch { setResults([]); } }, 350);
  };
  const pick = (r: GeocodeResult) => { onSelect({ address: r.display_name, latitude: r.latitude, longitude: r.longitude }); setText(r.display_name); setOpen(false); };
  return (
    <div className="relative">
      <label className="field-label" htmlFor={`location-${label}`}>{label}</label>
      <input id={`location-${label}`} aria-label={label} className="field-control" value={text} onChange={(e) => onType(e.target.value)} onFocus={() => text.length > 1 && setOpen(true)} placeholder={`Search ${label.toLowerCase()}`} autoComplete="off" />
      {open && results.length > 0 && <ul className="absolute z-20 mt-2 max-h-56 w-full overflow-auto rounded-xl border border-slate-600 bg-slate-900 p-1 shadow-2xl" role="listbox">{results.map((r) => <li key={r.place_id} role="option" aria-selected="false" className="cursor-pointer rounded-lg px-3 py-2.5 text-sm text-slate-300 hover:bg-sky-400/10 hover:text-white" onMouseDown={() => pick(r)}>{r.display_name}</li>)}</ul>}
    </div>
  );
}
