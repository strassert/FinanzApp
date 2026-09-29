<script lang="ts">
  import { api, type Interval, type Recurring, type RecurringItem } from "../lib/api";
  import { day, dayLongFmt, eur, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import { go } from "../lib/router.svelte";
  import Sheet from "../components/Sheet.svelte";

  let { onerror, demo = false }: { onerror: (e: unknown) => void; demo?: boolean } = $props();

  let data = $state<Recurring | null>(null);
  let selected = $state<RecurringItem | null>(null);

  async function load() {
    try {
      data = await api.get<Recurring>("/api/recurring");
    } catch (e) {
      onerror(e);
    }
  }
  load();

  async function decide(item: RecurringItem, decision: "rejected" | null) {
    try {
      data = await api.post<Recurring>("/api/recurring/decision", { key: item.key, decision });
      selected = null;
    } catch (e) {
      onerror(e);
    }
  }

  const INTERVALS: [Interval, string][] = [
    ["monthly", "Monatlich"], ["quarterly", "Vierteljährlich"], ["halfyearly", "Halbjährlich"],
    ["yearly", "Jährlich"], ["weekly", "Wöchentlich"],
  ];
  const intervalLabel = (i: Interval) => INTERVALS.find(([k]) => k === i)?.[1] ?? i;

  const in30 = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);

  const expenses = $derived(data?.items.filter((i) => i.role === "expense") ?? []);
  const income = $derived(data?.items.filter((i) => i.role === "income") ?? []);
  const groups = $derived(INTERVALS
    .map(([key, title]) => ({ title, items: expenses.filter((i) => i.interval === key)
      .sort((a, b) => a.amount - b.amount) }))
    .filter((g) => g.items.length));
  const upcoming = $derived((data?.items ?? []).filter((i) => i.next_date <= in30)
    .sort((a, b) => a.next_date.localeCompare(b.next_date)));
  const left = $derived(data ? data.monthly_income - data.monthly_expense : 0);
</script>

