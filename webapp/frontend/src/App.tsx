import { Suspense, lazy, useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { Skeleton } from "./components/Async";
import { CommandPalette } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { strategyLabel } from "./labels";
import { Overview } from "./pages/Overview";
import { useTheme } from "./useTheme";

// Pages with charts or long tables load on demand, so the first screen appears quickly. Each import returns the whole module,
// and `named` picks the page component out of it.
const named = <T extends Record<string, unknown>>(load: () => Promise<T>, key: keyof T) =>
  lazy(() => load().then((m) => ({ default: m[key] as React.ComponentType })));
const Screener = named(() => import("./pages/Screener"), "Screener");
const Stock = named(() => import("./pages/Stock"), "Stock");
const Strategies = named(() => import("./pages/Strategies"), "Strategies");
const Compare = named(() => import("./pages/Compare"), "Compare");
const ClaimChecker = named(() => import("./pages/ClaimChecker"), "ClaimChecker");
const TrackRecord = named(() => import("./pages/TrackRecord"), "TrackRecord");
const ReportCard = named(() => import("./pages/ReportCard"), "ReportCard");
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
//   /strategies/:id/card  (the same strategy on one printable page: "Save as PDF")
//   /compare              Compare         two or three strategies on one chart and one table
//   /screener             Stocks          every stock: table or sector heatmap
//   /stock/:symbol        Stock cockpit   one stock: chart, strategy slices, data quality
//   /paper                Paper trading   frozen candidates run forward, against buy-and-hold
//   /track-record         Track record    checks, from git history, that the record was never rewritten
//   /claim-checker        Claim checker   judge "Sharpe X over Y years after Z tries" against what luck produces
//   /research             Research log    hypothesis ledger, forward test, data quality
//   /methodology          How it works    how the results were produced and what they cannot show
const TITLES: [RegExp, string][] = [
  [/^\/$/, "Home"], [/^\/advisory/, "Portfolio advisor"], [/^\/multiasset/, "Multi-asset trading rules"],
  [/^\/compare/, "Compare strategies"], [/^\/strategies\/[^/]+\/card$/, "Report card"], [/^\/strategies\/.+/, "Strategy"], [/^\/strategies/, "Strategies"], [/^\/screener/, "Stocks"],
  [/^\/stock\/(.+)/, "Stock"], [/^\/paper/, "Paper trading"], [/^\/research/, "Research log"], [/^\/track-record/, "Track record"], [/^\/claim-checker/, "Claim checker"], [/^\/methodology/, "How it works"],
];

/**
 * Sets the browser tab's title for the page shown, starts each new page at the top, and scrolls to the part named in the address (/paper#go-live)
 * once it has been drawn: the page and its data arrive after the click, so the part is looked for a few times before giving up.
 */
function PageChrome() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    const hit = TITLES.find(([re]) => re.test(pathname));
    const detail = pathname.match(/^\/(?:stock|strategies)\/([^/]+)/)?.[1];
    document.title = `${hit ? hit[1] : "Page not found"}${detail ? `: ${/^\/strategies\//.test(pathname) ? strategyLabel(decodeURIComponent(detail)) : decodeURIComponent(detail)}` : ""} · AlphaGuard AI`;
  }, [pathname]);
  useEffect(() => {
    if (!hash) { window.scrollTo(0, 0); return; }
    const id = decodeURIComponent(hash.slice(1));
    let tries = 0;
    const timer = window.setInterval(() => {
      const el = document.getElementById(id);
      if (el) { el.scrollIntoView(); window.clearInterval(timer); } else if (++tries > 40) window.clearInterval(timer);
    }, 100);
    return () => window.clearInterval(timer);
  }, [pathname, hash]);
  return null;
}

/** One boundary per address: moving to another page clears a failure, so a crash on one page never sticks to the next. */
function Guarded({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]);
  // Ctrl+K (Cmd+K on a Mac) or "/" opens the search from anywhere, except while typing in a field; Escape closes the phone menu.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); setSearchOpen(true); }
      else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); setSearchOpen(true); }
      else if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <a className="skip" href="#main">Skip to the page</a>
      <PageChrome />
      <StatusBar />
      <div className="shell">
        <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
        {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
        <div className="content">
          <TopBar theme={theme} onToggleTheme={toggleTheme} onSearch={() => setSearchOpen(true)} onMenu={() => setMenuOpen((o) => !o)} menuOpen={menuOpen} />
          <main id="main">
        <Guarded key={theme}><Suspense fallback={<div className="loading"><Skeleton lines={4} /></div>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/screener" element={<Screener />} />
            <Route path="/stock/:symbol" element={<Stock />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/strategies/:id" element={<StrategyPage />} />
            <Route path="/strategies/:id/card" element={<ReportCard />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/multiasset" element={<MultiAsset />} />
            <Route path="/advisory" element={<Advisory />} />
            <Route path="/paper" element={<PaperTrading />} />
            <Route path="/research" element={<Research />} />
            <Route path="/track-record" element={<TrackRecord />} />
            <Route path="/claim-checker" element={<ClaimChecker />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="*" element={<div className="note">No such page. <a href="/">Back to the home page</a>.</div>} />
          </Routes>
        </Suspense></Guarded>
          </main>
          <footer className="footer">
            <span><b>AlphaGuard AI</b> is a research tool, not investment advice. It places no orders.</span>
            <span>Results are produced in the terminal by the validated backtest code; these pages only display them. <a href="/methodology">How it works</a></span>
          </footer>
        </div>
      </div>
      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}
