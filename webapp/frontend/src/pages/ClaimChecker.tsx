import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Term } from "../components/Term";
import { num, pct } from "../fmt";

// Typed text, not numbers, so a half-typed "1." or an empty box is not an error: it simply is not judged yet.
const parse = (s: string): number | null => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

const EXAMPLES: { label: string; claimed: string; years: string; tries: string }[] = [
  { label: "A vendor's ad: 2.3 over 3 years, 40 variants", claimed: "2.3", years: "3", tries: "40" },
  { label: "Impressive but one try: 2.0 over 3 years", claimed: "2", years: "3", tries: "1" },
  { label: "Good-looking, many tries: 1.2 over 5 years, 300 variants", claimed: "1.2", years: "5", tries: "300" },
  { label: "This project's own MA crossover, later window: 1.0 over 5.4 years, 220 ideas", claimed: "1", years: "5.4", tries: "220" },
];

/**
 * Judge a claim "annual Sharpe X over Y years after Z attempts" the way this project judges its own results. The API does the arithmetic; this page only asks for three numbers
 * and shows what came back. It knows nothing about any real strategy.
 */
export function ClaimChecker() {
  const [claimed, setClaimed] = useState("2.3");
  const [years, setYears] = useState("3");
  const [tries, setTries] = useState("40");
  const c = parse(claimed), y = parse(years), t = parse(tries);
  const problem =
    c === null || y === null || t === null ? "Fill in all three numbers."
      : c < -5 || c > 10 ? "The claimed Sharpe ratio must be between -5 and 10."
        : y < 0.5 || y > 50 ? "Years of data must be between half a year and 50."
          : !Number.isInteger(t) || t < 1 || t > 100000 ? "Variants tried must be a whole number from 1 to 100,000."
            : null;

  const state = useApi(() => (problem ? Promise.resolve(null) : api.claimCheck(c as number, y as number, t as number)), [claimed, years, tries]);

  return (
    <div>
      <div className="pagehead"><h1>Claim checker</h1></div>
      <p className="lede">
        Somebody says a trading rule has a <Term k="sharpe">Sharpe ratio</Term> of 2.3 over 3 years. Is that impressive or just what luck produces when enough things are tried? Enter the claim and how many
        variants were tried to get it (an ad rarely says), and this judges it the way this project judges its own results: against the best that <em>no-skill</em> attempts would be expected to show by chance.
      </p>

      <Panel title="The claim">
        <div className="claimform">
          <label>Annual Sharpe ratio claimed<input inputMode="decimal" value={claimed} onChange={(e) => setClaimed(e.target.value)} /></label>
          <label>Years of data it rests on<input inputMode="decimal" value={years} onChange={(e) => setYears(e.target.value)} /></label>
          <label>Variants or ideas tried to get it<input inputMode="numeric" value={tries} onChange={(e) => setTries(e.target.value)} /></label>
        </div>
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12 }}>
          Not sure how many were tried? Ask. A seller who cannot say how many versions were tried before the one on display is telling you something. If it was only ever one idea, enter 1.
        </p>
        <div className="chips" style={{ marginTop: 10 }}>
          {EXAMPLES.map((e) => (
            <button key={e.label} type="button" className="chip-btn" onClick={() => { setClaimed(e.claimed); setYears(e.years); setTries(e.tries); }}>{e.label}</button>
          ))}
        </div>
      </Panel>

      {problem ? <p className="note">{problem}</p> : (
        <Async state={state}>
          {(r) => r && (
            <>
              <p className={r.clears_luck_bar ? "note info" : "note"} role="status">
                {r.clears_luck_bar
                  ? <><b>This clears the luck bar.</b> It is at least 95% likely to be better than what {int(r.tries)} no-skill attempts would show by chance. That is a necessary check, not proof: it assumes returns are
                    ordinary, that costs were counted, and that nothing was peeked at.</>
                  : <><b>This does not clear the luck bar.</b> With {int(r.tries)} {r.tries === 1 ? "attempt" : "attempts"}, luck alone would be expected to produce a best result of about <b>{num(r.luck_bar_annual, 2)}</b> over {num(r.years, 1)} years.
                    A claim of {num(r.claimed_annual, 2)} cannot be told apart from that.</>}
              </p>
              <div className="kpis">
                <div className="kpi"><span className="kpi-label">The luck bar</span><span className="kpi-value">{num(r.luck_bar_annual, 2)}</span><span className="kpi-vs muted">what the best of {int(r.tries)} no-skill tries is expected to show</span></div>
                <div className="kpi"><span className="kpi-label">Chance it has no edge at all</span><span className="kpi-value">{pct(r.chance_of_no_edge_pct, 1)}</span><span className="kpi-vs muted">true edge zero or worse</span></div>
                <div className="kpi"><span className="kpi-label">Chance it beats luck</span><span className="kpi-value">{pct(r.chance_beats_luck_pct, 1)}</span><span className="kpi-vs muted">needs 95% to clear</span></div>
                <div className="kpi"><span className="kpi-label">Edge that would clear</span><span className="kpi-value">{num(r.edge_needed_annual, 2)}</span><span className="kpi-vs muted">for {num(r.years, 1)} years and {int(r.tries)} {r.tries === 1 ? "try" : "tries"}</span></div>
              </div>
              <p>
                {r.years_needed === null || r.years_needed === undefined
                  ? <>A claimed edge of {num(r.claimed_annual, 2)} would not clear the bar at this number of tries within 300 years.</>
                  : <>If the edge is real, it would need about <b>{num(r.years_needed, 1)} years</b> of data to be told apart from luck after {int(r.tries)} {r.tries === 1 ? "try" : "tries"}.</>}
              </p>
              <Panel title="The same claim after more attempts" flush>
                <div className="tablewrap">
                  <table className="stack">
                    <thead><tr><th className="num">Variants tried</th><th className="num">Luck bar</th><th className="num">Chance it beats luck</th></tr></thead>
                    <tbody>
                      {r.by_tries.map((x) => (
                        <tr key={x.tries}>
                          <td className="num" data-label="Variants tried">{int(x.tries)}</td>
                          <td className="num" data-label="Luck bar">{num(x.luck_bar_annual, 2)}</td>
                          <td className="num" data-label="Chance it beats luck">{pct(x.chance_beats_luck_pct, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted" style={{ padding: "8px 14px", margin: 0, fontSize: 12 }}>
                  This is how a good-looking number is made: try enough versions and keep the best. The claim stays the same; what it proves shrinks with every extra try.
                </p>
              </Panel>
            </>
          )}
        </Async>
      )}

      <Panel title="What this cannot tell you">
        <ul className="plain">
          <li>It assumes ordinary, bell-shaped daily returns. Strategies that sell options or collect small gains and lose big rarely look better than they are, so for those even a pass is generous.</li>
          <li>It assumes the claimed figure already includes realistic costs, was measured on data the rule never saw, and had no look-ahead. None of that can be checked from three numbers.</li>
          <li>A pass is not a reason to trade. A fail is a reason to ask more questions. The number of variants tried is the figure that matters most, and the one sellers most often leave out.</li>
        </ul>
      </Panel>
    </div>
  );
}

const int = (x: number) => x.toLocaleString("en-IN");
