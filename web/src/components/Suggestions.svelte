<script lang="ts">
  // K5: uncertain transfers and duplicates for the user to confirm or reject.
  import { api, type OrderSuggestion, type Tx } from "../lib/api";
  import { day, signed } from "../lib/format";
  import { EVIDENCE } from "../lib/labels";

  interface Suggestion { kind: string; evidence: string; a: Tx; b: Tx }
  let { open, demo, onerror, onchange }: {
    open: boolean; demo: boolean; onerror: (e: unknown) => void; onchange: () => void;
  } = $props();

  let items = $state<Suggestion[]>([]);
  let orders = $state<OrderSuggestion[]>([]);
  let expanded = $state(false);

  async function load() {
    try {
      const data = await api.get<{ items: Suggestion[]; orders: OrderSuggestion[] }>("/api/suggestions");
      items = data.items;
      orders = data.orders ?? [];
    } catch (e) {
      onerror(e);
    }
  }
  load();
  $effect(() => { if (open) expanded = true; });

  async function decideOrder(o: OrderSuggestion, decision: "confirmed" | "rejected") {
    try {
      await api.post("/api/suggestions/order", { shipment_key: o.shipment_key, tx_id: o.tx.id, decision });
      orders = orders.filter((x) => x !== o);
      onchange();
    } catch (e) {
      onerror(e);
    }
  }
  const count = $derived(items.length + orders.length);

  async function decide(s: Suggestion, decision: "confirmed" | "rejected") {
    try {
      await api.post("/api/suggestions", { kind: s.kind, a_id: s.a.id, b_id: s.b.id, decision });
      items = items.filter((x) => x !== s);
      onchange();
    } catch (e) {
      onerror(e);
    }
  }
</script>

{#if count}
  <section class="card sugg">
    <button class="head" onclick={() => (expanded = !expanded)} aria-expanded={expanded}>
      <strong>{count} {count === 1 ? "Verknüpfung" : "Verknüpfungen"} zu prüfen</strong>
      <span aria-hidden="true">{expanded ? "▴" : "▾"}</span>
    </button>
    {#if expanded}
      {#each orders as o}
        <div class="item">
          <p class="small muted">Gehört diese Abbuchung zur Amazon-Bestellung vom {day(o.order_date)}?
            Es gibt mehrere Abbuchungen mit genau diesem Betrag.</p>
          <div class="row">
            <span>{o.tx.counterparty || o.tx.description}<span class="small muted"> · {day(o.tx.date)}</span></span>
            <span class="num">{signed(o.tx.amount, o.tx.currency)}</span>
          </div>
          {#each o.items as it}
            <div class="row small muted"><span>{it.name}</span><span class="num">{signed(-it.amount_minor)}</span></div>
          {/each}
          <div class="actions">
            <button class="yes" disabled={demo} onclick={() => decideOrder(o, "confirmed")}>Ja, aufteilen</button>
            <button class="no" disabled={demo} onclick={() => decideOrder(o, "rejected")}>Nein</button>
          </div>
        </div>
      {/each}
      {#each items as s}
        <div class="item">
          <p class="small muted">{s.kind === "duplicate" ? "Doppelt erfasst?" : "Umbuchung zwischen eigenen Konten?"}
            {EVIDENCE[s.evidence] ?? ""}</p>
          {#each [s.a, s.b] as t}
            <div class="row">
              <span>{t.counterparty || t.description}<span class="small muted"> · {t.account.name} · {day(t.date)}</span></span>
              <span class="num">{signed(t.amount, t.currency)}</span>
            </div>
          {/each}
          <div class="actions">
            <button class="yes" disabled={demo} onclick={() => decide(s, "confirmed")}>
              {s.kind === "duplicate" ? "Ja, doppelt" : "Ja, Umbuchung"}</button>
            <button class="no" disabled={demo} onclick={() => decide(s, "rejected")}>Nein</button>
          </div>
        </div>
      {/each}
    {/if}
  </section>
{/if}

<style>
  .sugg { background: var(--accent-wash); box-shadow: none; }
  .head { all: unset; display: flex; justify-content: space-between; width: 100%; cursor: pointer; color: var(--accent); }
  .item { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--hairline); }
  .item p { margin: 0 0 8px; }
  .row { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; }
  .actions { display: flex; gap: 8px; margin-top: 10px; }
  .actions button { flex: 1; border: 0; border-radius: 10px; padding: 10px; cursor: pointer; font-weight: 600; }
  .yes { background: var(--accent); color: var(--accent-ink); }
  .no { background: var(--surface); color: var(--ink); }
  button:disabled { opacity: .5; }
</style>
