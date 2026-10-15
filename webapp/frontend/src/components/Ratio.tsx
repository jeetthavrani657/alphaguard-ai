import type { RiskAdjustedRatio } from "../api/types";
import { StatusChip } from "./StatusChip";

/**
 * THE ONLY WAY A SHARPE OR SORTINO IS RENDERED IN THIS APP.
 *
 * It takes the whole ratio object (value + status + hypothesis count), so a
 * number can never be drawn without its validation status beside it. This is
 * rule 5 of the web app brief, enforced twice:
 *   1. by types: the generated RiskAdjustedRatio has a required `status`;
 *   2. by a test (tests/test_webapp_frontend_rules.py) that fails if any other
 *      file reads a ratio's `.value` directly.
 *
 * A status is only true "as of" a hypothesis count, so that is shown too.
 * Styling never hides any of the three parts: value, status chip, "as of N".
 */
export function Ratio({ ratio }: { ratio: RiskAdjustedRatio }) {
  const value = ratio.value === null ? "n/a" : ratio.value.toFixed(3);
  const isSlice = ratio.status === "SLICE_OF_POOLED_HYPOTHESIS";
  return (
    <span className="ratio" title={isSlice ? "One stock's slice of a pooled test, not an independent hypothesis." : undefined}>
      {ratio.kind === "sortino" && <span className="asof">Sortino</span>}
      <span className="v">{value}</span>
      <StatusChip status={ratio.status} />
      <span className="asof">as of {ratio.as_of_hypotheses}</span>
      {isSlice && (
        <span className="parent">
          slice of {ratio.parent_strategy_id} ({ratio.parent_status}) · not a standalone test
        </span>
      )}
      {ratio.clears_bar === true && <span className="bar pos">clears Bonferroni bar</span>}
      {ratio.clears_bar === false && <span className="bar neg">below Bonferroni bar</span>}
    </span>
  );
}
