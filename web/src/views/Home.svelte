<script lang="ts">
  import { api, query, type NetWorthPoint, type Overview } from "../lib/api";
  import { eur, percent } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import { go } from "../lib/router.svelte";
  import BarList from "../components/BarList.svelte";
  import TrendChart from "../components/TrendChart.svelte";
  import LineChart from "../components/LineChart.svelte";

  let { onerror }: { onerror: (e: unknown) => void } = $props();

  let data = $state<Overview | null>(null);
  let cards = $state<number[]>([]);          // F4: card selection
  let range = $state("1J");
  let worth = $state<NetWorthPoint[]>([]);
  let loading = $state(false);

  async function load() {
    loading = true;
    try {
      data = await api.get<Overview>("/api/overview" + query({ accounts: cards }));
    } catch (e) {
      onerror(e);
    } finally {
      loading = false;
    }
  }

  async function loadWorth() {
    try {
      worth = (await api.get<{ points: NetWorthPoint[] }>(`/api/networth?range=${range}`)).points;
    } catch (e) {
      onerror(e);
    }
  }

  $effect(() => { void cards; load(); });
  $effect(() => { void range; loadWorth(); });

  function toggleCard(id: number | null) {
    cards = id === null ? [] : cards.includes(id) ? cards.filter((c) => c !== id) : [...cards, id];
  }

  const compare = $derived(data ? data.spent - data.previous.spent_same_day : 0);
  const accountsTotal = $derived(data ? data.accounts.reduce((s, a) => s + (a.balance_eur ?? 0), 0) : 0);
  const RANGES = ["1M", "3M", "6M", "1J", "3J", "Alles"];
</script>

{#if data}
  <div class:reloading={loading}>
    <!-- 1. Ausgaben -->
    <section class="card hero" aria-labelledby="h-spent">
      <div class="period small muted">{data.period.label}</div>
      <h2 id="h-spent" class="sr-only">Ausgaben</h2>
      <div class="label small">Ausgegeben{cards.length ? " (Auswahl)" : ""}</div>
      <div class="big num">{eur(data.spent)}</div>
      <div class="cmp small">
        {#if data.previous.spent_same_day}
          <span class:more={compare > 0} class:less={compare <= 0}>
            {compare > 0 ? "▲" : "▼"} {eur(Math.abs(compare))}
          </span>
          <span class="muted">{compare > 0 ? "mehr" : "weniger"} als im {data.previous.period.label.split(" ")[0]} bis zum selben Tag</span>
        {/if}
      </div>
      <dl class="figures">
        <div><dt>Einnahmen</dt><dd class="num">{eur(data.income)}</dd></div>
        <div><dt>Sparquote</dt><dd class="num">{percent(data.savings_rate)}</dd></div>
        <div><dt>{data.budget.per_day !== null ? "Übrig pro Tag" : "Übrig"}</dt>
          <dd class="num" class:neg={data.budget.remaining < 0}>
            {data.budget.per_day !== null ? eur(data.budget.per_day) : eur(data.budget.remaining)}</dd>
          {#if data.budget.days_left}<dd class="days">noch {data.budget.days_left} {data.budget.days_left === 1 ? "Tag" : "Tage"}</dd>{/if}</div>
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
      <BarList items={data.categories.map((c) => ({ id: c.id, label: c.name, amount: c.amount, slot: c.color_slot }))}
               onselect={(id) => go("umsaetze", { period: data!.period.key, kategorie: id ?? undefined })} />
    </section>

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

    <!-- 5. Vermögensverlauf -->
    <section class="card">
      <h2>Vermögen</h2>
      <div class="chips ranges" role="group" aria-label="Zeitraum">
        {#each RANGES as r}
          <button class="chip" aria-pressed={range === r} onclick={() => (range = r)}>{r}</button>
        {/each}
      </div>
      <LineChart points={worth} />
    </section>

    <!-- 6. Konten -->
    <section class="card">
      <h2>Konten</h2>
      <ul class="accounts">
        {#each data.accounts as a (a.id)}
          <li>
            <span class="dot" style:background={slotVar(a.color_slot)}></span>
            <span class="name">{a.name}{#if a.iban}<span class="small muted"> · {a.iban.slice(-4)}</span>{/if}</span>
            <span class="num" class:neg={(a.balance ?? 0) < 0}>
              {#if a.currency !== "EUR" && a.balance !== null}<span class="small muted">{(a.balance / 100).toLocaleString("de-AT", { style: "currency", currency: a.currency })} · </span>{/if}{eur(a.balance_eur)}
            </span>
          </li>
        {/each}
        <li class="total"><span class="name">Gesamt</span><span class="num">{eur(accountsTotal)}</span></li>
      </ul>
    </section>
  </div>
{:else}
  <div class="card skeleton">Lade …</div>
{/if}

<style>
  .reloading { opacity: .6; transition: opacity .2s; }
  .hero .period { margin-bottom: 8px; }
  .hero .label { color: var(--ink-2); }
  .big { font-size: 48px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.1; margin: 2px 0 6px;
         font-variant-numeric: normal; }
  .cmp { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }
  .more { color: var(--bad); font-weight: 600; }
  .less { color: var(--good); font-weight: 600; }
  .figures { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 0 14px;
             padding-top: 12px; border-top: 1px solid var(--hairline); }
  .figures dt { font-size: 12px; color: var(--muted); }
  .figures dd { margin: 2px 0 0; font-weight: 600; font-size: 17px; }
  .figures .days { font-size: 12px; font-weight: 400; color: var(--muted); margin-top: 0; }
  .neg { color: var(--bad); }
  .note { margin: 10px 0 0; }
  .ranges { margin-bottom: 12px; }
  .accounts { list-style: none; margin: 0; padding: 0; }
  .accounts li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .accounts li:first-child { border-top: 0; padding-top: 0; }
  .accounts .name { flex: 1; min-width: 0; }
  .accounts .total { font-weight: 600; }
  .skeleton { color: var(--muted); }
</style>
