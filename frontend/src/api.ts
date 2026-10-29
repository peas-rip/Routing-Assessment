import axios from "axios";
const raw = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
const base = raw.replace(/\/+$/, "");
export const api = axios.create({
  baseURL: base.endsWith("/api/v1") ? base : `${base}/api/v1`,
});