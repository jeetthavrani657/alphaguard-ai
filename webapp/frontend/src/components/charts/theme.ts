// Chart colours come from the SAME CSS variables the page uses (src/styles.css),
// read when a chart is drawn -- so the palette lives in exactly one place and the
// charts can never drift from the rest of the screen.
import { ColorType, type ChartOptions, type DeepPartial } from "lightweight-charts";

const css = (name: string, fallback: string): string => {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

export function chartColors() {
  return {
    text: css("--text", "#d7dee8"),
    muted: css("--muted", "#8494a8"),
    grid: css("--grid", "#1c2632"),
    border: css("--border", "#243040"),
    background: css("--panel", "#111821"),
    up: css("--pos", "#3fb950"),
    down: css("--neg", "#f85149"),
    strategy: css("--accent", "#4da3ff"),
    benchmark: css("--bench", "#e3b341"),
    sma50: css("--sma50", "#f0883e"),
    sma200: css("--sma200", "#bc8cff"),
    rsi: css("--rsi", "#39c5cf"),
    volume: css("--volume", "#3a4859"),
    drawdown: css("--neg", "#f85149"),
    exposure: css("--muted", "#8494a8"),
    // three distinguishable lines for the compare view; none is the buy-and-hold yellow, which means "the benchmark" everywhere else
    series: [css("--accent", "#4da3ff"), css("--sma200", "#bc8cff"), css("--rsi", "#39c5cf")],
  };
}

export function baseChartOptions(): DeepPartial<ChartOptions> {
  const c = chartColors();
  return {
    autoSize: true,                                   // follow the container's width
    layout: {
      background: { type: ColorType.Solid, color: c.background }, textColor: c.text,
      fontFamily: "ui-monospace, Consolas, monospace", fontSize: 12,
      panes: { separatorColor: c.border, separatorHoverColor: c.muted, enableResize: false },
    },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.border },
    timeScale: { borderColor: c.border, rightOffset: 4 },
    crosshair: { mode: 0 },                           // 0 = free-moving crosshair
    // The page is long: a wheel over the chart should scroll the PAGE, not silently zoom the chart.
    // Panning is by dragging; zoom by the range buttons or a touch pinch.
    handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
  };
}