{#snippet row(i: RecurringItem, showDate: boolean)}
  <li>
    <button class="row" onclick={() => (selected = i)}>
      <span class="dot" style:background={slotVar(i.category.color_slot)}></span>
      <span class="grow">
        <span class="name">{i.name}</span>
        <span class="small muted">
          {#if showDate}{i.overdue ? "überfällig seit" : ""} {day(i.next_date)} · {intervalLabel(i.interval)}
          {:else}{i.category.name} · nächste {day(i.next_date)}{/if}
        </span>
      </span>
      <span class="right">
        <span class="num" class:pos={i.amount > 0}>{signed(i.amount)}</span>
        {#if i.previous_amount !== null}
          <span class="small change">vorher {signed(i.previous_amount)}</span>
        {:else if i.interval !== "monthly" && !showDate}
          <span class="small muted">{signed(i.monthly)} / Monat</span>
        {/if}
      </span>
    </button>
  </li>
{/snippet}

{#if data}
  <section class="card hero">
    <div class="label small">Fixkosten pro Monat</div>
    <div class="big num">{eur(data.monthly_expense)}</div>
    <dl class="figures">
      <div><dt>Regelmäßige Einnahmen</dt><dd class="num">{eur(data.monthly_income)}</dd></div>
      <div><dt>Bleibt nach Fixkosten</dt><dd class="num" class:neg={left < 0}>{eur(left)}</dd></div>
    </dl>
    <p class="small muted note">Erkannt aus Buchungen, die sich regelmäßig mit ähnlichem Betrag wiederholen.
      Vierteljährliche und jährliche Zahlungen zählen anteilig.</p>
  </section>

  {#if upcoming.length}
    <section class="card">
      <h2>Nächste 30 Tage</h2>
      <ul class="rows">
        {#each upcoming as i (i.key + i.interval + i.amount)}{@render row(i, true)}{/each}
      </ul>
    </section>
  {/if}

  {#each groups as g (g.title)}
    <section class="card">
      <h2>{g.title}</h2>
      <ul class="rows">
        {#each g.items as i (i.key + i.interval + i.amount)}{@render row(i, false)}{/each}
      </ul>
    </section>
  {/each}

  {#if income.length}
    <section class="card">
      <h2>Einnahmen</h2>
      <ul class="rows">
        {#each income as i (i.key + i.interval + i.amount)}{@render row(i, false)}{/each}
      </ul>
    </section>
  {/if}

  {#if !data.items.length}
    <section class="card"><p class="muted">Noch keine regelmäßigen Zahlungen erkannt. Dafür braucht es mindestens drei Monatsbuchungen.</p></section>
  {/if}

  {#if data.rejected.length}
    <section class="card">
      <h2>Ausgeblendet</h2>
      <ul class="rows">
        {#each data.rejected as i (i.key + i.interval + i.amount)}
          <li>
            <span class="grow"><span class="name">{i.name}</span><span class="small muted">{signed(i.amount)} · {intervalLabel(i.interval)}</span></span>
            <button class="small-btn" disabled={demo} onclick={() => decide(i, null)}>Wieder anzeigen</button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
{:else}
  <div class="card muted">Lade …</div>
{/if}

{#if selected}
  {@const s = selected}
  <Sheet title={s.name} onclose={() => (selected = null)}>
    <div class="card">
      <dl class="facts">
        <div><dt>Betrag</dt><dd class="num">{signed(s.amount)}</dd></div>
        {#if s.previous_amount !== null}<div><dt>Vorher</dt><dd class="num">{signed(s.previous_amount)}</dd></div>{/if}
        <div><dt>Rhythmus</dt><dd>{intervalLabel(s.interval)}{s.interval !== "monthly" ? ` · ${signed(s.monthly)} pro Monat` : ""}</dd></div>
        <div><dt>{s.overdue ? "Erwartet seit" : "Nächste Buchung"}</dt><dd>{dayLongFmt(s.next_date)}</dd></div>
        <div><dt>Zuletzt</dt><dd>{dayLongFmt(s.last_date)}</dd></div>
        <div><dt>Konto</dt><dd>{s.account.name}</dd></div>
        <div><dt>Kategorie</dt><dd>{s.category.name}</dd></div>
        <div><dt>Erkannt aus</dt><dd>{s.count} Buchungen</dd></div>
      </dl>
    </div>
    <div class="actions">
      <button onclick={() => go("umsaetze", { q: s.name, konto: s.account.id })}>Umsätze ansehen</button>
      <button class="danger" disabled={demo} onclick={() => decide(s, "rejected")}>Keine Fixkosten</button>
    </div>
    <p class="small muted">„Keine Fixkosten“ blendet die Zahlung aus und nimmt sie aus der Summe. Das lässt sich unten auf der Seite rückgängig machen.</p>
  </Sheet>
{/if}

<style>
  .hero .label { color: var(--ink-2); }
  .big { font-size: 40px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.1; margin: 2px 0 12px; }
  .figures { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 0;
             padding-top: 12px; border-top: 1px solid var(--hairline); }
  .figures dt { font-size: 12px; color: var(--muted); }
  .figures dd { margin: 2px 0 0; font-weight: 600; font-size: 17px; }
  .note { margin: 12px 0 0; }
  .neg { color: var(--bad); }
  .pos { color: var(--good); }
  .change { color: var(--copper); }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; padding-top: 0; }
  .row { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 10px; width: 100%; cursor: pointer; color: var(--ink); }
  .row:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
  .grow { flex: 1; min-width: 0; display: grid; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .right { text-align: right; display: grid; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .small-btn { border: 0; border-radius: 999px; padding: 6px 12px; background: var(--accent-wash); color: var(--accent);
               font-weight: 600; cursor: pointer; white-space: nowrap; }
  .facts { display: grid; gap: 10px; margin: 0; }
  .facts div { display: flex; justify-content: space-between; gap: 12px; }
  .facts dt { color: var(--muted); }
  .facts dd { margin: 0; text-align: right; }
  .actions { display: flex; gap: 8px; margin: 12px 0; }
  .actions button { flex: 1; border: 0; border-radius: 12px; padding: 12px; cursor: pointer; font-weight: 600;
                    background: var(--surface); color: var(--ink); box-shadow: 0 0 0 1px var(--border); }
  .actions .danger { color: var(--bad); }
  button:disabled { opacity: .5; cursor: default; }
</style>
