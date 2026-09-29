<script lang="ts">
  import { api, type Account } from "../lib/api";
  import { day, dayLongFmt, eur, eurCents } from "../lib/format";
  import { slotVar } from "../lib/colors";
  import { ACCOUNT_KIND } from "../lib/labels";
  import { go } from "../lib/router.svelte";
  import Sheet from "../components/Sheet.svelte";
  import Import from "../components/Import.svelte";

  let { onerror, demo = false, onchange }: { onerror: (e: unknown) => void; demo?: boolean; onchange?: () => void } = $props();

  interface Connection { id: number; institution: string; status: string; valid_until: string | null;
    last_sync_at: string | null; last_error: string | null; paused_until: string | null }
  let accounts = $state<Account[]>([]);
  let connections = $state<Connection[]>([]);
  let editing = $state<Account | null>(null);
  let adding = $state<"bank" | "manual" | null>(null);
  let importing = $state(false);
  let institutions = $state<{ name: string; max_consent_days: number | null }[]>([]);
  let bankFilter = $state("");
  let syncing = $state(false);
  let form = $state({ name: "", patterns: "", balance: "", kind: "depot" });

  async function load() {
    try {
      const data = await api.get<{ items: Account[]; connections: Connection[] }>("/api/accounts");
      accounts = data.items;
      connections = data.connections;
    } catch (e) {
      onerror(e);
    }
  }
  load();

  function daysLeft(iso: string | null): number | null {
    return iso ? Math.floor((Date.parse(iso) - Date.now()) / 86400000) : null;
  }

  async function syncNow() {
    syncing = true;
    try {
      await api.post("/api/sync", {});
      await load();
      onchange?.();
    } catch (e) {
      onerror(e);
    } finally {
      syncing = false;
    }
  }

  async function startConsent(institution: string, renewId?: number, maxDays?: number | null) {
    try {
      const { url } = await api.post<{ url: string }>("/api/connections",
        { institution, renew_connection_id: renewId, max_consent_days: maxDays ?? undefined });
      // Bank apps refuse to switch from embedded views: open the consent in the real browser.
      window.open(url, "_blank", "noopener");
      adding = null;
    } catch (e) {
      onerror(e);
    }
  }

  async function openBankList() {
    adding = "bank";
    if (!institutions.length) {
      try {
        institutions = (await api.get<{ items: typeof institutions }>("/api/institutions")).items;
      } catch (e) {
        onerror(e);
      }
    }
  }

  function edit(a: Account) {
    editing = a;
    form = { name: a.name, patterns: a.patterns, balance: "", kind: a.kind };
  }

  function toCents(text: string): number | null {
    const clean = text.replace(/\s|€/g, "").replace(/\./g, "").replace(",", ".").replace("−", "-");
    const v = Number(clean);
    return Number.isFinite(v) && clean !== "" ? Math.round(v * 100) : null;
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await api.patch(`/api/accounts/${editing.id}`, { name: form.name, patterns: form.patterns });
      const cents = toCents(form.balance);
      if (editing.source !== "api" && cents !== null) {
        await api.post(`/api/accounts/${editing.id}/balance`, { amount: cents });
      }
      editing = null;
      load();
    } catch (e) {
      onerror(e);
    }
  }

  async function hide(a: Account) {
    try {
      await api.patch(`/api/accounts/${a.id}`, { hidden: true });
      editing = null;
      load();
    } catch (e) {
      onerror(e);
    }
  }

  async function addManual() {
    try {
      const { id } = await api.post<{ id: number }>("/api/accounts",
        { name: form.name, kind: form.kind, patterns: form.patterns });
      const cents = toCents(form.balance);
      if (cents !== null) await api.post(`/api/accounts/${id}/balance`, { amount: cents });
      adding = null;
      load();
    } catch (e) {
      onerror(e);
    }
  }

  const filtered = $derived(institutions.filter((i) => i.name.toLowerCase().includes(bankFilter.toLowerCase())));
</script>

