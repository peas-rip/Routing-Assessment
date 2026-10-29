import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export interface Place {
  address: string;
  latitude: number;
  longitude: number;
}

interface GeocodeResult {
  place_id: string;
  display_name: string;
  latitude: number;
  longitude: number;
}

export default function GeocodeInput({
  label,
  value,
  onSelect,
}: {
  label: string;
  value: Place | null;
  onSelect: (p: Place) => void;
}) {
  const [text, setText] = useState(value?.address ?? "");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setText(value?.address ?? ""), [value]);

  const onType = (q: string) => {
    setText(q);
    setOpen(true);
    window.clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const res = await api.get("/geocoding/search/", { params: { q, limit: 5 } });
        setResults(res.data.data);
      } catch {
        setResults([]);
      }
    }, 350);
  };

  const onBlur = async () => {
    // If the user typed a full address but didn't pick a suggestion,
    // auto-select the first geocoding result so the form still works.
    if (value && text.trim() === value.address) return;
    if (text.trim().length < 2) return;
    try {
      const res = await api.get("/geocoding/search/", { params: { q: text.trim(), limit: 1 } });
      const r = res.data.data?.[0];
      if (r) {
        onSelect({ address: r.display_name, latitude: r.latitude, longitude: r.longitude });
        setText(r.display_name);
      }
    } catch {
      /* leave as-is */
    }
    setOpen(false);
  };

  const pick = (r: GeocodeResult) => {
    onSelect({ address: r.display_name, latitude: r.latitude, longitude: r.longitude });
    setText(r.display_name);
    setOpen(false);
  };

  return (
    <div className="relative">
      <label className="block text-sm text-slate-400 mb-1">{label}</label>
      <input
        className="w-full p-2 rounded bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        value={text}
        onChange={(e) => onType(e.target.value)}
        onBlur={onBlur}
        placeholder={`Search ${label.toLowerCase()}`}
      />
      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full bg-slate-800 border border-slate-700 rounded max-h-56 overflow-auto">
          {results.map((r) => (
            <li
              key={r.place_id}
              className="p-2 hover:bg-slate-700 cursor-pointer text-sm"
              onClick={() => pick(r)}
            >
              {r.display_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
