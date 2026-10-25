import { useEffect, useRef, useState } from "react";
import { LineSeries, PriceScaleMode, createChart, type IChartApi, type Time } from "lightweight-charts";
import { num } from "../../fmt";
import { baseChartOptions, chartColors } from "./theme";

export type CompareCurve = { id: string; name: string; dates: string[]; values: number[] };

// Fixed height for the same reason as StrategyChart: a container sized by its own chart can creep taller at fractional zoom.
const CHART_HEIGHT = 380;

/**
 * Several strategies' growth-of-100 curves on one axis. Each curve is the one the API sent for that strategy (each divided by its OWN
 * starting capital); nothing is re-based or averaged here. The legend reads each value at the crosshair by looking up the date.
 */
export function CompareChart({ curves }: { curves: CompareCurve[] }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [log, setLog] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const palette = chartColors().series;

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, { ...baseChartOptions(), height: CHART_HEIGHT });
    chartRef.current = chart;
    const colors = chartColors().series;
    curves.forEach((c, i) => {
      const s = chart.addSeries(LineSeries, { color: colors[i % colors.length], lineWidth: 2, title: c.name, priceLineVisible: false });
      s.setData(c.dates.map((d, k) => ({ time: d as Time, value: c.values[k] })));
      if (i === 0) s.priceScale().applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal });
    });
    chart.subscribeCrosshairMove((p) => setHover(typeof p.time === "string" ? p.time : null));
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [curves, log]);

  return (
    <div>
      <div className="legendline comparelegend">
        {curves.map((c, i) => {
          const k = hover ? c.dates.indexOf(hover) : c.dates.length - 1;
          return (
            <span key={c.id}><i style={{ background: palette[i % palette.length] }} /> {c.name}: <b>{k >= 0 ? num(c.values[k], 1) : "—"}</b></span>
          );
        })}
        <span className="muted">{hover ?? "latest"}</span>
      </div>
      <div className="controls" style={{ marginBottom: 10 }}>
        <label><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log scale</label>
        <button onClick={() => chartRef.current?.timeScale().fitContent()}>Reset zoom</button>
      </div>
      <div className="chartbox"><div ref={host} style={{ height: CHART_HEIGHT, width: "100%" }} /></div>
    </div>
  );
}
