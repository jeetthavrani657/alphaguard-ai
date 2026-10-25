import { Link, NavLink, useLocation } from "react-router-dom";

export type NavItem = { to: string; label: string; end?: boolean };

/** Five groups instead of eight flat tabs: what is true today, the portfolio tool, the research, the paper tests, and the evidence behind it all. */
export const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Today", items: [{ to: "/", label: "Home", end: true }] },
  { group: "Portfolio", items: [{ to: "/advisory", label: "Portfolio advisor" }] },
  { group: "Research", items: [{ to: "/strategies", label: "Strategies" }, { to: "/compare", label: "Compare" }, { to: "/multiasset", label: "Multi-asset rules" }, { to: "/screener", label: "Stocks" }] },
  { group: "Paper trading", items: [{ to: "/paper", label: "Scoreboard", end: true }, { to: "/paper#go-live", label: "Go-live gates" }] },
  { group: "Evidence", items: [{ to: "/research", label: "Research log" }, { to: "/methodology", label: "How it works" }] },
];

/** A link is current when its page is open; the two Paper trading links tell themselves apart by the #go-live part of the address. */
function isCurrent(item: NavItem, pathname: string, hash: string): boolean {
  const [path, anchor] = item.to.split("#");
  if (anchor) return pathname === path && hash === `#${anchor}`;
  if (path === "/paper") return pathname === "/paper" && hash !== "#go-live";
  return item.end ? pathname === path : pathname === path || pathname.startsWith(`${path}/`);
}

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { pathname, hash } = useLocation();
  return (
    <aside id="sidebar" className={`sidebar${open ? " open" : ""}`} aria-label="Main">
      <NavLink to="/" className="brand" aria-label="AlphaGuard AI, home" onClick={onNavigate}>
        <img src="/alphaguard-mark.svg" alt="" width={30} height={30} />
        <span className="brand-name">Alpha<b>Guard</b> <i>AI</i></span>
      </NavLink>
      <nav>
        {NAV.map((g) => (
          <div className="nav-group" key={g.group}>
            <div className="nav-title">{g.group}</div>
            {g.items.map((i) => {
              const current = isCurrent(i, pathname, hash);
              return (
                <Link key={i.to} to={i.to} onClick={onNavigate} className={`nav-link${current ? " active" : ""}`} aria-current={current ? "page" : undefined}>
                  {i.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">Research only. Places no orders and cannot touch any account.</div>
    </aside>
  );
}
