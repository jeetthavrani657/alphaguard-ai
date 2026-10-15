import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, HistogramSeries, LineSeries, createChart, createSeriesMarkers,
  type IChartApi, type SeriesMarker, type Time,
} from "lightweight-charts";
import type { PriceSeries, SymbolDetail } from "../../api/types";
import { int, num, pct } from "../../fmt";
import { baseChartOptions, chartColors } from "./theme";

type Marker = SymbolDetail["markers"][number];

/**
 * Candlesticks + SMA lines + trade markers on top, volume below, RSI below that.
 * All three are "panes" of ONE chart, so they share a time axis and crosshair.
 *
 * Nothing is computed here. Candles, volume, the SMA/RSI lines and the trade
 * markers are the exact arrays the API sent; the chart only draws them. The
 * indicator lines come from the strategy modules' own functions (the API's
 * `indicator_sources` says which), so a line here is the line a strategy trades on.
 */
export function PriceChart({ prices, markers }: { prices: PriceSeries; markers: Marker[] }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [hover, setHover] = useState<number | null>(null);        // index into prices.dates under the crosshair
  const strategies = useMemo(() => [...new Set(markers.map((m) => m.strategy_id))], [markers]);
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const isShown = (id: string) => shown[id] ?? true;

  useEffect(() => {
    if (!host.current) return;
    const p = prices;
    const chart = createChart(host.current, { ...baseChartOptions(), height: 560 });
    const colors = chartColors();
    chartRef.current = chart;

    // --- pane 0: candles, SMAs, markers ---
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: colors.up, downColor: colors.down, borderVisible: false, wickUpColor: colors.up, wickDownColor: colors.down,
    }, 0);
    candles.setData(p.dates.map((d, i) => ({ time: d as Time, open: p.open[i], high: p.high[i], low: p.low[i], close: p.close[i] })));

    const lineData = (values: (number | null)[]) =>
      p.dates.flatMap((d, i) => (values[i] === null ? [] : [{ time: d as Time, value: values[i] as number }]));
    const palette = [colors.sma50, colors.sma200];
    Object.entries(p.indicators).filter(([k]) => k.startsWith("sma_")).forEach(([k, v], j) => {
      chart.addSeries(LineSeries, { color: palette[j % palette.length], lineWidth: 2, title: k.toUpperCase().replace("_", " "),
        priceLineVisible: false, lastValueVisible: false }, 0).setData(lineData(v));
    });

    // Trade markers: arrow up at each entry, arrow down at each exit (green if the trade made money).
    const have = new Set(p.dates);                                  // a marker needs a bar to sit on
    const sm: SeriesMarker<Time>[] = [];
    for (const m of markers.filter((x) => isShown(x.strategy_id))) {
      if (have.has(m.entry_date)) sm.push({ time: m.entry_date as Time, position: "belowBar", shape: "arrowUp", color: colors.strategy, text: "in" });
      if (have.has(m.exit_date)) {
        sm.push({ time: m.exit_date as Time, position: "aboveBar", shape: "arrowDown",
          color: m.return_pct >= 0 ? colors.up : colors.down, text: pct(m.return_pct) });
      }
    }
    sm.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    createSeriesMarkers(candles, sm);

    // --- pane 1: volume ---
    const vol = chart.addSeries(HistogramSeries, { color: colors.volume, priceFormat: { type: "volume" }, priceLineVisible: false }, 1);
    vol.setData(p.dates.map((d, i) => ({ time: d as Time, value: p.volume[i] })));

    // --- pane 2: RSI ---
    const rsiKey = Object.keys(p.indicators).find((k) => k.startsWith("rsi_"));
    if (rsiKey) {
      chart.addSeries(LineSeries, { color: colors.rsi, lineWidth: 2, title: rsiKey.toUpperCase().replace("_", " "),
        priceLineVisible: false }, 2).setData(lineData(p.indicators[rsiKey]));
    }
    const panes = chart.panes();
    if (panes[0]) panes[0].setStretchFactor(0.58);   // price
    if (panes[1]) panes[1].setStretchFactor(0.14);   // volume
    if (panes[2]) panes[2].setStretchFactor(0.28);   // RSI

    // Legend: which bar is the crosshair on?
    const index = new Map(p.dates.map((d, i) => [d, i]));
    chart.subscribeCrosshairMove((param) => {
      setHover(typeof param.time === "string" ? index.get(param.time) ?? null : null);
    });

    // Open on the most recent ~2 years; the user can scroll and zoom out to everything.
    const n = p.dates.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 504), to: n + 4 });

    return () => { chart.remove(); chartRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prices, markers, shown]);

  const i = hover ?? prices.dates.length - 1;
  const ind = Object.keys(prices.indicators);

  const setRange = (bars: number | "all") => {
    const n = prices.dates.length;
    chartRef.current?.timeScale().setVisibleLogicalRange({ from: bars === "all" ? 0 : Math.max(0, n - bars), to: n + 4 });
  };

  return (
    <div>
      <div className="legendline">
        <b>{prices.dates[i]}</b> · O <b>{num(prices.open[i])}</b> H <b>{num(prices.high[i])}</b> L{" "}
        <b>{num(prices.low[i])}</b> C <b>{num(prices.close[i])}</b> · Vol <b>{int(prices.volume[i])}</b>
        {ind.map((k) => <span key={k}> · {k} <b>{num(prices.indicators[k][i])}</b></span>)}
      </div>
      <div className="controls" style={{ marginBottom: 10 }}>
        <span className="seg">
          <button onClick={() => setRange(126)}>6M</button><button onClick={() => setRange(252)}>1Y</button>
          <button onClick={() => setRange(504)}>2Y</button><button onClick={() => setRange(1260)}>5Y</button>
          <button onClick={() => setRange("all")}>All</button>
        </span>
        {strategies.length > 0 && <span className="muted">Trade markers:</span>}
        {strategies.map((id) => (
          <label key={id}>
            <input type="checkbox" checked={isShown(id)} onChange={(e) => setShown({ ...shown, [id]: e.target.checked })} /> {id}
          </label>
        ))}
      </div>
      <div className="chartbox"><div ref={host} /></div>
      <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
        ▲ entry · ▼ exit (green = profitable, red = loss; label is the trade's net return). Orange SMA 50, purple
        SMA 200. Lower panes: volume, RSI 14 (Wilder). Drag to pan; use the range buttons to zoom.
      </p>
    </div>
  );
}