<div class="actions">
  <button class="primary" disabled={demo || syncing} onclick={syncNow}>{syncing ? "Aktualisiere …" : "Jetzt aktualisieren"}</button>
  <button disabled={demo} onclick={openBankList}>Bank verbinden</button>
</div>

{#if connections.length}
  <section class="card">
    <h2>Bankverbindungen</h2>
    <ul class="rows">
      {#each connections as c (c.id)}
        {@const left = daysLeft(c.valid_until)}
        <li>
          <div class="grow">
            <div>{c.institution}</div>
            <div class="small muted">
              {#if c.status === "expired"}<span class="warn">Zustimmung abgelaufen</span>
              {:else if left !== null && left <= 14}<span class="warn">läuft in {Math.max(0, left)} Tagen ab</span>
              {:else if c.valid_until}gültig bis {day(c.valid_until.slice(0, 10))}{/if}
              {#if c.last_sync_at} · abgerufen {day(c.last_sync_at.slice(0, 10))} {c.last_sync_at.slice(11, 16)}{/if}
              {#if c.last_error === "rate_limited"} · Abruflimit, pausiert{/if}
            </div>
          </div>
          {#if c.status === "expired" || (left !== null && left <= 14)}
            <button class="small-btn" disabled={demo} onclick={() => startConsent(c.institution, c.id)}>Erneuern</button>
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/if}

<section class="card">
  <h2>Konten</h2>
  <ul class="rows">
    {#each accounts as a (a.id)}
      <li>
        <button class="row" onclick={() => edit(a)}>
          <span class="dot" style:background={slotVar(a.color_slot)}></span>
          <span class="grow">
            <span>{a.name}</span>
            <span class="small muted">{ACCOUNT_KIND[a.kind] ?? a.kind}{a.iban ? ` · ${a.iban}` : ""}{a.source !== "api" ? " · ohne Bankanbindung" : ""}</span>
          </span>
          <span class="num right" class:neg={(a.balance ?? 0) < 0}>
            {a.balance !== null ? eurCents(a.balance, a.currency) : "–"}
            {#if a.currency !== "EUR" && a.balance_eur !== null}<span class="small muted">{eur(a.balance_eur)}</span>{/if}
          </span>
        </button>
      </li>
    {/each}
  </ul>
  <button class="link" disabled={demo} onclick={() => { adding = "manual"; form = { name: "", patterns: "", balance: "", kind: "depot" }; }}>
    + Konto ohne Bankanbindung (z. B. Depot)</button>
</section>

<section class="card">
  <h2>Weiteres</h2>
  <ul class="rows">
    <li><a class="row" href="#/fixkosten"><span class="grow">Fixkosten und regelmäßige Zahlungen</span><span class="muted">›</span></a></li>
    <li><button class="row" onclick={() => go("kategorien")}><span class="grow">Kategorien und Regeln</span><span class="muted">›</span></button></li>
    <li><button class="row" disabled={demo} onclick={() => (importing = true)}><span class="grow">Datei importieren (CSV, Excel)</span><span class="muted">›</span></button></li>
    <li><a class="row" href="#/applepay"><span class="grow">Apple Pay sofort erfassen</span><span class="muted">›</span></a></li>
  </ul>
</section>

{#if editing}
  <Sheet title={editing.name} onclose={() => (editing = null)}>
    <div class="card form">
      <label>Name <input type="text" bind:value={form.name} disabled={demo} /></label>
      <label>Muster für Umbuchungen <input type="text" bind:value={form.patterns} disabled={demo} placeholder="z. B. PAYPAL, PAYLIFE" /></label>
      <p class="small muted">Taucht eines dieser Wörter im Buchungstext eines anderen Kontos auf, gilt die Buchung als Umbuchung auf dieses Konto. Mehrere mit Komma trennen.</p>
      {#if editing.source !== "api"}
        <label>{editing.kind === "depot" ? "Depotwert heute" : editing.kind === "card" ? "Offener Betrag (negativ)" : "Saldo heute"}
          <input type="text" inputmode="decimal" bind:value={form.balance} disabled={demo} placeholder="z. B. 12.345,67" /></label>
      {/if}
      {#if editing.valid_until}<p class="small muted">Zustimmung gültig bis {dayLongFmt(editing.valid_until.slice(0, 10))}</p>{/if}
      <button class="primary" disabled={demo} onclick={saveEdit}>Speichern</button>
      <button class="link danger" disabled={demo} onclick={() => editing && hide(editing)}>Konto ausblenden</button>
    </div>
  </Sheet>
{/if}

{#if adding === "manual"}
  <Sheet title="Konto ohne Bankanbindung" onclose={() => (adding = null)}>
    <div class="card form">
      <label>Name <input type="text" bind:value={form.name} placeholder="z. B. flatex Depot" /></label>
      <label>Art
        <select bind:value={form.kind}>
          <option value="depot">Depot</option><option value="savings">Sparkonto</option>
          <option value="card">Kreditkarte</option><option value="other">Sonstiges</option>
        </select></label>
      <label>Muster für Umbuchungen <input type="text" bind:value={form.patterns} placeholder={form.kind === "depot" ? "WP-KAUF, WP-VERKAUF" : ""} /></label>
      <label>{form.kind === "depot" ? "Aktueller Depotwert" : "Aktueller Saldo"}
        <input type="text" inputmode="decimal" bind:value={form.balance} placeholder="z. B. 12.345,67" /></label>
      <button class="primary" disabled={!form.name.trim()} onclick={addManual}>Anlegen</button>
    </div>
  </Sheet>
{/if}

{#if adding === "bank"}
  <Sheet title="Bank verbinden" onclose={() => (adding = null)}>
    <input class="search" type="search" placeholder="Bank suchen" bind:value={bankFilter} />
    <p class="small muted">Die Zustimmung öffnet sich im Browser. Danach kehrst du hierher zurück; die Umsätze werden sofort geladen.</p>
    <ul class="card rows">
      {#each filtered as i}
        <li><button class="row" onclick={() => startConsent(i.name, undefined, i.max_consent_days)}><span class="grow">{i.name}</span><span class="muted">›</span></button></li>
      {:else}
        <li class="muted small">Keine Bank gefunden.</li>
      {/each}
    </ul>
  </Sheet>
{/if}

{#if importing}
  <Import {accounts} {onerror} onclose={(done) => { importing = false; if (done) load(); }} />
{/if}

<style>
  .actions { display: flex; gap: 8px; margin-bottom: 12px; }
  .actions button, .primary { flex: 1; border: 0; border-radius: 12px; padding: 12px; cursor: pointer; font-weight: 600;
    background: var(--surface); color: var(--ink); box-shadow: 0 0 0 1px var(--border); }
  .primary { background: var(--accent) !important; color: var(--accent-ink) !important; box-shadow: none !important; }
  button:disabled { opacity: .5; cursor: default; }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; padding-top: 0; }
  .row { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 10px; width: 100%; cursor: pointer; color: var(--ink); }
  .grow { flex: 1; min-width: 0; display: grid; }
  .right { text-align: right; display: grid; }
  .neg { color: var(--bad); }
  .warn { color: var(--copper); font-weight: 600; }
  .small-btn { border: 0; border-radius: 999px; padding: 6px 12px; background: var(--copper-wash); color: var(--copper); font-weight: 600; cursor: pointer; }
  .link { all: unset; color: var(--accent); cursor: pointer; margin-top: 12px; display: inline-block; }
  .link.danger { color: var(--bad); }
  .form { display: grid; gap: 12px; }
  .form label { display: grid; gap: 4px; font-size: 14px; color: var(--ink-2); }
  .form p { margin: -6px 0 0; }
  input, select { font: inherit; font-size: 16px; color: var(--ink); background: var(--surface-2); border: 0;
                  border-radius: 10px; padding: 10px 12px; width: 100%; }
  .search { margin-bottom: 8px; background: var(--surface); box-shadow: 0 0 0 1px var(--border); }
</style>
