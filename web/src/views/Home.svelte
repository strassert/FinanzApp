<script lang="ts">
  import { api, query, type Overview, type Period, type Recurring, type Summary } from "../lib/api";
  import { day, eur, percent, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import { go, route } from "../lib/router.svelte";
  import BarList from "../components/BarList.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import BalanceSummary from "../components/BalanceSummary.svelte";
  import NetWorthCard from "../components/NetWorthCard.svelte";

  let { onerror }: { onerror: (e: unknown) => void } = $props();

  let data = $state<Overview | null>(null);
  let cards = $state<number[]>([]);          // F4: card selection
  let summary = $state<Summary | null>(null);
  let loading = $state(false);
  let fixed = $state<Recurring | null>(null);
  let periods = $state<Period[]>([]);          // newest first
  let currentKey = $state("");

  // month shown on the home screen: #/?period=2026-08, current month without
  const periodKey = $derived(route.params.get("period") ?? "");
  const shownKey = $derived(periodKey || currentKey);
  const shownIdx = $derived(periods.findIndex((p) => p.key === shownKey));
  const isCurrent = $derived(!periodKey || periodKey === currentKey);

  async function loadPeriods() {
    try {
      const p = await api.get<{ current: Period; items: Period[] }>("/api/periods");
      periods = p.items;
      currentKey = p.current.key;
    } catch (e) {
      onerror(e);
    }
  }
  loadPeriods();

  function step(delta: number) {
    const target = periods[shownIdx - delta];
    if (target) go("", target.key === currentKey ? {} : { period: target.key });
  }

  async function load() {
    loading = true;
    try {
      data = await api.get<Overview>("/api/overview" + query({ accounts: cards, period: periodKey || undefined }));
    } catch (e) {
      onerror(e);
    } finally {
      loading = false;
    }
  }

  async function loadSummary() {
    try {
      summary = await api.get<Summary>("/api/summary");
    } catch (e) {
      onerror(e);
    }
  }
  loadSummary();

  async function loadFixed() {
    try {
      fixed = await api.get<Recurring>("/api/recurring");
    } catch (e) {
      onerror(e);
    }
  }
  loadFixed();

  $effect(() => { void cards; void periodKey; load(); });

  function toggleCard(id: number | null) {
    cards = id === null ? [] : cards.includes(id) ? cards.filter((c) => c !== id) : [...cards, id];
  }

  const compare = $derived(data ? data.spent - data.previous.spent_same_day : 0);
  const nextFixed = $derived(fixed ? [...fixed.items].filter((i) => i.role === "expense")
    .sort((a, b) => a.next_date.localeCompare(b.next_date)).slice(0, 3) : []);
</script>

{#if isCurrent && summary}
  <BalanceSummary data={summary} />
  <NetWorthCard data={summary.net_worth} {onerror} />
{/if}

{#if data}
  <div class:reloading={loading}>
    <!-- Dieser Monat -->
    <section class="card hero" aria-labelledby="h-spent">
      <h2 id="h-spent">Dieser Monat</h2>
      <div class="period">
        <button class="nav" aria-label="Vorheriger Monat" disabled={shownIdx < 0 || shownIdx >= periods.length - 1}
                onclick={() => step(-1)}>‹</button>
        <span class="small">{data.period.label}</span>
        <button class="nav" aria-label="Nächster Monat" disabled={shownIdx <= 0} onclick={() => step(1)}>›</button>
        {#if !isCurrent}<button class="today small" onclick={() => go("")}>Aktueller Monat</button>{/if}
      </div>
      <div class="label small">Ausgegeben{cards.length ? " (Auswahl)" : ""}</div>
      <div class="big num">{eur(data.spent)}</div>
      <div class="cmp small">
        {#if data.previous.spent_same_day}
          <span class:more={compare > 0} class:less={compare <= 0}>
            {compare > 0 ? "▲" : "▼"} {eur(Math.abs(compare))}
          </span>
          <span class="muted">{compare > 0 ? "mehr" : "weniger"} als im {data.previous.period.label.split(" ")[0]}{isCurrent ? " bis zum selben Tag" : ""}</span>
        {/if}
      </div>
      <dl class="figures">
        <div><dt>Einnahmen</dt><dd class="num">{eur(data.income)}</dd></div>
        <div><dt>Sparquote</dt><dd class="num">{percent(data.savings_rate)}</dd></div>
      </dl>
      {#if data.cards.length > 1}
        <div class="chips" role="group" aria-label="Karten auswählen">
          <button class="chip" aria-pressed={cards.length === 0} onclick={() => toggleCard(null)}>Alle</button>
          {#each data.cards as c (c.id)}
            <button class="chip" aria-pressed={cards.includes(c.id)} onclick={() => toggleCard(c.id)}>
              <span class="dot" style:background={slotVar(c.color_slot)}></span>{c.name}
            </button>
          {/each}
        </div>
      {/if}
      {#if data.pending || data.not_converted}
        <p class="small muted note">
          {#if data.pending}{data.pending} vorgemerkt{/if}{#if data.pending && data.not_converted} · {/if}{#if data.not_converted}{data.not_converted} nicht umgerechnet{/if}
        </p>
      {/if}
    </section>

    <!-- 2. Kategorien -->
    <section class="card">
      <h2>Kategorien</h2>
      <BarList items={data.categories.map((c) => ({ id: c.id, label: c.name, amount: c.amount, slot: c.color_slot,
                                                     average: c.average }))}
               onselect={(id) => go("umsaetze", { period: data!.period.key, kategorie: id ?? undefined })} />
      {#if data.average_periods}
        <p class="small muted legend"><span class="tick" aria-hidden="true"></span>Ø = Durchschnitt pro Monat {data.average_periods === 1 ? "des letzten Monats" : `der letzten ${data.average_periods} Monate`}</p>
      {/if}
    </section>

    <!-- Fixkosten -->
    {#if fixed?.items.length}
      <section class="card">
        <a class="more-link" href="#/fixkosten">
          <h2>Fixkosten</h2>
          <span class="small muted">Alle ›</span>
        </a>
        <div class="fixed-total"><span class="num">{eur(fixed.monthly_expense)}</span><span class="small muted">pro Monat</span></div>
        <ul class="accounts">
          {#each nextFixed as i (i.key + i.amount)}
            <li>
              <span class="when small muted">{day(i.next_date)}</span>
              <span class="name">{i.name}</span>
              <span class="num">{signed(i.amount)}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <!-- 3. nach Karte -->
    {#if data.cards.length}
      <section class="card">
        <h2>Nach Karte und Konto</h2>
        <BarList foldOthers={false}
                 items={data.cards.map((c) => ({ id: c.id, label: c.name, amount: c.amount, slot: c.color_slot }))}
                 onselect={(id) => go("umsaetze", { period: data!.period.key, konto: id ?? undefined })} />
      </section>
    {/if}

    <!-- 4. 12-Monats-Trend -->
    <section class="card">
      <h2>12 Monate</h2>
      <TrendChart points={data.trend} current={data.period.key} />
    </section>
  </div>
{:else}
  <div class="card skeleton">Lade …</div>
{/if}

<style>
  .reloading { opacity: .6; transition: opacity .2s; }
  .hero .period { display: flex; align-items: center; gap: 8px; margin: -4px 0 8px; color: var(--ink-2); }
  .hero .period span { min-width: 7.5em; text-align: center; font-weight: 600; }
  .nav { border: 0; background: var(--surface-2); color: var(--ink); width: 32px; height: 28px; border-radius: 8px;
         cursor: pointer; font-size: 18px; line-height: 1; }
  .nav:disabled { opacity: .35; cursor: default; }
  .nav:focus-visible, .today:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .today { all: unset; margin-left: auto; color: var(--accent); cursor: pointer; }
  .hero .label { color: var(--ink-2); }
  .big { font-size: 34px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.1; margin: 2px 0 6px;
         font-variant-numeric: normal; }
  .cmp { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }
  .more { color: var(--bad); font-weight: 600; }
  .less { color: var(--good); font-weight: 600; }
  .figures { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 0 0 14px;
             padding-top: 12px; border-top: 1px solid var(--hairline); }
  .figures dt { font-size: 12px; color: var(--muted); }
  .figures dd { margin: 2px 0 0; font-weight: 600; font-size: 17px; }
  .note { margin: 10px 0 0; }
  .accounts { list-style: none; margin: 0; padding: 0; }
  .accounts li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .accounts li:first-child { border-top: 0; padding-top: 0; }
  .accounts .name { flex: 1; min-width: 0; }
  .skeleton { color: var(--muted); }
  .more-link { display: flex; justify-content: space-between; align-items: baseline; color: inherit; text-decoration: none; }
  .fixed-total { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; }
  .fixed-total .num { font-size: 24px; font-weight: 650; }
  .when { width: 52px; flex: none; }
  .legend { display: flex; align-items: center; gap: 8px; margin: 14px 0 0; }
  .legend .tick { width: 2px; height: 14px; border-radius: 1px; background: var(--ink); flex: none; }
</style>
