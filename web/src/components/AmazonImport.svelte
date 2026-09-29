<script lang="ts">
  // Import the Amazon "Your Orders" data export (ZIP or Retail.OrderHistory CSV).
  import { ApiError, getToken } from "../lib/api";
  import { day } from "../lib/format";
  import Sheet from "./Sheet.svelte";

  let { onerror, onclose }: { onerror: (e: unknown) => void; onclose: (done: boolean) => void } = $props();

  interface Result { items: number; new: number; orders: number; first: string | null; last: string | null;
    shipments: number; matched: number; suggested: number }
  let file = $state<File | null>(null);
  let busy = $state(false);
  let result = $state<Result | null>(null);

  async function upload() {
    if (!file) return;
    busy = true;
    try {
      const form = new FormData();
      form.set("file", file);
      const resp = await fetch("/api/import/amazon", { method: "POST", body: form,
                                                      headers: { Authorization: `Bearer ${getToken()}` } });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new ApiError(resp.status, data.error || `Fehler ${resp.status}`);
      result = data;
    } catch (e) {
      onerror(e);
    } finally {
      busy = false;
    }
  }
</script>

<Sheet title="Amazon-Bestellungen" onclose={() => onclose(Boolean(result))}>
  {#if result}
    <div class="card">
      <p><strong>{result.new} neue Artikel</strong> aus {result.orders} Bestellungen
        {#if result.first && result.last}({day(result.first)} bis {day(result.last)}){/if}.</p>
      <p class="small muted">{result.matched} von {result.shipments} Lieferungen sind einer Abbuchung zugeordnet und
        in Positionen aufgeteilt.{#if result.suggested} {result.suggested} brauchen deine Bestätigung (unter „Umsätze“).{/if}</p>
      <p class="small muted">Nicht zugeordnet bleiben Lieferungen, die mit einer anderen Zahlungsart bezahlt wurden
        oder deren Abbuchung älter ist als die geladene Kontohistorie.</p>
      <button class="primary" onclick={() => onclose(true)}>Fertig</button>
    </div>
  {:else}
    <div class="card steps">
      <strong>Export anfordern (einmalig, dauert Stunden bis wenige Tage)</strong>
      <ol class="small">
        <li>amazon.de → <em>Konto und Listen</em> → <em>Mein Konto</em> → ganz unten <em>Meine Daten anfordern</em>
          (oder „Datenschutz“ → „Auskunft“).</li>
        <li><em>Ihre Bestellungen</em> auswählen und die Anfrage per E-Mail-Link bestätigen.</li>
        <li>Wenn die Mail „Ihre Daten sind bereit“ kommt, die ZIP-Datei laden.</li>
      </ol>
      <p class="small muted">Du kannst die ganze ZIP-Datei wählen oder nur <code>Retail.OrderHistory.1.csv</code>.
        Ein erneuter Import desselben oder eines neueren Exports fügt nur Neues hinzu.</p>
    </div>
    <div class="card form">
      <label>Datei (ZIP oder CSV)
        <input type="file" accept=".zip,.csv,application/zip,text/csv"
               onchange={(e) => (file = e.currentTarget.files?.[0] ?? null)} /></label>
      <button class="primary" disabled={!file || busy} onclick={upload}>{busy ? "Importiere …" : "Importieren"}</button>
    </div>
    <p class="small muted">Die Artikelnamen bleiben auf deinem Server (und in den verschlüsselten Backups).</p>
  {/if}
</Sheet>

<style>
  .steps ol { margin: 8px 0; padding-left: 20px; display: grid; gap: 6px; }
  .steps p, .card p { margin: 6px 0; }
  .form { display: grid; gap: 10px; }
  label { display: grid; gap: 4px; font-size: 14px; color: var(--ink-2); }
  input[type="file"] { font: inherit; font-size: 15px; background: var(--surface-2); border-radius: 10px; padding: 10px; }
  .primary { width: 100%; border: 0; border-radius: 12px; padding: 12px; font-weight: 600; cursor: pointer;
             background: var(--accent); color: var(--accent-ink); margin-top: 6px; }
  .primary:disabled { opacity: .5; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 5px; font-size: 13px; }
</style>
