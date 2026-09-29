<script lang="ts">
  import { api, type Category, type Tx } from "../lib/api";
  import { dayLongFmt, eurCents, signed } from "../lib/format";
  import { CATEGORY_SOURCE, EVIDENCE, LINK_KIND, ROLE } from "../lib/labels";
  import { slotVar } from "../lib/colors";
  import Sheet from "./Sheet.svelte";

  let { id, categories, demo, onerror, onclose, onopen }: {
    id: number; categories: Category[]; demo: boolean; onerror: (e: unknown) => void;
    onclose: (changed: boolean) => void; onopen: (id: number) => void;
  } = $props();

  let tx = $state<Tx | null>(null);
  let changed = $state(false);
  let note = $state("");
  let makeRule = $state(false);
  let rulePattern = $state("");

  async function load() {
    try {
      tx = await api.get<Tx>(`/api/transactions/${id}`);
      note = tx.note ?? "";
      rulePattern = (tx.counterparty || tx.description).split(/\s+/).slice(0, 2).join(" ").toUpperCase();
    } catch (e) {
      onerror(e);
    }
  }
  $effect(() => { void id; load(); });

  async function save(changes: Record<string, unknown>) {
    try {
      tx = await api.patch<Tx>(`/api/transactions/${id}`, changes);
      changed = true;
    } catch (e) {
      onerror(e);
    }
  }

  let itemRule = $state(false);

  async function setItemCategory(itemId: number, name: string, value: string) {
    try {
      const pattern = itemRule ? name.split(/\s+/).slice(0, 2).join(" ").toUpperCase() : undefined;
      await api.patch(`/api/order-items/${itemId}`, { category_id: Number(value), rule_pattern: pattern });
      changed = true;
      await load();
    } catch (e) {
      onerror(e);
    }
  }

  function setCategory(value: string) {
    const catId = Number(value);
    save(makeRule && rulePattern.trim().length >= 3 ? { category_id: catId, rule_pattern: rulePattern.trim() }
                                                     : { category_id: catId });
  }
</script>

