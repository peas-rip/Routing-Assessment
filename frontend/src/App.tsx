import { BrowserRouter, Routes, Route } from "react-router-dom";
import RouteInput from "./pages/RouteInput";
import RouteResults from "./pages/RouteResults";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RouteInput />} />
        <Route path="/results" element={<RouteResults />} />
      </Routes>
    </BrowserRouter>
  );
}