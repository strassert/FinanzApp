<script lang="ts">
  import { api, query, type Category, type Period, type Tx, type TxList } from "../lib/api";
  import { eur, monthShort, relativeDay, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import { route, go } from "../lib/router.svelte";
  import TxDetail from "../components/TxDetail.svelte";
  import Suggestions from "../components/Suggestions.svelte";

  let { onerror, demo = false }: { onerror: (e: unknown) => void; demo?: boolean } = $props();

  let periods = $state<Period[]>([]);
  let categories = $state<Category[]>([]);
  let accounts = $state<{ id: number; name: string }[]>([]);
  let list = $state<TxList | null>(null);
  let items = $state<Tx[]>([]);
  let search = $state("");
  let selected = $state<number | null>(null);
  let loading = $state(false);

  const period = $derived(route.params.get("period") ?? "");
  const category = $derived(route.params.get("kategorie") ?? "");
  const account = $derived(route.params.get("konto") ?? "");
  const q = $derived(route.params.get("q") ?? "");
  const showSuggestions = $derived(route.params.get("vorschlaege") === "1");

  function setParam(key: string, value: string | number | undefined) {
    const params: Record<string, string> = {};
    route.params.forEach((v, k) => (params[k] = v));
    if (value === undefined || value === "") delete params[key];
    else params[key] = String(value);
    go("umsaetze", params);
  }

  async function loadMeta() {
    try {
      const [p, c, a] = await Promise.all([
        api.get<{ current: Period; items: Period[] }>("/api/periods"),
        api.get<{ items: Category[] }>("/api/categories"),
        api.get<{ items: { id: number; name: string }[] }>("/api/accounts"),
      ]);
      periods = p.items;
      categories = c.items;
      accounts = a.items;
    } catch (e) {
      onerror(e);
    }
  }
  loadMeta();

  async function load(append = false) {
    loading = true;
    try {
      const params = {
        period: q ? undefined : period || undefined, from: q ? "2000-01-01" : undefined,
        category: category || undefined, accounts: account || undefined, q: q || undefined,
        limit: 100, offset: append ? items.length : 0,
      };
      const data = await api.get<TxList>("/api/transactions" + query(params));
      list = data;
      items = append ? [...items, ...data.items] : data.items;
    } catch (e) {
      onerror(e);
    } finally {
      loading = false;
    }
  }

  $effect(() => { void period; void category; void account; void q; search = q; load(); });

  const groups = $derived.by(() => {
    const out: { day: string; items: Tx[] }[] = [];
    for (const t of items) {
      const last = out[out.length - 1];
      if (last && last.day === t.date) last.items.push(t);
      else out.push({ day: t.date, items: [t] });
    }
    return out;
  });
  const today = $derived(new Date().toISOString().slice(0, 10));
  const currentIdx = $derived(periods.findIndex((p) => p.key === (period || list?.budget?.period.key)));

  function step(delta: number) {
    const target = periods[currentIdx - delta];   // periods are newest first
    if (target) setParam("period", target.key);
  }

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setParam("q", search.trim()), 350);
  }

  function title(t: Tx): string {
    return t.counterparty || t.description || "Umsatz";
  }
</script>

