<script lang="ts">
  // K5: uncertain transfers and duplicates for the user to confirm or reject.
  import { api, type Tx } from "../lib/api";
  import { day, signed } from "../lib/format";
  import { EVIDENCE } from "../lib/labels";

  interface Suggestion { kind: string; evidence: string; a: Tx; b: Tx }
  let { open, demo, onerror, onchange }: {
    open: boolean; demo: boolean; onerror: (e: unknown) => void; onchange: () => void;
  } = $props();

  let items = $state<Suggestion[]>([]);
  let expanded = $state(false);

  async function load() {
    try {
      items = (await api.get<{ items: Suggestion[] }>("/api/suggestions")).items;
    } catch (e) {
      onerror(e);
    }
  }
  load();
  $effect(() => { if (open) expanded = true; });

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

{#if items.length}
  <section class="card sugg">
    <button class="head" onclick={() => (expanded = !expanded)} aria-expanded={expanded}>
      <strong>{items.length} {items.length === 1 ? "Verknüpfung" : "Verknüpfungen"} zu prüfen</strong>
      <span aria-hidden="true">{expanded ? "▴" : "▾"}</span>
    </button>
    {#if expanded}
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
