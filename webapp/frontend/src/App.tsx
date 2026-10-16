import { NavLink, Route, Routes } from "react-router-dom";
import { StatusBar } from "./components/StatusBar";
import { Overview } from "./pages/Overview";
import { Screener } from "./pages/Screener";
import { Stock } from "./pages/Stock";
import { Strategies } from "./pages/Strategies";
import { StrategyPage } from "./pages/StrategyPage";
import { PaperTrading } from "./pages/PaperTrading";
import { Research } from "./pages/Research";

// One URL per page. A page is just a React component: a function that returns what to
// draw. The router picks which one by looking at the URL.
//
//   /                     Overview        the front door: scoreboard and how to read it
//   /screener             Screener        every stock: table or sector heatmap
//   /stock/:symbol        Stock cockpit   one stock: chart, strategy slices, data quality
//   /strategies           Strategies      every strategy with its validation status
//   /strategies/:id       (detail of one strategy)
//   /paper                Paper trading   frozen candidates run forward, against buy-and-hold
//   /research             Research record hypothesis ledger, forward test, data quality
export default function App() {
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "tab active" : "tab");
  return (
    <>
      <StatusBar />
      <nav className="topnav">
        <NavLink to="/" className="brand" aria-label="AlphaGuard AI, home">
          <img src="/alphaguard-mark.svg" alt="" width={30} height={30} />
          <span className="brand-name">Alpha<b>Guard</b> <i>AI</i></span>
        </NavLink>
        <NavLink to="/" end className={tab}>Overview</NavLink>
        <NavLink to="/screener" className={tab}>Screener</NavLink>
        <NavLink to="/strategies" className={tab}>Strategies</NavLink>
        <NavLink to="/paper" className={tab}>Paper trading</NavLink>
        <NavLink to="/research" className={tab}>Research record</NavLink>
        <span className="spacer" />
        <span className="readonly">read-only · no orders, ever</span>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/screener" element={<Screener />} />
          <Route path="/stock/:symbol" element={<Stock />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/strategies/:id" element={<StrategyPage />} />
          <Route path="/paper" element={<PaperTrading />} />
          <Route path="/research" element={<Research />} />
          <Route path="*" element={<p>No such page.</p>} />
        </Routes>
      </main>
      <footer className="footer">
        <span><b>AlphaGuard AI</b> is a research tool, not investment advice. It places no orders and has no live data.</span>
        <span>Results are produced in the terminal by the validated backtest code; this page only displays them.</span>
      </footer>
    </>
  );
}
