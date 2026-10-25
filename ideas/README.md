# Ideas: the honest way to try a new rule

Every new rule goes through `research/try_idea.py`. It exists because the two easy ways to fool yourself in backtesting are to try many variants and remember only the best, and to
adjust the idea after seeing how it did. The tool makes both impossible to do by accident:

1. **Write the idea down first.** One small file here, `ideas/<id>.json`:

   ```json
   {
     "id": "ma_fast_nifty50",
     "name": "Faster moving-average crossover",
     "rationale": "Why this should work, in your own words. A real reason, at least a sentence.",
     "strategy": "ma_crossover",
     "universe": "nifty50",
     "grid": {"fast": [20, 30], "slow": [100, 150]}
   }
   ```

   - `strategy`: `ma_crossover`, `rsi_reversion` or `dip_target`. `universe`: `nifty50`, `midcap150` or `smallcap250`.
   - `grid`: every combination is **one hypothesis** (the example is 2 x 2 = 4). The names must be the strategy's own parameters; any you leave out keep the strategy's defaults.
   - More than 60 combinations is refused unless you add `--allow-large`: a grid that big mostly finds luck.

2. **See the cost before paying it.** `python research/try_idea.py ideas/ma_fast_nifty50.json --plan` prints how many ideas it would add to the ledger and how much
   stricter the bar becomes. It runs nothing and counts nothing.

3. **Commit the file.** The tool refuses to run a file that is not committed and unchanged. This is what makes "written before it was run" provable.

4. **Run it.** `python research/try_idea.py ideas/ma_fast_nifty50.json --run` runs every combination, counts all of them in the ledger in one step, and only then shows the
   verdicts. A run that crashes counts nothing. Each idea runs once; a changed idea is a new idea with a new id.

5. **Keep the record.** Commit the ledger and `reports/output/ideas/<id>_result.json`. The Track record page (`python research/track_record.py`) then checks that each idea file was
   saved before its run and has not been edited since.

What this cannot do: stop someone from running a backtest by hand outside the tool. It makes the honest route the easy one, and makes the record show which route each result came from.
