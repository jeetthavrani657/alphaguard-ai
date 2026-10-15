import { NavLink, Route, Routes } from "react-router-dom";
import { StatusBar } from "./components/StatusBar";
import { Screener } from "./pages/Screener";
import { Stock } from "./pages/Stock";
import { Strategies } from "./pages/Strategies";
import { StrategyPage } from "./pages/StrategyPage";
import { Research } from "./pages/Research";

// Four pages, one URL each. A page is just a React component: a function that
// returns what to draw. The router picks which one by looking at the URL.
//
//   /                     Screener        every stock: table or sector heatmap
//   /stock/:symbol        Stock cockpit   one stock: chart, strategy slices, data quality
//   /strategies           Strategies      every strategy with its validation status
//   /strategies/:id       (detail of one strategy)
//   /research             Research record hypothesis ledger, forward test, data quality
export default function App() {
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "tab active" : "tab");
  return (
    <>
      <StatusBar />
      <nav className="topnav">
        <span className="brand">NSE<span>·</span>RESEARCH</span>
        <NavLink to="/" end className={tab}>Screener</NavLink>
        <NavLink to="/strategies" className={tab}>Strategies</NavLink>
        <NavLink to="/research" className={tab}>Research record</NavLink>
        <span className="spacer" />
        <span className="readonly">read-only · results are produced in the terminal · no orders, ever</span>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Screener />} />
          <Route path="/stock/:symbol" element={<Stock />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/strategies/:id" element={<StrategyPage />} />
          <Route path="/research" element={<Research />} />
          <Route path="*" element={<p>No such page.</p>} />
        </Routes>
      </main>
    </>
  );
}
