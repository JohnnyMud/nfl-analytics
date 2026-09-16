import { Link, Route, Routes } from "react-router-dom";

import { Home } from "./pages/Home";
import { PlayerPage } from "./pages/Player";
import { TeamPage } from "./pages/Team";

export function App() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="wordmark" to="/">
          NFL Analytics
        </Link>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/teams/:teamAbbr" element={<TeamPage />} />
        <Route path="/players/:gsisId" element={<PlayerPage />} />
      </Routes>
    </div>
  );
}
