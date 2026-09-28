// Amounts arrive as integer cents (EUR unless stated). Formatting only here.

const whole = new Intl.NumberFormat("de-AT", { style: "currency", currency: "EUR", maximumFractionDigits: 0, minimumFractionDigits: 0 });
const cents = new Intl.NumberFormat("de-AT", { style: "currency", currency: "EUR" });
// de-AT groups plain numbers with a space, currency with a dot; use the dot everywhere.
const grouped = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

/** Key figure: no cents ("€ 1.234"). */
export function eur(minor: number | null | undefined): string {
  if (minor == null) return "–";
  return whole.format(Math.round(minor / 100)).replace("-", "−");
}

/** List amount: with cents ("€ 12,50"). */
export function eurCents(minor: number | null | undefined, currency = "EUR"): string {
  if (minor == null) return "–";
  const fmt = currency === "EUR" ? cents : new Intl.NumberFormat("de-AT", { style: "currency", currency });
  const digits = fmt.resolvedOptions().maximumFractionDigits ?? 2;
  return fmt.format(minor / 10 ** digits).replace("-", "−");
}

/** Signed list amount: "+€ 12,50" / "−€ 12,50". */
export function signed(minor: number, currency = "EUR"): string {
  const s = eurCents(Math.abs(minor), currency);
  return (minor > 0 ? "+" : minor < 0 ? "−" : "") + s;
}

/** Axis ticks: whole euros, grouped ("2.500"). */
export function axis(minor: number): string {
  return grouped.format(Math.round(minor / 100)).replace("-", "−");
}

export function percent(ratio: number | null | undefined): string {
  if (ratio == null) return "–";
  return new Intl.NumberFormat("de-AT", { style: "percent", maximumFractionDigits: 0 }).format(ratio).replace("-", "−");
}

const dayFmt = new Intl.DateTimeFormat("de-AT", { day: "numeric", month: "short" });
const dayLong = new Intl.DateTimeFormat("de-AT", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

export function day(iso: string): string {
  return dayFmt.format(new Date(iso + "T12:00:00"));
}

export function dayLongFmt(iso: string): string {
  return dayLong.format(new Date(iso + "T12:00:00"));
}

const MONTHS = ["Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

export function monthShort(key: string): string {
  const [, m] = key.split("-").map(Number);
  return MONTHS[m - 1];
}

export function relativeDay(iso: string, today: string): string {
  const diff = Math.round((Date.parse(today) - Date.parse(iso)) / 86400000);
  if (diff === 0) return "Heute";
  if (diff === 1) return "Gestern";
  return dayLong.format(new Date(iso + "T12:00:00")).replace(/, \d{4}$/, "").replace(/ \d{4}$/, "");
}

const monthYearFmt = new Intl.DateTimeFormat("de-AT", { month: "short", year: "numeric" });

export function monthYear(iso: string): string {
  return monthYearFmt.format(new Date(iso + "T12:00:00"));
}
