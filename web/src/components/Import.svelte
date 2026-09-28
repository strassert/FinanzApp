<script lang="ts">
  // F1: two-step import – preview with guessed columns, then import with the confirmed mapping.
  import { untrack } from "svelte";
  import { ApiError, getToken, type Account } from "../lib/api";
  import { day, signed } from "../lib/format";
  import Sheet from "./Sheet.svelte";

  let { accounts, onerror, onclose }: { accounts: Account[]; onerror: (e: unknown) => void; onclose: (done: boolean) => void } = $props();

  interface Holding { isin: string; name: string; quantity: string }
  interface Preview {
    kind?: "depot"; holdings?: Holding[];
    columns: string[]; sample: string[][]; mapping: Record<string, unknown>; template: string | null;
    remembered: boolean; count: number; skipped: number; has_balance: boolean;
    parsed: { date: string; amount: number; currency: string; text: string; counterparty: string | null }[];
  }
  const units = (q: string) => Number(q).toLocaleString("de-AT", { maximumFractionDigits: 6 });

  // initial choice only: prefer an account without bank connection
  let accountId = $state(untrack(() => accounts.find((a) => a.source !== "api")?.id ?? accounts[0]?.id ?? 0));
  let file = $state<File | null>(null);
  let preview = $state<Preview | null>(null);
  let mapping = $state<Record<string, unknown>>({});
  let result = $state<{ new: number; known: number; skipped: number; first: string; last: string;
                        holdings?: Holding[] } | null>(null);
  let busy = $state(false);

  async function send(path: string, withMapping: boolean) {
    const form = new FormData();
    form.set("account_id", String(accountId));
    form.set("file", file!);
    if (withMapping) form.set("mapping", JSON.stringify(mapping));
    const resp = await fetch(path, { method: "POST", body: form, headers: { Authorization: `Bearer ${getToken()}` } });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new ApiError(resp.status, data.error || `Fehler ${resp.status}`);
    return data;
  }

  async function doPreview() {
    if (!file) return;
    busy = true;
    try {
      preview = await send("/api/import/preview", false);
      mapping = { ...preview!.mapping };
    } catch (e) {
      onerror(e);
    } finally {
      busy = false;
    }
  }

  async function doImport() {
    busy = true;
    try {
      result = await send("/api/import", true);
    } catch (e) {
      onerror(e);
    } finally {
      busy = false;
    }
  }

  function setCol(key: string, value: string) {
    mapping = { ...mapping, [key]: value === "" ? null : Number(value) };
    if (key === "amount" && value !== "") mapping = { ...mapping, debit: null, credit: null };
  }
  function setText(value: string) {
    mapping = { ...mapping, text: value === "" ? [] : [Number(value)] };
  }
  const fields: [string, string][] = [["date", "Datum"], ["amount", "Betrag"], ["debit", "Soll (Ausgang)"],
    ["credit", "Haben (Eingang)"], ["counterparty", "Gegenseite"], ["currency", "Währung"], ["balance", "Saldo"]];
</script>