<div class="filters">
  {#if !q}
    <div class="period">
      <button class="nav" aria-label="Vorheriger Zeitraum" disabled={currentIdx >= periods.length - 1} onclick={() => step(-1)}>‹</button>
      <span class="label">{list?.budget?.period.label ?? "…"}</span>
      <button class="nav" aria-label="Nächster Zeitraum" disabled={currentIdx <= 0} onclick={() => step(1)}>›</button>
    </div>
  {/if}
  <input type="search" placeholder="Suchen (Händler, Text, Notiz)" bind:value={search} oninput={onSearch}
         aria-label="Umsätze durchsuchen" />
  <div class="chips">
    <select aria-label="Konto" value={account} onchange={(e) => setParam("konto", e.currentTarget.value)}>
      <option value="">Alle Konten</option>
      {#each accounts as a}<option value={a.id}>{a.name}</option>{/each}
    </select>
    <select aria-label="Kategorie" value={category} onchange={(e) => setParam("kategorie", e.currentTarget.value)}>
      <option value="">Alle Kategorien</option>
      {#each categories as c}<option value={c.id}>{c.name}</option>{/each}
    </select>
  </div>
</div>

{#if list?.budget && !q}
  {@const b = list.budget}
  <section class="card budget" aria-label="Budget">
    <div><span class="k">Rest</span><span class="v num" class:neg={b.remaining < 0}>{eur(b.remaining)}</span></div>
    <div><span class="k">Einnahmen</span><span class="v num">{eur(b.income)}</span></div>
    <div><span class="k">Ausgegeben</span><span class="v num">{eur(b.spent)}</span></div>
    <div><span class="k">Übrig pro Tag</span><span class="v num">{b.per_day !== null ? eur(b.per_day) : "–"}</span></div>
    {#if b.fixed_expected}
      <p class="fixed">Rest nach {eur(-b.fixed_expected)} Fixkosten, die noch kommen{#if b.income_expected}, mit {eur(b.income_expected)} erwarteten Einnahmen{/if}</p>
    {/if}
  </section>
{/if}

<Suggestions open={showSuggestions} {demo} {onerror} onchange={() => load()} />

<div class:reloading={loading}>
  {#each groups as g (g.day)}
    <h3 class="day">{relativeDay(g.day, today)}</h3>
    <ul class="card list">
      {#each g.items as t (t.id)}
        <li>
          <button type="button" onclick={() => (selected = t.id)} class:muted-row={t.role === "transfer" || t.role === "excluded"}>
            <span class="icon" style:background={slotVar(t.category.color_slot)} aria-hidden="true"></span>
            <span class="text">
              <span class="title">{title(t)}</span>
              <span class="sub small muted">
                {t.category.name} · {t.account.name}
                {#if t.status === "pending"}<span class="tag">vorgemerkt</span>{/if}
                {#if t.budget_date && t.budget_date.slice(0, 7) !== t.date.slice(0, 7)}<span class="tag">zählt für {monthShort(t.budget_date.slice(0, 7))}</span>{/if}
                {#if t.apple_pay}<span class="tag">Apple Pay</span>{/if}
                {#if t.role === "excluded"}<span class="tag">nicht mitgezählt</span>{/if}
                {#if t.note}<span class="note">· {t.note}</span>{/if}
              </span>
            </span>
            <span class="amount num" class:pos={t.amount > 0 && t.role !== "transfer"}>
              {signed(t.amount, t.currency)}
              {#if t.currency !== "EUR" && t.amount_eur !== null}<span class="small muted eur">{signed(t.amount_eur)}</span>{/if}
            </span>
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    {#if list}<div class="card muted">Keine Umsätze gefunden.</div>{/if}
  {/each}
  {#if list && items.length < list.total}
    <button class="more" onclick={() => load(true)}>Weitere laden ({list.total - items.length})</button>
  {/if}
</div>

{#if selected !== null}
  <TxDetail id={selected} {categories} {demo} {onerror}
            onclose={(changed) => { selected = null; if (changed) load(); }}
            onopen={(id) => (selected = id)} />
{/if}

<style>
  .filters { display: grid; gap: 10px; margin-bottom: 12px; }
  .period { display: flex; align-items: center; justify-content: space-between; }
  .period .label { font-weight: 600; font-size: 17px; }
  .nav { border: 0; background: var(--surface); box-shadow: 0 0 0 1px var(--border); width: 40px; height: 36px;
         border-radius: 10px; font-size: 22px; line-height: 1; cursor: pointer; color: var(--ink); }
  .nav:disabled { opacity: .35; }
  input[type="search"], select {
    font: inherit; font-size: 16px; color: var(--ink); background: var(--surface); border: 0;
    box-shadow: 0 0 0 1px var(--border); border-radius: 12px; padding: 10px 12px; width: 100%; min-width: 0;
  }
  select { width: auto; flex: 1; font-size: 14px; padding: 8px 10px; -webkit-appearance: none; appearance: none; }
  .budget { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; padding: 12px 14px; }
  .budget div { display: grid; gap: 2px; }
  .budget .k { font-size: 11px; color: var(--muted); }
  .budget .v { font-weight: 600; font-size: 15px; }
  .budget .fixed { grid-column: 1 / -1; margin: 2px 0 0; font-size: 12px; color: var(--muted); }
  .neg { color: var(--bad); }
  .day { font-size: 13px; font-weight: 600; color: var(--muted); margin: 18px 4px 6px; }
  .list { list-style: none; padding: 0 0 0 14px; margin: 0; }
  .list li + li button { border-top: 1px solid var(--hairline); }
  .list button { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 12px; width: 100%;
                 padding: 12px 14px 12px 0; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .list button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .icon { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .text { flex: 1; min-width: 0; display: grid; }
  .title, .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag { background: var(--surface-2); border-radius: 6px; padding: 0 5px; margin-left: 4px; font-size: 11px; color: var(--ink-2); }
  .amount { text-align: right; font-weight: 600; white-space: nowrap; display: grid; }
  .amount.pos { color: var(--good); }
  .eur { font-weight: 400; }
  .muted-row .title, .muted-row .amount { color: var(--muted); }
  .muted-row .amount { font-weight: 400; }
  .more { display: block; width: 100%; margin: 12px 0; padding: 12px; border: 0; border-radius: 12px;
          background: var(--surface); box-shadow: 0 0 0 1px var(--border); color: var(--accent); cursor: pointer; }
  .reloading { opacity: .6; }
</style>
