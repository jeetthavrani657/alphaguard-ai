import { Suspense, lazy, useEffect } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Skeleton } from "./components/Async";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { StatusBar } from "./components/StatusBar";
import { strategyLabel } from "./labels";
import { Overview } from "./pages/Overview";

// Pages with charts or long tables load on demand, so the first screen appears quickly. Each import returns the whole module,
// and `named` picks the page component out of it.
const named = <T extends Record<string, unknown>>(load: () => Promise<T>, key: keyof T) =>
  lazy(() => load().then((m) => ({ default: m[key] as React.ComponentType })));
const Screener = named(() => import("./pages/Screener"), "Screener");
const Stock = named(() => import("./pages/Stock"), "Stock");
const Strategies = named(() => import("./pages/Strategies"), "Strategies");
const StrategyPage = named(() => import("./pages/StrategyPage"), "StrategyPage");
const PaperTrading = named(() => import("./pages/PaperTrading"), "PaperTrading");
const Advisory = named(() => import("./pages/Advisory"), "Advisory");
const MultiAsset = named(() => import("./pages/MultiAsset"), "MultiAsset");
const Research = named(() => import("./pages/Research"), "Research");
const Methodology = named(() => import("./pages/Methodology"), "Methodology");

// One URL per page. A page is just a React component: a function that returns what to
// draw. The router picks which one by looking at the URL.
//
//   /                     Home            what you can do here, and the scoreboard
//   /advisory             Portfolio advisor   a risk-managed mix for your risk appetite, with amounts and rebalancing
//   /multiasset           Multi-asset     trend-filter trading rules over six asset classes, against no timing
//   /strategies           Strategies      every strategy with its validation status
//   /strategies/:id       (detail of one strategy)
//   /screener             Stocks          every stock: table or sector heatmap
//   /stock/:symbol        Stock cockpit   one stock: chart, strategy slices, data quality
//   /paper                Paper trading   frozen candidates run forward, against buy-and-hold
//   /research             Research log    hypothesis ledger, forward test, data quality
//   /methodology          How it works    how the results were produced and what they cannot show
const TITLES: [RegExp, string][] = [
  [/^\/$/, "Home"], [/^\/advisory/, "Portfolio advisor"], [/^\/multiasset/, "Multi-asset trading rules"],
  [/^\/strategies\/.+/, "Strategy"], [/^\/strategies/, "Strategies"], [/^\/screener/, "Stocks"],
  [/^\/stock\/(.+)/, "Stock"], [/^\/paper/, "Paper trading"], [/^\/research/, "Research log"], [/^\/methodology/, "How it works"],
];

/** Sets the browser tab's title for the page shown, and starts each new page at the top. */
function PageChrome() {
  const { pathname } = useLocation();
  useEffect(() => {
    const hit = TITLES.find(([re]) => re.test(pathname));
    const detail = pathname.match(/^\/(?:stock|strategies)\/(.+)$/)?.[1];
    document.title = `${hit ? hit[1] : "Page not found"}${detail ? `: ${/^\/strategies\//.test(pathname) ? strategyLabel(decodeURIComponent(detail)) : decodeURIComponent(detail)}` : ""} · AlphaGuard AI`;
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/** One boundary per address: moving to another page clears a failure, so a crash on one page never sticks to the next. */
function Guarded({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}

export default function App() {
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "tab active" : "tab");
  return (
    <>
      <a className="skip" href="#main">Skip to the page</a>
      <PageChrome />
      <StatusBar />
      <nav className="topnav" aria-label="Main">
        <NavLink to="/" className="brand" aria-label="AlphaGuard AI, home">
          <img src="/alphaguard-mark.svg" alt="" width={30} height={30} />
          <span className="brand-name">Alpha<b>Guard</b> <i>AI</i></span>
        </NavLink>
        <NavLink to="/" end className={tab}>Home</NavLink>
        <NavLink to="/advisory" className={tab}>Portfolio advisor</NavLink>
        <NavLink to="/multiasset" className={tab}>Multi-asset</NavLink>
        <NavLink to="/strategies" className={tab}>Strategies</NavLink>
        <NavLink to="/screener" className={tab}>Stocks</NavLink>
        <NavLink to="/paper" className={tab}>Paper trading</NavLink>
        <NavLink to="/research" className={tab}>Research log</NavLink>
        <NavLink to="/methodology" className={tab}>How it works</NavLink>
        <span className="spacer" />
        <span className="readonly" title="This application only shows research results. It cannot place orders or touch any account.">read-only</span>
      </nav>
      <main id="main">
        <Guarded><Suspense fallback={<div className="loading"><Skeleton lines={4} /></div>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/screener" element={<Screener />} />
            <Route path="/stock/:symbol" element={<Stock />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/strategies/:id" element={<StrategyPage />} />
            <Route path="/multiasset" element={<MultiAsset />} />
            <Route path="/advisory" element={<Advisory />} />
            <Route path="/paper" element={<PaperTrading />} />
            <Route path="/research" element={<Research />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="*" element={<div className="note">No such page. <a href="/">Back to the home page</a>.</div>} />
          </Routes>
        </Suspense></Guarded>
      </main>
      <footer className="footer">
        <span><b>AlphaGuard AI</b> is a research tool, not investment advice. It places no orders.</span>
        <span>Results are produced in the terminal by the validated backtest code; these pages only display them. <a href="/methodology">How it works</a></span>
      </footer>
    </>
  );
}
