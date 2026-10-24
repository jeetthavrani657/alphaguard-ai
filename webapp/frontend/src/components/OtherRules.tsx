import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { OtherRule } from "../api/types";
import { Async } from "./Async";
import { Panel } from "./Panel";
import { Ratio } from "./Ratio";
import { Term } from "./Term";
import { plain } from "../labels";
import { day, inr, int, num, pct, signClass } from "../fmt";

/**
 * The Nifty options rules and the same-day stock rules (OPTIONS_IDEAS.md, INTRADAY_IDEAS.md): what each did in the practice and the unseen period.
 * Every figure is read from the API; the only Sharpe values drawn here go through <Ratio>, so none appears without its status.
 */
function unseenTrades(r: OtherRule) {
  if (r.family === "options") {
    const w = r.options_windows.find((x) => x.window === "out_of_sample");
    if (!w || w.n_trades === 0) return "No trades in the unseen period.";
    return (
      <>
        {int(w.n_trades)} trades, won <b>{pct(w.win_rate_pct, 0)}</b>. Profit after costs <b className={signClass(w.total_net_profit)}>{inr(w.total_net_profit)}</b>.
        The worst single trade: <b className="neg">{inr(w.worst_trade)}</b>; without it the total would have been{" "}
        <b className={signClass(w.total_net_profit_without_worst_trade)}>{inr(w.total_net_profit_without_worst_trade)}</b>.
      </>
    );
  }
  const w = r.intraday_windows.find((x) => x.window === "out_of_sample");
  if (!w || w.n_trades === 0) return "No trades in the unseen period.";
  return (
    <>
      {int(w.n_trades)} trades ({num(w.trades_per_day, 0)} a day). Average gain per trade before costs <b className={signClass(w.mean_gross_pct)}>{pct(w.mean_gross_pct, 3)}</b>, against{" "}
      <b>{pct(w.bar_pct, 1)}</b> needed just to cover costs; after costs <b className={signClass(w.mean_net_pct)}>{pct(w.mean_net_pct, 3)}</b> per trade.
    </>
  );
}

export function OtherRules() {
  const state = useApi(() => api.otherRules(), []);
  return (
    <Panel title="Options and same-day ideas" flush>
      <Async state={state}>
        {(d) => (
          <>
            <div style={{ padding: "10px 14px" }}>
              <p className="note info" style={{ margin: 0 }}>
                Ideas on Nifty options and on buying and selling stocks within one day, each written down and frozen before any result existed, then run once and counted.
                Results are from {day(d.generated_at)}, when <b>{d.ledger_total_at_generation}</b> ideas had been tried{d.is_stale ? " (more have been tried since)" : ""}.
                Everything is simulated; nothing here places an order. Options money is on an account of ₹10,00,000.
              </p>
            </div>
            <div className="tablewrap scroll">
              <table>
                <thead>
                  <tr>
                    <th>Idea</th>
                    <th>Practice period</th>
                    <th>Unseen period</th>
                    <th className="num">Unseen return a year</th>
                    <th className="num">Unseen worst fall</th>
                    <th>What the trades looked like (unseen period)</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rules.map((r) => (
                    <tr key={r.id}>
                      <td className="wrap">
                        <b>{plain(r.name)}</b>
                        <div className="muted">{r.family === "options" ? "Nifty options" : "Same-day stock trades"}</div>
                      </td>
                      <td><Ratio ratio={r.strategy.in_sample.sharpe} /></td>
                      <td><Ratio ratio={r.strategy.out_of_sample.sharpe} /></td>
                      <td className={`num ${signClass(r.strategy.out_of_sample.cagr_pct)}`}>{pct(r.strategy.out_of_sample.cagr_pct)}</td>
                      <td className="num neg">{pct(r.strategy.out_of_sample.max_drawdown_pct)}</td>
                      <td className="wrap">{unseenTrades(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ padding: "10px 14px" }}>
              <p className="muted" style={{ margin: 0 }}>
                A result only counts if it clears the <Term k="bonferroni">Bonferroni bar</Term>, which gets harder with every idea tried. A rule that wins often can still fail it:
                selling options earns small amounts many times and loses a lot rarely. Same-day trades pay the cost of getting in and out every day, which is why their gain
                per trade has to be large before it earns anything.
              </p>
            </div>
          </>
        )}
      </Async>
    </Panel>
  );
}
