<script lang="ts">
  // Single series (net worth): 2px line, 10% wash, crosshair readout, end label.
  import type { NetWorthPoint } from "../lib/api";
  import { axis, day, dayLongFmt, eur, monthYear } from "../lib/format";

  let { points }: { points: NetWorthPoint[] } = $props();
  let width = $state(340);
  let active = $state<number | null>(null);

  const H = 170, top = 10, bottom = 22, left = 48, right = 10;
  const plotH = H - top - bottom;
  const values = $derived(points.map((p) => p.value));
  const lo = $derived(Math.min(...values));
  const hi = $derived(Math.max(...values));
  // round the axis to clean steps (e.g. 20.000 / 30.000 / 40.000)
  const step = $derived.by(() => {
    const raw = Math.max(100, (hi - lo) / 2);
    const mag = 10 ** Math.floor(Math.log10(raw));
    return ([1, 2, 2.5, 5, 10].map((m) => m * mag).find((c) => c >= raw) ?? raw);
  });
  const yMin = $derived(Math.floor(lo / step) * step);
  const yMax = $derived(Math.max(yMin + step, Math.ceil(hi / step) * step));
  const x = (i: number) => left + (i / Math.max(1, points.length - 1)) * (width - left - right);
  const y = (v: number) => top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const path = $derived(points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(""));
  const area = $derived(path ? `${path}L${x(points.length - 1)},${top + plotH}L${x(0)},${top + plotH}Z` : "");
  const ticks = $derived(Array.from({ length: Math.round((yMax - yMin) / step) + 1 }, (_, i) => yMin + i * step));
  const long = $derived(points.length > 1 && Date.parse(points[points.length - 1].date) - Date.parse(points[0].date) > 100 * 86400000);
  const shown = $derived(active ?? points.length - 1);
  const first = $derived(points[0]?.value ?? 0);

  function pick(e: PointerEvent) {
    const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
    const rel = (e.clientX - rect.left - left) / (width - left - right);
    active = Math.max(0, Math.min(points.length - 1, Math.round(rel * (points.length - 1))));
  }
</script>

{#if points.length}
  <div class="readout" aria-live="polite">
    <span class="value">{eur(points[shown].value)}</span>
    <span class="small muted">{active === null ? "heute" : dayLongFmt(points[shown].date)}</span>
    {#if active === null && points.length > 1}
      {@const diff = points[shown].value - first}
      <span class="small delta" class:up={diff >= 0}>{diff >= 0 ? "▲" : "▼"} {eur(Math.abs(diff))} im Zeitraum</span>
    {/if}
  </div>
  <div class="wrap" bind:clientWidth={width}>
    <svg {width} height={H} role="img" aria-label="Vermögensverlauf" onpointermove={pick} onpointerdown={pick}
         onpointerleave={() => (active = null)}>
      {#each ticks as t}
        <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} class="grid" />
        <text x={left - 6} y={y(t) + 4} text-anchor="end" class="tick">{axis(t)}</text>
      {/each}
      <path d={area} fill="var(--s1)" opacity="0.10" />
      <path d={path} fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      {#if active !== null}
        <line x1={x(active)} x2={x(active)} y1={top} y2={top + plotH} class="cross" />
      {/if}
      <circle cx={x(shown)} cy={y(points[shown].value)} r="4" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" />
      <text x={left} y={H - 4} class="tick">{long ? monthYear(points[0].date) : day(points[0].date)}</text>
      <text x={width - right} y={H - 4} text-anchor="end" class="tick">{long ? monthYear(points[points.length - 1].date) : day(points[points.length - 1].date)}</text>
    </svg>
  </div>
  {#if points[shown].not_converted}
    <p class="small muted">{points[shown].not_converted} Konto ohne Wechselkurs nicht enthalten.</p>
  {/if}
{/if}

<style>
  .wrap { width: 100%; touch-action: pan-y; }
  svg { display: block; }
  .grid { stroke: var(--hairline); stroke-width: 1; }
  .cross { stroke: var(--baseline); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .readout { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
  .value { font-size: 22px; font-weight: 600; }
  .delta { color: var(--bad); }
  .delta.up { color: var(--good); }
</style>
