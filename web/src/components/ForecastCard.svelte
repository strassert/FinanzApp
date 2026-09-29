<script lang="ts">
  // Balance forecast until the end of the budget period: one row per account.
  import { api, type Forecast, type ForecastAccount } from "../lib/api";
  import { day, dayLongFmt, eur, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import Sheet from "./Sheet.svelte";

  let { onerror }: { onerror: (e: unknown) => void } = $props();

  let data = $state<Forecast | null>(null);
  let open = $state(false);

  async function load() {
    try {
      data = await api.get<Forecast>("/api/forecast");
    } catch (e) {
      onerror(e);
    }
  }
  load();

  // accounts where something is still expected; the others stay as they are
  const moving = $derived(data?.accounts.filter((a) => a.expected.length || a.pending) ?? []);
  const change = (a: ForecastAccount) => a.forecast - a.balance;
</script>

{#if data && moving.length}
  <section class="card">
    <button class="head" onclick={() => (open = true)}>
      <h2>Kontostand am {day(data.until)}</h2>
      <span class="small muted">Details ›</span>
    </button>
    <ul class="rows">
      {#each moving as a (a.id)}
        <li>
          <span class="dot" style:background={slotVar(a.color_slot)}></span>
          <span class="grow">
            <span class="name">{a.name}</span>
            <span class="small muted">heute {eur(a.balance)} · {change(a) > 0 ? "+" : ""}{eur(change(a))} erwartet</span>
          </span>
          <span class="num strong" class:neg={a.forecast < 0}>{eur(a.forecast)}</span>
        </li>
        {#if a.lowest < 0 && a.forecast >= 0}
          <li class="warn small">Tiefster Stand am {day(a.lowest_date)}: {eur(a.lowest)}</li>
        {/if}
      {/each}
    </ul>
  </section>
{/if}

{#if open && data}
  <Sheet title="Bis {dayLongFmt(data.until)}" onclose={() => (open = false)}>
    <p class="small muted intro">Kontostand heute, dazu vorgemerkte Umsätze und die regelmäßigen Buchungen, die bis dahin noch kommen. Das Gehalt am Beginn des nächsten Zeitraums ist nicht enthalten.</p>
    {#each moving as a (a.id)}
      <section class="card">
        <h2>{a.name}</h2>
        <ul class="rows">
          <li><span class="grow">Heute</span><span class="num">{signed(a.balance)}</span></li>
          {#if a.pending}
            <li><span class="grow">Vorgemerkt</span><span class="num">{signed(a.pending)}</span></li>
          {/if}
          {#each a.expected as e (e.key + e.date)}
            <li>
              <span class="when small muted" class:late={e.overdue}>{e.overdue ? "überfällig" : day(e.date)}</span>
              <span class="grow name">{e.name}</span>
              <span class="num" class:pos={e.amount > 0}>{signed(e.amount)}</span>
            </li>
          {/each}
          <li class="total"><span class="grow">Am {day(data.until)}</span><span class="num" class:neg={a.forecast < 0}>{signed(a.forecast)}</span></li>
        </ul>
      </section>
    {/each}
  </Sheet>
{/if}

<style>
  .head { all: unset; box-sizing: border-box; display: flex; justify-content: space-between; align-items: baseline;
          width: 100%; cursor: pointer; }
  .head:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; padding-top: 0; }
  .rows li.warn { border-top: 0; padding-top: 0; color: var(--bad); padding-left: 20px; }
  .rows .total { font-weight: 600; }
  .grow { flex: 1; min-width: 0; display: grid; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .strong { font-weight: 600; }
  .neg { color: var(--bad); }
  .pos { color: var(--good); }
  .when { width: 64px; flex: none; }
  .late { color: var(--copper); }
  .intro { margin: 0 0 12px; }
</style>
