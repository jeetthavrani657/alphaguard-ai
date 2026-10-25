import type { Theme } from "../useTheme";
import { ViewSwitch } from "../useViewMode";

/** The slim bar above every page: the menu button (phones), the search box, the theme switch and the read-only badge. */
export function TopBar({ theme, onToggleTheme, onSearch, onMenu, menuOpen }: { theme: Theme; onToggleTheme: () => void; onSearch: () => void; onMenu: () => void; menuOpen: boolean }) {
  return (
    <div className="topbar">
      <button type="button" className="menubtn" onClick={onMenu} aria-label="Menu" aria-expanded={menuOpen} aria-controls="sidebar">
        <span aria-hidden="true">☰</span>
      </button>
      <button type="button" className="searchbtn" onClick={onSearch} aria-label="Search stocks, rules and pages">
        <span className="searchtext">Search stocks, rules and pages</span>
        <kbd aria-hidden="true">Ctrl K</kbd>
      </button>
      <span className="spacer" />
      <ViewSwitch />
      <button type="button" className="themebtn" onClick={onToggleTheme} aria-label={`Switch to the ${theme === "dark" ? "light" : "dark"} theme`}>{theme === "dark" ? "Light" : "Dark"}</button>
      <span className="readonly" title="This application only shows research results. It cannot place orders or touch any account.">read-only</span>
    </div>
  );
}
