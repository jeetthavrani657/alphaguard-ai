// Friendly names for the generated response shapes.
//
// schema.d.ts is GENERATED from the backend's schemas.py (npm run gen:types);
// never edit it by hand. These aliases just give the pieces short names.
import type { components } from "./schema";

type S = components["schemas"];

export type RiskAdjustedRatio = S["RiskAdjustedRatio"];
export type WindowMetrics = S["WindowMetrics"];
export type StrategyList = S["StrategyList"];
export type StrategySummary = S["StrategySummary"];
export type StrategyDetail = S["StrategyDetail"];
export type EquityResponse = S["EquityResponse"];
export type TradePage = S["TradePage"];
export type ScreenerResponse = S["ScreenerResponse"];
export type ScreenerRow = S["ScreenerRow"];
export type SymbolDetail = S["SymbolDetail"];
export type SymbolStrategyResult = S["SymbolStrategyResult"];
export type SliceMetrics = S["SliceMetrics"];
export type PriceSeries = S["PriceSeries"];
export type DataQualityResponse = S["DataQualityResponse"];
export type LedgerResponse = S["LedgerResponse"];
export type ForwardResponse = S["ForwardResponse"];
export type ForwardBooksResponse = S["ForwardBooksResponse"];
export type ForwardBook = S["ForwardBook"];
export type LiveQuotesResponse = S["LiveQuotesResponse"];
export type AdvisoryResponse = S["AdvisoryResponse"];
export type AdvisoryProfile = S["AdvisoryProfile"];
export type LiveQuote = S["LiveQuote"];
export type Health = S["Health"];
export type Window = "in_sample" | "out_of_sample";