<Sheet title={tx ? (tx.counterparty || tx.description || "Umsatz") : "Umsatz"} onclose={() => onclose(changed)}>
  {#if tx}
    <div class="amount num" class:pos={tx.amount > 0}>{signed(tx.amount, tx.currency)}</div>
    {#if tx.currency !== "EUR"}
      <p class="small muted">{tx.amount_eur !== null ? `≈ ${eurCents(tx.amount_eur)} (EZB-Kurs vom Buchungstag)` : "Kein Wechselkurs – nicht in den Summen enthalten"}</p>
    {:else if tx.original_currency}
      <p class="small muted">Ursprünglich {signed(tx.original_amount ?? 0, tx.original_currency)}</p>
    {/if}

    <dl class="card facts">
      <div><dt>Datum</dt><dd>{dayLongFmt(tx.date)}{tx.status === "pending" ? " · vorgemerkt" : ""}</dd></div>
      <div><dt>Konto</dt><dd>{tx.account.name}</dd></div>
      <div><dt>Zählt als</dt><dd>{ROLE[tx.role] ?? tx.role}</dd></div>
      {#if tx.description && tx.description !== tx.counterparty}<div><dt>Text</dt><dd class="wrap">{tx.description}</dd></div>{/if}
      {#if tx.counterparty_iban}<div><dt>IBAN</dt><dd>{tx.counterparty_iban}</dd></div>{/if}
      {#if tx.apple_pay}<div><dt>Quelle</dt><dd>Apple-Pay-Meldung</dd></div>{/if}
      {#if tx.mcc}<div><dt>MCC</dt><dd>{tx.mcc}</dd></div>{/if}
    </dl>

    {#if tx.links.length}
      <h3>Verknüpft</h3>
      {#each tx.links as l}
        <div class="card link">
          <strong>{LINK_KIND[l.kind] ?? l.kind}{l.status === "suggested" ? " (Vorschlag)" : ""}</strong>
          <p class="small muted">{EVIDENCE[l.evidence] ?? ""}</p>
          {#if l.other}
            <button class="other" onclick={() => onopen(l.other!.id)}>
              <span>{l.other.counterparty || l.other.description}<span class="small muted"> · {l.other.account.name}</span></span>
              <span class="num">{signed(l.other.amount, l.other.currency)}</span>
            </button>
          {/if}
        </div>
      {/each}
    {/if}

    {#if tx.items?.length}
      <h3>Positionen · Amazon-Bestellung {tx.items[0].order_id}</h3>
      <ul class="card items">
        {#each tx.items as it (it.id)}
          <li>
            <div class="line">
              <span class="swatch" style:background={slotVar(it.category_slot)}></span>
              <span class="grow">{it.quantity > 1 ? `${it.quantity}× ` : ""}{it.name}</span>
              <span class="num">{signed(it.amount)}</span>
            </div>
            <select value={it.category_id} disabled={demo} aria-label="Kategorie für {it.name}"
                    onchange={(e) => setItemCategory(it.id, it.name, e.currentTarget.value)}>
              {#each categories.filter((c) => c.kind === "expense") as c}<option value={c.id}>{c.name}</option>{/each}
            </select>
          </li>
        {/each}
      </ul>
      <label class="check small"><input type="checkbox" bind:checked={itemRule} disabled={demo} />
        Gewählte Kategorie auch für künftige Artikel mit gleichem Namensanfang</label>
    {/if}

    {#if !tx.items?.length}
    <h3>Kategorie</h3>
    <div class="card form">
      <select value={tx.category.id} disabled={demo} onchange={(e) => setCategory(e.currentTarget.value)} aria-label="Kategorie">
        {#each categories as c}<option value={c.id}>{c.name}</option>{/each}
      </select>
      <p class="small muted">Erkannt: {CATEGORY_SOURCE[tx.category.source] ?? tx.category.source}{#if tx.category.hint} (wie „{tx.category.hint}“){/if}</p>
      <label class="check"><input type="checkbox" bind:checked={makeRule} disabled={demo} />
        Auch künftig so zuordnen, wenn der Text enthält:</label>
      {#if makeRule}<input type="text" bind:value={rulePattern} aria-label="Muster für die Regel" />{/if}
    </div>
    {/if}

    <h3>Notiz</h3>
    <div class="card form">
      <textarea rows="2" bind:value={note} disabled={demo} placeholder="z. B. Geschenk für Anna"
                onblur={() => note !== (tx?.note ?? "") && save({ note })}></textarea>
      <label class="check"><input type="checkbox" checked={tx.excluded_by_user} disabled={demo}
             onchange={(e) => save({ excluded: e.currentTarget.checked })} /> Nicht mitzählen</label>
    </div>
    {#if demo}<p class="small muted">In der Demo-Version sind Änderungen nicht möglich.</p>{/if}
  {:else}
    <p class="muted">Lade …</p>
  {/if}
</Sheet>

<style>
  .amount { font-size: 34px; font-weight: 650; margin: 4px 0; }
  .amount.pos { color: var(--good); }
  h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .02em; color: var(--muted); margin: 18px 4px 8px; }
  .facts { display: grid; gap: 10px; margin: 12px 0 0; }
  .facts div { display: flex; gap: 12px; justify-content: space-between; }
  .facts dt { color: var(--muted); }
  .facts dd { margin: 0; text-align: right; }
  .wrap { word-break: break-word; }
  .link p { margin: 4px 0 8px; }
  .other { all: unset; box-sizing: border-box; display: flex; justify-content: space-between; gap: 10px; width: 100%;
           padding: 10px 12px; border-radius: 10px; background: var(--surface-2); cursor: pointer; }
  .form { display: grid; gap: 10px; }
  select, input[type="text"], textarea { font: inherit; font-size: 16px; color: var(--ink); background: var(--surface-2);
    border: 0; border-radius: 10px; padding: 10px 12px; width: 100%; }
  .check { display: flex; gap: 8px; align-items: center; font-size: 15px; }
  .form p { margin: 0; }
  .items { list-style: none; padding: 4px 14px; display: grid; }
  .items li { display: grid; gap: 6px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .items li:first-child { border-top: 0; }
  .line { display: flex; gap: 8px; align-items: center; }
  .grow { flex: 1; min-width: 0; }
  .items select { padding: 6px 10px; font-size: 14px; }
</style>