<Sheet title="Datei importieren" onclose={() => onclose(Boolean(result))}>
  {#if result?.holdings}
    <div class="card">
      <p><strong>{result.new} neue Depotbuchungen</strong> importiert ({day(result.first)} bis {day(result.last)}).</p>
      {#if result.known}<p class="small muted">{result.known} waren schon vorhanden und wurden übersprungen.</p>{/if}
      <ul class="sample">
        {#each result.holdings as h}
          <li><span class="grow">{h.name}<span class="small muted"> · {h.isin}</span></span>
            <span class="num">{units(h.quantity)} Stk.</span></li>
        {/each}
      </ul>
      <p class="small muted">Der Depotwert wird täglich mit aktuellen Kursen neu berechnet.</p>
      <button class="primary" onclick={() => onclose(true)}>Fertig</button>
    </div>
  {:else if result}
    <div class="card">
      <p><strong>{result.new} neue Umsätze</strong> importiert ({day(result.first)} bis {day(result.last)}).</p>
      {#if result.known}<p class="small muted">{result.known} waren schon vorhanden und wurden übersprungen.</p>{/if}
      {#if result.skipped}<p class="small muted">{result.skipped} Zeilen ohne Datum oder Betrag ignoriert.</p>{/if}
      <button class="primary" onclick={() => onclose(true)}>Fertig</button>
    </div>
  {:else if !preview}
    <div class="card form">
      <label>Konto
        <select bind:value={accountId}>
          {#each accounts as a}<option value={a.id}>{a.name}</option>{/each}
        </select></label>
      <label>Datei (CSV, XLSX, XLS)
        <input type="file" accept=".csv,.xls,.xlsx,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
               onchange={(e) => (file = e.currentTarget.files?.[0] ?? null)} /></label>
      <p class="small muted">PDF-Auszüge lassen sich nicht zuverlässig lesen – bitte im Online-Banking den Export als CSV oder Excel wählen.
        Hat die Datei keinen Saldo, trage bei einer Kreditkarte den offenen Betrag unter „Konten“ ein.</p>
      <button class="primary" disabled={!file || busy} onclick={doPreview}>{busy ? "Lese …" : "Vorschau"}</button>
    </div>
  {:else if preview.kind === "depot"}
    <p class="small muted">Format erkannt: {preview.template}. {preview.count} Käufe/Verkäufe,
      {preview.skipped} Steuerbuchungen (Thesaurierung) ändern den Bestand nicht und werden übersprungen.</p>
    <h3>Bestand laut Datei</h3>
    <ul class="card sample">
      {#each preview.holdings ?? [] as h}
        <li><span class="grow">{h.name}<span class="small muted"> · {h.isin}</span></span>
          <span class="num">{units(h.quantity)} Stk.</span></li>
      {/each}
    </ul>
    <button class="primary" disabled={busy} onclick={doImport}>{busy ? "Importiere …" : "Importieren"}</button>
  {:else}
    <p class="small muted">
      {preview.template ? `Format erkannt: ${preview.template}. ` : ""}{preview.remembered ? "Zuordnung vom letzten Import. " : ""}
      Prüfe die Spalten und die Beispielzeilen.
    </p>
    <div class="card form">
      {#each fields as [key, label]}
        <label>{label}
          <select value={mapping[key] ?? ""} onchange={(e) => setCol(key, e.currentTarget.value)}>
            <option value="">–</option>
            {#each preview.columns as c, i}<option value={i}>{c || `Spalte ${i + 1}`}</option>{/each}
          </select></label>
      {/each}
      <label>Text
        <select value={(mapping.text as number[] | undefined)?.[0] ?? ""} onchange={(e) => setText(e.currentTarget.value)}>
          <option value="">–</option>
          {#each preview.columns as c, i}<option value={i}>{c || `Spalte ${i + 1}`}</option>{/each}
        </select></label>
      <label class="check"><input type="checkbox" checked={Boolean(mapping.invert)}
             onchange={(e) => (mapping = { ...mapping, invert: e.currentTarget.checked })} /> Vorzeichen umkehren (Ausgaben stehen positiv in der Datei)</label>
    </div>
    <h3>Beispiel ({preview.count} Umsätze erkannt{preview.skipped ? `, ${preview.skipped} Zeilen übersprungen` : ""})</h3>
    <ul class="card sample">
      {#each preview.parsed as t}
        <li><span>{day(t.date)}</span><span class="grow">{t.counterparty ?? ""} {t.text}</span>
          <span class="num">{signed(mapping.invert ? -t.amount : t.amount, t.currency)}</span></li>
      {/each}
    </ul>
    <p class="small muted">Die Vorschau zeigt die erkannte Zuordnung; geänderte Spalten wirken beim Import.</p>
    <button class="primary" disabled={busy} onclick={doImport}>{busy ? "Importiere …" : "Importieren"}</button>
  {/if}
</Sheet>

<style>
  .form { display: grid; gap: 10px; }
  label { display: grid; gap: 4px; font-size: 14px; color: var(--ink-2); }
  .check { display: flex; gap: 8px; align-items: center; }
  select, input[type="file"] { font: inherit; font-size: 16px; color: var(--ink); background: var(--surface-2);
    border: 0; border-radius: 10px; padding: 10px 12px; width: 100%; }
  .primary { width: 100%; border: 0; border-radius: 12px; padding: 12px; font-weight: 600; cursor: pointer;
             background: var(--accent); color: var(--accent-ink); margin-top: 6px; }
  .primary:disabled { opacity: .5; }
  h3 { font-size: 13px; text-transform: uppercase; color: var(--muted); margin: 16px 4px 8px; }
  .sample { list-style: none; padding: 8px 14px; }
  .sample li { display: flex; gap: 10px; padding: 6px 0; font-size: 14px; border-top: 1px solid var(--hairline); }
  .sample li:first-child { border-top: 0; }
  .grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
