<script lang="ts">
  // Income -> pot -> accounts -> categories. Colour follows account/category.
  // Categories without an own colour slot fold into "Weitere" (grey).
  import type { SankeyLink, SankeyNode } from "../lib/api";
  import { eur } from "../lib/format";
  import { hasOwnColor, slotVar } from "../lib/colors";

  let { nodes, links, onselect }: {
    nodes: SankeyNode[]; links: SankeyLink[]; onselect: (node: SankeyNode | null) => void;
  } = $props();
  let width = $state(340);
  let selected = $state<string | null>(null);

  const H = 360, GAP = 6, NODE_W = 10;

  const folded = $derived.by(() => {
    const fold = new Set(nodes.filter((n) => n.kind === "category" && !hasOwnColor(n.color_slot)).map((n) => n.id));
    const ns = nodes.filter((n) => !fold.has(n.id));
    if (fold.size) ns.push({ id: "cat:other", label: `Weitere (${fold.size})`, column: 3, kind: "category", color_slot: null });
    const merged = new Map<string, SankeyLink>();
    for (const l of links) {
      const target = fold.has(l.target) ? "cat:other" : l.target;
      const key = `${l.source}>${target}`;
      const m = merged.get(key);
      if (m) m.value += l.value;
      else merged.set(key, { source: l.source, target, value: l.value });
    }
    return { nodes: ns, links: [...merged.values()] };
  });

  const layout = $derived.by(() => {
    const { nodes: ns, links: ls } = folded;
    const value = new Map<string, number>();
    for (const n of ns) {
      const out = ls.filter((l) => l.source === n.id).reduce((s, l) => s + l.value, 0);
      const inn = ls.filter((l) => l.target === n.id).reduce((s, l) => s + l.value, 0);
      value.set(n.id, Math.max(out, inn));
    }
    const columns = [0, 1, 2, 3].map((c) => ns.filter((n) => n.column === c)
      .sort((a, b) => (a.kind === "left" || a.kind === "savings" ? 1 : 0) - (b.kind === "left" || b.kind === "savings" ? 1 : 0)
        || (value.get(b.id) ?? 0) - (value.get(a.id) ?? 0)));
    const k = Math.min(...columns.filter((c) => c.length).map((col) =>
      (H - GAP * (col.length - 1)) / Math.max(1, col.reduce((s, n) => s + (value.get(n.id) ?? 0), 0))));
    const xs = [0, 0.3, 0.55, 1].map((f) => f * (width - NODE_W));
    const pos = new Map<string, { x: number; y: number; h: number }>();
    for (const [c, col] of columns.entries()) {
      const total = col.reduce((s, n) => s + (value.get(n.id) ?? 0) * k, 0) + GAP * (col.length - 1);
      let y = (H - total) / 2;
      for (const n of col) {
        const h = Math.max(1, (value.get(n.id) ?? 0) * k);
        pos.set(n.id, { x: xs[c], y, h });
        y += h + GAP;
      }
    }
    const outY = new Map<string, number>(), inY = new Map<string, number>();
    const sorted = [...ls].sort((a, b) => (pos.get(a.target)?.y ?? 0) - (pos.get(b.target)?.y ?? 0));
    const paths = sorted.map((l) => {
      const s = pos.get(l.source)!, t = pos.get(l.target)!;
      const h = l.value * k;
      const sy = s.y + (outY.get(l.source) ?? 0), ty = t.y + (inY.get(l.target) ?? 0);
      outY.set(l.source, (outY.get(l.source) ?? 0) + h);
      inY.set(l.target, (inY.get(l.target) ?? 0) + h);
      const x0 = s.x + NODE_W, x1 = t.x, mx = (x0 + x1) / 2;
      const d = `M${x0},${sy}C${mx},${sy} ${mx},${ty} ${x1},${ty}L${x1},${ty + h}C${mx},${ty + h} ${mx},${sy + h} ${x0},${sy + h}Z`;
      return { ...l, d };
    });
    return { pos, paths, value };
  });

  function color(n: SankeyNode | undefined): string {
    if (!n) return "var(--other)";
    if (n.kind === "income" || n.kind === "pot") return "var(--s1)";
    if (n.kind === "left") return "var(--accent)";
    if (n.kind === "savings") return "var(--copper)";
    return slotVar(n.color_slot);
  }
  const byId = $derived(new Map(folded.nodes.map((n) => [n.id, n])));

  function pick(n: SankeyNode) {
    selected = selected === n.id ? null : n.id;
    onselect(selected ? n : null);
  }
</script>

<div class="wrap" bind:clientWidth={width}>
  <svg {width} height={H} role="img" aria-label="Geldflüsse von Einnahmen über Konten zu Kategorien">
    {#each layout.paths as p}
      {@const target = byId.get(p.target)}
      <path d={p.d} fill={color(target?.kind === "pot" ? byId.get(p.source) : target)}
            opacity={selected && p.source !== selected && p.target !== selected ? 0.08 : 0.28} />
    {/each}
    {#each folded.nodes as n (n.id)}
      {@const q = layout.pos.get(n.id)!}
      {@const left = n.column >= 2}
      <g role="button" tabindex="0" aria-label="{n.label}: {eur(layout.value.get(n.id) ?? 0)}"
         onclick={() => pick(n)} onkeydown={(e) => e.key === "Enter" && pick(n)}>
        <rect x={q.x - 4} y={q.y - 2} width={NODE_W + 8} height={q.h + 4} fill="transparent" />
        <rect x={q.x} y={q.y} width={NODE_W} height={q.h} rx="2" fill={color(n)}
              opacity={selected && selected !== n.id ? 0.4 : 1} />
        {#if q.h >= 11 || n.column === 1}
          {@const max = n.column === 2 ? 13 : 16}
          <text x={left ? q.x - 5 : q.x + NODE_W + 5} y={q.y + q.h / 2 + 4} text-anchor={left ? "end" : "start"}
                class="label" class:strong={selected === n.id}>{n.label.length > max ? n.label.slice(0, max - 1) + "…" : n.label}</text>
        {/if}
      </g>
    {/each}
  </svg>
</div>

<style>
  .wrap { width: 100%; }
  svg { display: block; overflow: visible; }
  g { cursor: pointer; outline: none; }
  .label { fill: var(--ink); font-size: 11px; paint-order: stroke; stroke: var(--surface); stroke-width: 3px; stroke-linejoin: round; }
  .label.strong { font-weight: 700; }
</style>
