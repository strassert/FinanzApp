<script lang="ts">
  import { api, query, type Explore, type SankeyNode } from "../lib/api";
  import { eur, monthShort } from "../lib/format";
  import { hasOwnColor, slotVar } from "../lib/colors";
  import Sankey from "../components/Sankey.svelte";

  let { onerror }: { onerror: (e: unknown) => void } = $props();

  let data = $state<Explore | null>(null);
  let from = $state(0);          // index into timeline (inclusive)
  let to = $state(0);
  let ready = false;
  let focus = $state<SankeyNode | null>(null);
  let loading = $state(false);

  async function load() {
    loading = true;
    try {
      const t = data?.timeline;
      const params = t && ready ? { from: t[from].start, to: t[to].end } : {};
      const next = await api.get<Explore>("/api/explore" + query(params));
      if (!ready) {
        const idx = next.timeline.findIndex((p) => p.start === next.sankey.start);
        from = to = idx >= 0 ? idx : Math.max(0, next.timeline.length - 2);
        ready = true;
      }
      data = next;
      focus = null;
    } catch (e) {
      onerror(e);
    } finally {
      loading = false;
    }
  }
  load();

  // --- timeline: range slider, drag to shift, tap selects one month; reload on release
  let width = $state(340);
  let drag: { x: number; from: number; to: number } | null = null;
  const n = $derived(data?.timeline.length ?? 0);
  const band = $derived(width / Math.max(1, n));
  const maxSpent = $derived(Math.max(1, ...(data?.timeline ?? []).map((p) => p.spent)));

  function onDown(e: PointerEvent) {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    drag = { x: e.clientX, from, to };
  }
  function onMove(e: PointerEvent) {
    if (!drag) return;
    const shift = Math.round((e.clientX - drag.x) / band);
    const span = drag.to - drag.from;
    const f = Math.max(0, Math.min(n - 1 - span, drag.from + shift));
    from = f;
    to = f + span;
  }
  function onUp(e: PointerEvent) {
    if (!drag) return;
    const moved = Math.abs(e.clientX - drag.x) > 4;
    if (!moved) {
      const rect = (e.currentTarget as Element).getBoundingClientRect();
      const i = Math.max(0, Math.min(n - 1, Math.floor((e.clientX - rect.left) / band)));
      from = to = i;
    }
    drag = null;
    load();
  }

  const label = $derived.by(() => {
    const t = data?.timeline;
    if (!t?.length) return "";
    return from === to ? t[from].label : `${t[from].label} – ${t[to].label}`;
  });
  const focusLinks = $derived.by(() => {
    if (!focus || !data) return [];
    const names = new Map(data.sankey.nodes.map((x) => [x.id, x]));
    const out = data.sankey.links.filter((l) => l.source === focus!.id || l.target === focus!.id);
    return out.map((l) => ({ other: names.get(l.source === focus!.id ? l.target : l.source)!, value: l.value,
                             dir: l.source === focus!.id ? "→" : "←" })).sort((a, b) => b.value - a.value);
  });
</script>

{#if data}
  <section class="card" class:reloading={loading}>
    <div class="head">
      <strong>{label}</strong>
      <span class="small muted">Einnahmen {eur(data.sankey.income)} · Ausgaben {eur(data.sankey.spent)}</span>
    </div>
    <Sankey nodes={data.sankey.nodes} links={data.sankey.links} onselect={(node) => (focus = node)} />
    <p class="small muted hint">Die Bankdaten sagen nicht, welches Geld was bezahlt hat: Die Einnahmen werden
      anteilig auf die Konten verteilt, auf denen ausgegeben wurde. Umbuchungen sind nicht enthalten.
      Tippe auf einen Knoten für die Einzelwerte.</p>
  </section>

  {#if focus}
    <section class="card">
      <h2>{focus.label}</h2>
      <ul class="rows">
        {#each focusLinks as f}
          <li><span class="swatch" style:background={f.other.kind === "category" || f.other.kind === "account"
              ? (hasOwnColor(f.other.color_slot) ? slotVar(f.other.color_slot) : "var(--other)") : "var(--s1)"}></span>
            <span class="grow">{f.dir} {f.other.label}</span><span class="num">{eur(f.value)}</span></li>
        {/each}
      </ul>
    </section>
  {/if}

  <section class="card">
    <h2>Zeitraum</h2>
    <p class="small muted">Ziehen verschiebt den Bereich, Antippen wählt einen Monat.</p>
    <div class="timeline" bind:clientWidth={width} role="slider" tabindex="0" aria-label="Zeitraum wählen"
         aria-valuemin={0} aria-valuemax={n - 1} aria-valuenow={to} aria-valuetext={label}
         onpointerdown={onDown} onpointermove={onMove} onpointerup={onUp}
         onkeydown={(e) => { if (e.key === "ArrowLeft" && from > 0) { from--; to--; load(); }
                             if (e.key === "ArrowRight" && to < n - 1) { from++; to++; load(); } }}>
      <svg {width} height="84">
        <rect x={from * band} y="0" width={(to - from + 1) * band} height="84" rx="6" fill="var(--accent-wash)" />
        {#each data.timeline as p, i (p.key)}
          {@const h = Math.max(2, (p.spent / maxSpent) * 58)}
          <rect x={i * band + band * 0.2} y={62 - h} width={Math.max(2, band * 0.6)} height={h} rx="2"
                fill="var(--s2)" opacity={i >= from && i <= to ? 1 : 0.35} />
          {#if n <= 14 || p.key.endsWith("-01") || i === n - 1}
            <text x={i === n - 1 ? width : i * band + band / 2} y="78" text-anchor={i === n - 1 ? "end" : "middle"}
                  class="tick">{p.key.endsWith("-01") ? p.key.slice(0, 4) : monthShort(p.key)}</text>
          {/if}
        {/each}
      </svg>
    </div>
    <div class="range">
      <label class="small muted">Von
        <input type="range" min="0" max={n - 1} bind:value={from} onchange={() => { if (from > to) to = from; load(); }} /></label>
      <label class="small muted">Bis
        <input type="range" min="0" max={n - 1} bind:value={to} onchange={() => { if (to < from) from = to; load(); }} /></label>
    </div>
  </section>
{:else}
  <div class="card muted">Lade …</div>
{/if}

<style>
  .head { display: grid; gap: 2px; margin-bottom: 12px; }
  .hint { margin: 12px 0 0; }
  .reloading { opacity: .6; }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; gap: 10px; align-items: center; padding: 8px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; }
  .grow { flex: 1; }
  .timeline { touch-action: none; cursor: grab; user-select: none; -webkit-user-select: none; }
  .timeline svg { display: block; }
  .tick { fill: var(--muted); font-size: 10px; }
  .range { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 8px; }
  .range label { display: grid; gap: 2px; }
  input[type="range"] { width: 100%; accent-color: var(--accent); }
  p { margin: 0 0 8px; }
</style>
