// API client. The pairing token lives in localStorage of the home-screen app
// (sandboxed per origin; the server is reachable only inside the tailnet).

const TOKEN_KEY = "finanzen.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: stays unpaired */
  }
}

export type Cached<T> = T & { __offline?: boolean; __fetched_at?: string };

async function request<T>(method: string, path: string, body?: unknown): Promise<Cached<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let resp: Response;
  try {
    resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Keine Verbindung zum Server.");
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(resp.status, data.error || `Fehler ${resp.status}`);
  if (resp.headers.get("X-Finanzen-Offline")) {
    data.__offline = true;
    data.__fetched_at = resp.headers.get("X-Finanzen-Fetched-At") ?? undefined;
  }
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function query(params: Record<string, string | number | number[] | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) continue;
    q.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// --- types (mirror the server's JSON) -------------------------------------------

export interface Period { key: string; label: string; start: string; end: string; days: number }
export interface CategorySum { id: number; name: string; color_slot: number | null; amount: number; n: number }
export interface AccountSum { id: number; name: string; kind: string; color_slot: number | null; amount: number; n: number }
export interface TrendPoint extends Period { spent: number; income: number }
export interface Account {
  id: number; name: string; kind: string; currency: string; institution: string | null; source: string;
  color_slot: number | null; iban: string | null; patterns: string; balance: number | null;
  balance_eur: number | null; connection_status: string | null; valid_until: string | null;
  last_sync_at: string | null;
}
export interface Overview {
  period: Period; today: string; spent: number; income: number; savings_rate: number | null;
  previous: { period: Period; spent_same_day: number; spent: number; income: number; cutoff: string };
  budget: { remaining: number; days_left: number; per_day: number | null };
  not_converted: number; pending: number;
  categories: CategorySum[]; cards: AccountSum[]; trend: TrendPoint[]; accounts: Account[];
}
export interface Status {
  version: string; demo: boolean; today: string; last_sync_at: string | null;
  warnings: { connection_id: number; institution: string; kind: string; days_left?: number; paused_until?: string }[];
  suggestions: number; unassigned_wallet: number;
}
export interface NetWorthPoint { date: string; value: number; not_converted: number }
export interface TxLink { kind: string; status: string; evidence: string; other_id: number | null; other?: Tx }
export interface Tx {
  id: number; date: string; status: string; source: string; amount: number; currency: string;
  amount_eur: number | null; original_amount: number | null; original_currency: string | null;
  counterparty: string | null; description: string; counterparty_iban: string | null; mcc: string | null;
  apple_pay: boolean; note: string | null; role: string; excluded_by_user: boolean;
  category: { id: number; name: string; color_slot: number | null; source: string; kind: string };
  account: { id: number; name: string; kind: string; color_slot: number | null };
  links: TxLink[];
}
export interface TxList {
  total: number; items: Tx[];
  budget: { period: Period; income: number; spent: number; remaining: number; days_left: number; per_day: number | null } | null;
}
export interface Category { id: number; name: string; kind: string; color_slot: number | null; builtin: number; sort: number }
export interface Rule { id: number; pattern: string; category_id: number; category: string }
export interface SankeyNode { id: string; label: string; column: number; kind: string; color_slot: number | null }
export interface SankeyLink { source: string; target: string; value: number }
export interface Explore {
  sankey: { nodes: SankeyNode[]; links: SankeyLink[]; income: number; spent: number; start: string; end: string };
  timeline: (Period & { spent: number; income: number })[];
}
export type Interval = "weekly" | "monthly" | "quarterly" | "halfyearly" | "yearly";
export interface RecurringItem {
  key: string; name: string; role: "expense" | "income"; interval: Interval;
  amount: number; previous_amount: number | null; monthly: number;
  last_date: string; next_date: string; overdue: boolean; count: number; tx_ids: number[];
  category: { id: number | null; name: string | null; color_slot: number | null };
  account: { id: number; name: string | null; color_slot: number | null };
}
export interface Recurring {
  items: RecurringItem[]; rejected: RecurringItem[]; monthly_expense: number; monthly_income: number;
}
export interface ExpectedBooking {
  date: string; name: string; amount: number; role: string; interval: Interval; key: string; overdue: boolean;
}
export interface ForecastAccount {
  id: number; name: string; kind: string; color_slot: number | null;
  balance: number; pending: number; forecast: number; lowest: number; lowest_date: string;
  expected: ExpectedBooking[];
}
export interface Forecast { today: string; until: string; accounts: ForecastAccount[]; balance: number; forecast: number }
