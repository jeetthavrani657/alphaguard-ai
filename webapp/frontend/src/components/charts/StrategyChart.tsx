import { useEffect, useRef, useState } from "react";
import {
  AreaSeries, BaselineSeries, LineSeries, PriceScaleMode, createChart,
  type IChartApi, type Time,
} from "lightweight-charts";
import type { EquityResponse } from "../../api/types";
import { num, pct } from "../../fmt";
import { baseChartOptions, chartColors } from "./theme";

type Curve = { dates: string[]; values: number[] };

/**
 * What the chart needs, and nothing about where it came from. A strategy page passes an EquityResponse;
 * the paper-trading page passes a forward book's series. Rupee curves are only a fallback for old
 * snapshots: growth-of-100 is what gets drawn.
 */
export type ChartData = Pick<
  EquityResponse,
  "growth_strategy" | "growth_benchmark" | "drawdown_strategy_pct" | "drawdown_benchmark_pct" | "exposure_strategy_pct" | "exposure_definition"
> & Partial<Pick<EquityResponse, "strategy" | "benchmark">>;
const toData = (c: Curve) => c.dates.map((d, i) => ({ time: d as Time, value: c.values[i] }));

/**
 * Three panes in ONE chart, so they share a time axis and crosshair:
 *   1. equity (strategy vs buy-and-hold, in Rs)
 *   2. drawdown (% below the running peak)
 *   3. exposure (% of books invested)
 *
 * The three series are computed by engine/metrics.py when the snapshot is made
 * (compute_metrics' own drawdown function, so the deepest point on pane 2 IS the
 * max-drawdown figure in the table). This file only draws them.
 */
export function StrategyChart({ data }: { data: ChartData }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [log, setLog] = useState(false);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, { ...baseChartOptions(), height: 620 });
    const colors = chartColors();
    chartRef.current = chart;

    // pane 0: growth of 100 (each curve divided by its OWN starting capital, so a one-account
    // portfolio and a one-account-per-stock benchmark are drawn on the same footing)
    const growthS = data.growth_strategy ?? data.strategy;
    const growthB = data.growth_benchmark ?? data.benchmark;
    if (!growthS || !growthB) { chart.remove(); return; }
    const s = chart.addSeries(LineSeries, { color: colors.strategy, lineWidth: 2, title: "Strategy", priceLineVisible: false }, 0);
    s.setData(toData(growthS));
    chart.addSeries(LineSeries, { color: colors.benchmark, lineWidth: 2, title: "Buy & hold", priceLineVisible: false }, 0)
      .setData(toData(growthB));
    s.priceScale().applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal });

    // pane 1: drawdown (filled between the line and zero)
    if (data.drawdown_strategy_pct && data.drawdown_benchmark_pct) {
      const dd = (c: Curve, color: string, title: string) =>
        chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: 0 }, topLineColor: color, bottomLineColor: color,
          topFillColor1: "rgba(0,0,0,0)", topFillColor2: "rgba(0,0,0,0)",
          bottomFillColor1: color + "55", bottomFillColor2: color + "11", lineWidth: 1, title, priceLineVisible: false,
          priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(1)}%` },
        }, 1).setData(toData(c));
      dd(data.drawdown_benchmark_pct, colors.benchmark, "B&H DD");
      dd(data.drawdown_strategy_pct, colors.strategy, "Strategy DD");
    }

    // pane 2: exposure (0-100%, fixed range so a flat 0% or 100% is not auto-stretched)
    if (data.exposure_strategy_pct) {
      chart.addSeries(AreaSeries, {
        lineColor: colors.exposure, topColor: colors.exposure + "66", bottomColor: colors.exposure + "11", lineWidth: 1,
        title: "Exposure", priceLineVisible: false,
        priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(0)}%` },
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
      }, 2).setData(toData(data.exposure_strategy_pct));
    }

    const panes = chart.panes();
    // Proportions of the chart's height (a stretch factor, not pixels, so they survive re-layout).
    if (panes[0]) panes[0].setStretchFactor(0.55);
    if (panes[1]) panes[1].setStretchFactor(0.25);
    if (panes[2]) panes[2].setStretchFactor(0.20);

    chart.subscribeCrosshairMove((p) => setHover(typeof p.time === "string" ? p.time : null));
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [data, log]);

  // Legend values at the crosshair (or the last date): looked up by date, never derived.
  const at = (c: Curve | null | undefined) => {
    if (!c) return null;
    const i = hover ? c.dates.indexOf(hover) : c.dates.length - 1;
    return i >= 0 ? { date: c.dates[i], v: c.values[i] } : null;
  };
  const eq = at(data.growth_strategy ?? data.strategy), bh = at(data.growth_benchmark ?? data.benchmark);
  const dd = at(data.drawdown_strategy_pct), ddb = at(data.drawdown_benchmark_pct), ex = at(data.exposure_strategy_pct);

  return (
    <div>
      <div className="legendline">
        <b>{eq?.date}</b> · Growth of 100: Strategy <b>{num(eq?.v, 1)}</b> · Buy &amp; hold <b>{num(bh?.v, 1)}</b>
        {" "}· Drawdown <b>{pct(dd?.v)}</b> (B&amp;H {pct(ddb?.v)}) · Exposure <b>{pct(ex?.v, 0)}</b>
      </div>
      <div className="controls" style={{ marginBottom: 10 }}>
        <label><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log scale (growth)</label>
        <button onClick={() => chartRef.current?.timeScale().fitContent()}>Reset zoom</button>
      </div>
      <div className="chartbox"><div ref={host} /></div>
      <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
        Exposure: {data.exposure_definition ?? "not in this snapshot — regenerate it"}
      </p>
      {!data.drawdown_strategy_pct && (
        <p className="error" role="alert">This snapshot predates drawdown/exposure series: re-run the snapshot command.</p>
      )}
    </div>
  );
}
