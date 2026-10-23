<script lang="ts">
  // Net worth: total, split by kind (each part opens to its accounts), and the history line.
  import { api, type NetWorthPoint, type Summary } from "../lib/api";
  import { eur } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import LineChart from "./LineChart.svelte";

  let { data, onerror }: { data: Summary["net_worth"]; onerror: (e: unknown) => void } = $props();

  let range = $state("1J");
  let worth = $state<NetWorthPoint[]>([]);
  let open = $state<string | null>(null);
  const RANGES = ["1M", "3M", "6M", "1J", "3J", "Alles"];

  async function loadWorth() {
    try {
      worth = (await api.get<{ points: NetWorthPoint[] }>(`/api/networth?range=${range}`)).points;
    } catch (e) {
      onerror(e);
    }
  }
  $effect(() => { void range; loadWorth(); });
</script>

<section class="card" aria-labelledby="h-worth">
  <h2 id="h-worth">Vermögen</h2>
  <div class="total num">{eur(data.total)}</div>
  <ul class="parts">
    {#each data.parts as p (p.key)}
      <li>
        <button class="part" aria-expanded={open === p.key} onclick={() => (open = open === p.key ? null : p.key)}>
          <span class="label">{p.label}</span>
          <span class="num" class:neg={p.amount < 0}>{eur(p.amount)}</span>
          <span class="chev muted" aria-hidden="true">{open === p.key ? "▴" : "▾"}</span>
        </button>
        {#if open === p.key}
          <ul class="accs small">
            {#each p.accounts as a (a.id)}
              <li><span class="dot" style:background={slotVar(a.color_slot)}></span><span class="grow">{a.name}</span>
                <span class="num" class:neg={a.amount < 0}>{eur(a.amount)}</span></li>
            {/each}
          </ul>
        {/if}
      </li>
    {/each}
  </ul>
  {#if data.not_converted}
    <p class="small muted">{data.not_converted} Konto ohne Wechselkurs nicht enthalten.</p>
  {/if}

  <h3 class="small">Verlauf</h3>
  <div class="chips ranges" role="group" aria-label="Zeitraum">
    {#each RANGES as r}
      <button class="chip" aria-pressed={range === r} onclick={() => (range = r)}>{r}</button>
    {/each}
  </div>
  <LineChart points={worth} />
</section>

<style>
  .total { font-size: 32px; font-weight: 650; letter-spacing: -0.01em; margin-bottom: 8px; font-variant-numeric: normal; }
  .parts { list-style: none; margin: 0; padding: 0; }
  .parts > li { border-top: 1px solid var(--hairline); }
  .part { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 10px; width: 100%;
          padding: 10px 0; cursor: pointer; }
  .part:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
  .label { flex: 1; }
  .part .num { font-weight: 600; }
  .chev { width: 12px; text-align: center; }
  .accs { list-style: none; margin: 0 0 10px; padding: 0 0 0 4px; display: grid; gap: 6px; color: var(--ink-2); }
  .accs li { display: flex; align-items: center; gap: 8px; }
  .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .neg { color: var(--bad); }
  h3 { margin: 18px 0 8px; font-weight: 600; color: var(--muted); }
  .ranges { margin-bottom: 12px; }
</style>
