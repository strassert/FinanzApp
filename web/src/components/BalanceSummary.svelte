<script lang="ts">
  // "What do I have, what still goes off, what is left until the salary."
  import type { Summary } from "../lib/api";
  import { day, eur, eurCents, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";

  let { data }: { data: Summary } = $props();

  const daysLeft = $derived(Math.max(1, Math.round((Date.parse(data.until) - Date.parse(data.today)) / 86400000) + 1));
  const perDay = $derived(data.available > 0 ? Math.floor(data.available / daysLeft) : null);
  // bar: today's balance split into free (= available) and committed (the rest)
  const free = $derived(Math.min(data.balance, Math.max(0, data.available)));
  const committed = $derived(data.balance - free);
  const freeShare = $derived(data.balance > 0 ? free / data.balance : 0);
  const untilLabel = $derived(data.salary ? `bis zum Gehalt am ${day(data.salary.date)}` : `bis ${day(data.until)}`);

  function lineLink(kind: string): string | undefined {
    return kind === "fixed" || kind === "income" ? "#/fixkosten" : kind === "card" ? "#/konten" : undefined;
  }
</script>

<section class="card summary" aria-labelledby="h-now">
  <h2 id="h-now">Auf deinen Konten</h2>
  <div class="big num">{eur(data.balance)}</div>
  {#if data.accounts.length > 1}
    <ul class="accs small">
      {#each data.accounts as a (a.id)}
        <li><span class="dot" style:background={slotVar(a.color_slot)}></span>{a.name}
          <span class="num muted">{eur(a.balance)}</span></li>
      {/each}
    </ul>
  {/if}

  {#if data.balance > 0}
    <div class="bar" role="img"
         aria-label="{eur(committed)} verplant, {eur(free)} frei">
      <span class="free" style:width="{freeShare * 100}%"></span>
      <span class="planned" style:width="{(1 - freeShare) * 100}%"></span>
    </div>
    <div class="legend small">
      <span><span class="swatch free"></span>frei {eur(free)}</span>
      <span><span class="swatch planned"></span>verplant {eur(committed)}</span>
    </div>
  {/if}

  <h3 class="small">Geht noch weg {untilLabel}</h3>
  {#if data.lines.length}
    <ul class="lines">
      {#each data.lines as l, i (i)}
        {@const href = lineLink(l.kind)}
        <li>
          <span class="when small muted" class:late={l.overdue}>
            {l.kind === "pending" ? "offen" : l.overdue ? "überfällig" : l.date ? day(l.date) : ""}</span>
          {#if href}<a class="name" {href}>{l.label}</a>{:else}<span class="name">{l.label}</span>{/if}
          <span class="num" class:pos={l.amount > 0}>{signed(l.amount)}</span>
        </li>
        {#if l.kind === "card"}
          <li class="hint small muted">
            {[l.pending ? `inkl. ${eurCents(l.pending)} noch vorgemerkt.` : "",
              data.salary && l.date && l.date > data.salary.date
                ? "Abgebucht erst nach dem Gehalt, das Geld ist aber schon ausgegeben." : ""].filter(Boolean).join(" ")}
          </li>
        {/if}
      {/each}
    </ul>
  {:else}
    <p class="small muted">Nichts mehr erwartet.</p>
  {/if}

  <div class="result">
    <span>Frei verfügbar</span>
    <span class="num" class:neg={data.available < 0}>{eur(data.available)}</span>
  </div>
  {#if perDay !== null}
    <p class="small muted per-day">≈ {eur(perDay)} pro Tag für {daysLeft} {daysLeft === 1 ? "Tag" : "Tage"}
      {data.salary ? "bis zum Gehalt" : ""}{data.salary ? ` (${eur(data.salary.amount)})` : ""}</p>
  {:else if data.available < 0}
    <p class="small neg per-day">Bis zum Gehalt fehlen {eur(-data.available)} – Überziehungsrahmen prüfen.</p>
  {/if}
</section>

<style>
  .summary h2 { margin-bottom: 4px; }
  .big { font-size: 44px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.1; font-variant-numeric: normal; }
  .accs { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 2px; color: var(--ink-2); }
  .accs li { display: flex; align-items: center; gap: 6px; }
  .accs .num { margin-left: auto; }
  .bar { display: flex; gap: 2px; height: 10px; margin: 16px 0 6px; border-radius: 5px; overflow: hidden;
         background: var(--surface-2); }
  .bar span { display: block; height: 100%; }
  .free { background: var(--accent); }
  .planned { background: var(--copper); }
  .legend { display: flex; gap: 14px; color: var(--ink-2); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend .swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  h3 { margin: 18px 0 6px; font-weight: 600; color: var(--muted); text-transform: none; letter-spacing: 0; }
  .lines { list-style: none; margin: 0; padding: 0; }
  .lines li { display: flex; align-items: baseline; gap: 10px; padding: 8px 0; border-top: 1px solid var(--hairline); }
  .lines li:first-child { border-top: 0; }
  .lines li.hint { border-top: 0; padding: 0 0 6px 72px; }
  .when { width: 62px; flex: none; white-space: nowrap; }
  .late { color: var(--copper); }
  .name { flex: 1; min-width: 0; color: var(--ink); text-decoration: none; overflow-wrap: anywhere; }
  a.name:active { color: var(--accent); }
  .pos { color: var(--good); }
  .neg { color: var(--bad); }
  .result { display: flex; justify-content: space-between; align-items: baseline; margin-top: 8px; padding-top: 12px;
            border-top: 2px solid var(--ink); font-weight: 650; font-size: 20px; }
  .per-day { margin: 4px 0 0; }
</style>
