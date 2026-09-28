<script lang="ts">
  // Spending as columns, income as a line, on ONE axis. Tap a column for both values.
  import type { TrendPoint } from "../lib/api";
  import { axis, eur, monthShort } from "../lib/format";

  let { points, current }: { points: TrendPoint[]; current: string } = $props();
  let width = $state(340);
  let active = $state<number | null>(null);

  const H = 180, top = 12, bottom = 24, left = 44, right = 8;
  const plotH = H - top - bottom;
  const max = $derived(Math.max(1, ...points.map((p) => Math.max(p.spent, p.income))));
  const niceMax = $derived.by(() => {
    const step = 10 ** Math.floor(Math.log10(max)) / 2;
    return Math.ceil(max / step) * step;
  });
  const ticks = $derived([0, niceMax / 2, niceMax]);
  const band = $derived((width - left - right) / Math.max(1, points.length));
  const barW = $derived(Math.min(24, band * 0.6));
  const y = (v: number) => top + plotH - (v / niceMax) * plotH;
  const cx = (i: number) => left + band * i + band / 2;
  const linePath = $derived(points.map((p, i) => `${i ? "L" : "M"}${cx(i)},${y(p.income)}`).join(""));
  const shown = $derived(active ?? points.length - 1);
</script>

<div class="legend small">
  <span><span class="swatch" style:background="var(--s2)"></span>Ausgaben</span>
  <span><span class="key"></span>Einnahmen</span>
</div>
<div class="readout small" aria-live="polite">
  {#if points[shown]}
    <strong>{points[shown].label}</strong>
    <span class="num"><span class="swatch" style:background="var(--s2)"></span>{eur(points[shown].spent)}</span>
    <span class="num"><span class="key"></span>{eur(points[shown].income)}</span>
  {/if}
</div>
<div class="wrap" bind:clientWidth={width}>
  <svg {width} height={H} role="img" aria-label="Ausgaben und Einnahmen der letzten {points.length} Monate">
    {#each ticks as t}
      <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} class={t === 0 ? "base" : "grid"} />
      <text x={left - 6} y={y(t) + 4} text-anchor="end" class="tick">{axis(t)}</text>
    {/each}
    {#each points as p, i (p.key)}
      {@const h = Math.max(0, y(0) - y(p.spent))}
      <g class="col" class:dim={active !== null && active !== i}>
        {#if h > 0}
          <path d="M{cx(i) - barW / 2},{y(0)} v{-Math.max(0, h - 4)} q0,-4 4,-4 h{barW - 8} q4,0 4,4 v{Math.max(0, h - 4)} z"
                fill="var(--s2)" opacity={p.key === current ? 1 : 0.75} />
        {/if}
        <text x={cx(i)} y={H - 6} text-anchor="middle" class="tick" class:cur={p.key === current}>{monthShort(p.key)}</text>
        <rect x={cx(i) - band / 2} y={top} width={band} height={plotH + bottom} fill="transparent"
              role="button" tabindex="0" aria-label="{p.label}: Ausgaben {eur(p.spent)}, Einnahmen {eur(p.income)}"
              onpointerenter={() => (active = i)} onpointerleave={() => (active = null)}
              onclick={() => (active = active === i ? null : i)}
              onfocus={() => (active = i)} onblur={() => (active = null)}
              onkeydown={(e) => e.key === "Enter" && (active = i)} />
      </g>
    {/each}
    <path d={linePath} fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" pointer-events="none" />
    {#each points as p, i (p.key)}
      <circle cx={cx(i)} cy={y(p.income)} r={i === shown ? 4 : 0} fill="var(--s1)" stroke="var(--surface)" stroke-width="2" pointer-events="none" />
    {/each}
  </svg>
</div>

<style>
  .wrap { width: 100%; }
  svg { display: block; overflow: visible; }
  .grid { stroke: var(--hairline); stroke-width: 1; }
  .base { stroke: var(--baseline); stroke-width: 1; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .tick.cur { fill: var(--ink); font-weight: 600; }
  .col { transition: opacity .15s; }
  .col.dim { opacity: .45; }
  rect:focus { outline: none; }
  .legend, .readout { display: flex; gap: 14px; align-items: center; color: var(--ink-2); }
  .legend { margin-bottom: 6px; }
  .legend span, .readout span { display: inline-flex; align-items: center; gap: 6px; }
  .readout { margin-bottom: 8px; min-height: 20px; }
  .readout strong { color: var(--ink); font-weight: 600; }
  .key { width: 14px; height: 2px; background: var(--s1); border-radius: 1px; display: inline-block; }
</style>
