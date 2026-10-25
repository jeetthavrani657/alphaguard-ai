// The ONLY place the frontend talks to the network.
//
// Every function is a GET (the API has no other kind of route) and returns a
// typed object. Nothing here, or anywhere in the frontend, computes a number:
// whatever the API sends is what the screen shows.

import type {
  AdvisoryForwardResponse, AdvisoryResponse, BasketResponse, MultiassetResponse, RebalanceResponse, DataQualityResponse, EquityResponse, ForwardBooksResponse, ForwardResponse, Health, LedgerResponse, LiveQuotesResponse, PriceSeries,
  CondorExplainer, GoLiveResponse, TrackRecord, OtherRulesResponse, ScreenerResponse, StockSelectionResponse, StrategyDetail, StrategyList, StrategyReport, SymbolDetail, TradePage, Window,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== "" && v !== false) qs.set(k, String(v));
  }
  const url = `/api${path}${qs.size ? `?${qs}` : ""}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    // The API explains itself: {"detail": "..."} for 404/503, a list for 422.
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// encodeURIComponent matters: NSE has tickers such as "M&M" and "BAJAJ-AUTO".
const sym = (s: string) => encodeURIComponent(s);

export const api = {
  health: () => get<Health>("/health"),
  strategies: () => get<StrategyList>("/strategies"),
  strategy: (id: string) => get<StrategyDetail>(`/strategies/${sym(id)}`),
  equity: (id: string, window: Window) => get<EquityResponse>(`/strategies/${sym(id)}/equity`, { window }),
  report: (id: string, window: Window) => get<StrategyReport>(`/strategies/${sym(id)}/report`, { window }),
  trades: (id: string, window: Window, limit: number, offset: number) =>
    get<TradePage>(`/strategies/${sym(id)}/trades`, { window, limit, offset }),
  screener: (p: { universe?: string; sector?: string; flagged_only?: boolean }) =>
    get<ScreenerResponse>("/screener", p),
  symbol: (s: string) => get<SymbolDetail>(`/symbols/${sym(s)}`),
  prices: (s: string, from_date?: string, to_date?: string) =>
    get<PriceSeries>(`/symbols/${sym(s)}/prices`, { from_date, to_date }),
  dataQuality: (p: { universe?: string; only_issues?: boolean }) => get<DataQualityResponse>("/data-quality", p),
  ledger: () => get<LedgerResponse>("/ledger"),
  forwardTest: () => get<ForwardResponse>("/forward-test"),
  forwardBooks: () => get<ForwardBooksResponse>("/forward-books"),
  liveQuotes: () => get<LiveQuotesResponse>("/live-quotes"),
  advisory: () => get<AdvisoryResponse>("/advisory"),
  multiasset: (family: "trend" | "momentum" = "trend") => get<MultiassetResponse>("/multiasset", { family }),
  stockSelection: () => get<StockSelectionResponse>("/stockselection"),
  otherRules: () => get<OtherRulesResponse>("/otherrules"),
  trackRecord: () => get<TrackRecord>("/track-record"),
  optionsExplainer: () => get<CondorExplainer>("/options-explainer"),
  golive: () => get<GoLiveResponse>("/golive"),
  advisoryForward: () => get<AdvisoryForwardResponse>("/advisory/forward"),
  rebalance: (profile: string, holdings: string) => get<RebalanceResponse>("/advisory/rebalance", { profile, holdings }),
  basket: (profile: string, amount: number) => get<BasketResponse>("/advisory/basket", { profile, amount }),
};
