<script lang="ts">
  // Horizontal bars with a labelled row per entry (colour is never the only carrier).
  // Entries without an own colour slot fold into "Weitere" (grey).
  // Optional average per entry: a tick on the bar and a labelled "Ø" amount.
  import { eur } from "../lib/format";
  import { hasOwnColor, slotVar } from "../lib/colors";

  interface Item { id: number; label: string; amount: number; slot: number | null; sub?: string; average?: number | null }
  let { items, onselect, foldOthers = true, limit = 8 }: {
    items: Item[]; onselect?: (id: number | null) => void; foldOthers?: boolean; limit?: number;
  } = $props();

  let expanded = $state(false);

  const rows = $derived.by(() => {
    const positive = items.filter((i) => i.amount > 0);
    if (!foldOthers || expanded) return positive.map((i) => ({ ...i, other: false }));
    const own = positive.filter((i) => hasOwnColor(i.slot)).slice(0, limit);
    const rest = positive.filter((i) => !own.includes(i));
    const out = own.map((i) => ({ ...i, other: false }));
    if (rest.length) {
      const avgs = rest.map((i) => i.average).filter((a): a is number => a != null);
      out.push({ id: -1, label: `Weitere (${rest.length})`, amount: rest.reduce((s, i) => s + i.amount, 0),
                 slot: null, sub: rest.map((r) => r.label).join(", "), other: true,
                 average: avgs.length ? avgs.reduce((s, a) => s + a, 0) : null });
    }
    return out.sort((a, b) => (a.other ? 1 : 0) - (b.other ? 1 : 0) || b.amount - a.amount);
  });
  const max = $derived(Math.max(1, ...rows.map((r) => Math.max(r.amount, r.average ?? 0))));
  const total = $derived(rows.reduce((s, r) => s + r.amount, 0));
</script>

<ul class="bars">
  {#each rows as row (row.id)}
    <li>
      <button type="button" onclick={() => (row.other ? (expanded = true) : onselect?.(row.id))}
              aria-label="{row.label}: {eur(row.amount)}{row.average != null ? `, Durchschnitt ${eur(row.average)}` : ""}">
        <span class="line">
          <span class="swatch" style:background={slotVar(row.slot)}></span>
          <span class="label">{row.label}</span>
          <span class="share muted small num">{Math.round((row.amount / total) * 100)} %</span>
          <span class="amount num">{eur(row.amount)}</span>
        </span>
        <span class="track"><span class="fill" style:width="{(row.amount / max) * 100}%"
              style:background={slotVar(row.slot)}></span>
          {#if row.average != null}<span class="avg" style:left="{(row.average / max) * 100}%"></span>{/if}</span>
        {#if row.average != null}<span class="avg-label muted small num">Ø {eur(row.average)}</span>{/if}
        {#if row.other && row.sub}<span class="sub muted small">{row.sub}</span>{/if}
      </button>
    </li>
  {:else}
    <li class="muted small">Keine Ausgaben in diesem Zeitraum.</li>
  {/each}
</ul>
{#if expanded && foldOthers}
  <button class="less small" type="button" onclick={() => (expanded = false)}>Weniger anzeigen</button>
{/if}

<style>
  .bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
  button { all: unset; display: grid; gap: 6px; width: 100%; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; border-radius: 6px; }
  .line { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .amount { font-weight: 600; }
  .share { min-width: 3ch; text-align: right; }
  .track { position: relative; height: 8px; border-radius: 4px; background: var(--surface-2); }
  .track .fill { border-radius: 4px; }
  .avg { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; border-radius: 1px;
         background: var(--ink); }
  .avg-label { margin-top: -2px; }
  .fill { display: block; height: 100%; border-radius: 0 4px 4px 0; min-width: 4px; }
  .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .less { all: unset; color: var(--accent); cursor: pointer; margin-top: 12px; display: inline-block; }
</style>
