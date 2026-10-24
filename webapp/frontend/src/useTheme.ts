import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "alphaguard-theme";

/** The saved choice, else the computer's own light/dark setting, else dark. Browser storage can be blocked (private windows), so every access is guarded. */
function firstTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* storage unavailable: fall through */ }
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/** The page's theme and a way to flip it. The choice is a per-viewer convenience: it is remembered in this browser only. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(firstTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f4f6f9" : "#0b0f14");
    try { localStorage.setItem(KEY, theme); } catch { /* not saved: still works for this visit */ }
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return [theme, toggle];
}
