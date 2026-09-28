<script lang="ts">
  // F9 on iOS: a Shortcuts automation reports each Apple Pay payment to the server.
  import { api } from "../lib/api";
  import { day } from "../lib/format";
  import { signed } from "../lib/format";

  let { onerror, demo = false }: { onerror: (e: unknown) => void; demo?: boolean } = $props();

  interface Event { id: number; occurred_at: string; amount_minor: number | null; currency: string;
    merchant: string; card: string; status: string; reason: string | null }
  let events = $state<Event[]>([]);
  let accounts = $state<{ id: number; name: string }[]>([]);
  const url = `${location.origin}/api/wallet`;

  async function load() {
    try {
      events = (await api.get<{ items: Event[] }>("/api/wallet")).items;
      accounts = (await api.get<{ items: { id: number; name: string }[] }>("/api/accounts")).items;
    } catch (e) {
      onerror(e);
    }
  }
  load();

  async function assign(ev: Event, accountId: number) {
    try {
      await api.post(`/api/wallet/${ev.id}/assign`, { account_id: accountId, remember: true });
      load();
    } catch (e) {
      onerror(e);
    }
  }

  const STATUS: Record<string, string> = { recorded: "erfasst", duplicate: "doppelt gemeldet", unassigned: "nicht zugeordnet",
    ignored: "ignoriert", reassigned: "zugeordnet" };
</script>

<section class="card guide">
  <h2>Einrichten (einmalig)</h2>
  <ol>
    <li>Auf dem Server einen Token nur für diesen Zweck erzeugen:<br />
      <code>sudo -u finanzen finanzen token create --scope wallet --name Kurzbefehl</code></li>
    <li>iPhone: <strong>Kurzbefehle</strong> → <strong>Automation</strong> → <strong>+</strong> → <strong>Transaktion</strong>.
      Alle Karten wählen, „Sofort ausführen“ aktivieren.</li>
    <li>Aktion <strong>„Inhalte von URL abrufen“</strong> hinzufügen:
      <ul>
        <li>URL: <code>{url}</code></li>
        <li>Methode: <strong>POST</strong>, Anfragetext: <strong>JSON</strong></li>
        <li>Header: <code>Authorization</code> = <code>Bearer &lt;Token&gt;</code></li>
        <li>Felder: <code>amount</code> = Kurzbefehl-Eingabe → Betrag, <code>merchant</code> = Händler,
          <code>card</code> = Karte oder Pass</li>
      </ul></li>
  </ol>
  <p class="small muted">Die Karte wird dem Konto zugeordnet, dessen Name oder Muster im Kartennamen vorkommt.
    Liefert die Bank die Buchung später, wird sie damit verknüpft – nichts zählt doppelt. Nur Apple-Pay-Zahlungen
    lösen die Automation aus, nicht die physische Karte. Das iPhone muss dafür im Tailscale-Netz sein.</p>
</section>

<section class="card">
  <h2>Letzte Meldungen</h2>
  {#if !events.length}<p class="small muted">Noch keine.</p>{/if}
  <ul class="rows">
    {#each events as ev (ev.id)}
      <li>
        <div class="grow">
          <div>{ev.merchant || "–"} <span class="small muted">· {ev.card} · {day(ev.occurred_at.slice(0, 10))}</span></div>
          <div class="small" class:warn={ev.status === "unassigned"}>{STATUS[ev.status] ?? ev.status}{ev.reason ? `: ${ev.reason}` : ""}</div>
          {#if ev.status === "unassigned" && ev.amount_minor !== null && !demo}
            <select onchange={(e) => assign(ev, Number(e.currentTarget.value))} aria-label="Konto zuordnen">
              <option value="">Konto zuordnen …</option>
              {#each accounts as a}<option value={a.id}>{a.name}</option>{/each}
            </select>
          {/if}
        </div>
        <span class="num">{ev.amount_minor !== null ? signed(ev.amount_minor, ev.currency) : "–"}</span>
      </li>
    {/each}
  </ul>
</section>

<style>
  .guide ol { margin: 0; padding-left: 20px; display: grid; gap: 10px; }
  .guide ul { padding-left: 18px; margin: 6px 0 0; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 5px; font-size: 13px; word-break: break-all; }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; }
  .grow { flex: 1; min-width: 0; display: grid; gap: 4px; }
  .warn { color: var(--copper); }
  select { font: inherit; font-size: 15px; background: var(--surface-2); color: var(--ink); border: 0; border-radius: 8px; padding: 6px 8px; }
</style>
