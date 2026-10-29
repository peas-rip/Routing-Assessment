export const RISK_ORDER = ["low", "moderate", "high", "severe", "no_travel"];

export const RISK_COLORS: Record<string, string> = {
  low: "#22c55e",
  moderate: "#eab308",
  high: "#f97316",
  severe: "#ef4444",
  no_travel: "#7c2d12",
};

export function riskColor(level?: string | null): string {
  return RISK_COLORS[level ?? ""] ?? "#64748b";
}

export function riskLabel(level?: string | null): string {
  return (level ?? "unknown").replace("_", " ");
}
