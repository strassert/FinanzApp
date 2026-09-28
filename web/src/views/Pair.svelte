<script lang="ts">
  import { setToken } from "../lib/api";
  import { tokenFromInput } from "../lib/pairing";

  let { expired = false }: { expired?: boolean } = $props();
  let input = $state("");
  let invalid = $state(false);

  function pair(e: SubmitEvent) {
    e.preventDefault();
    const token = tokenFromInput(input);
    invalid = token === null;
    if (token) {
      setToken(token);
      location.replace(location.pathname);
    }
  }
</script>

<div class="pair">
  <img src="/icon.svg" alt="" width="72" height="72" />
  <h1>Finanzen</h1>
  {#if expired}
    <p>Die Kopplung ist nicht mehr gültig. Erzeuge auf dem Server einen neuen Link:</p>
  {:else}
    <p>Diese App ist noch nicht mit deinem Server gekoppelt. Erzeuge auf dem Server einen Kopplungslink:</p>
  {/if}
  <pre>sudo -u finanzen finanzen pair</pre>
  <form onsubmit={pair}>
    <label for="pairing">Kopplungslink hier einfügen</label>
    <input id="pairing" bind:value={input} autocomplete="off" autocapitalize="off" spellcheck="false"
           placeholder="https://…/#/koppeln/…" aria-invalid={invalid} />
    {#if invalid}<p class="small error">Das ist kein gültiger Kopplungslink.</p>{/if}
    <button type="submit" disabled={!input.trim()}>Koppeln</button>
  </form>
  <p class="small muted">Die App auf dem Home-Bildschirm hat eigenen Speicher, getrennt von Safari:
    Link kopieren, die App öffnen und hier einfügen. Die Verbindung läuft nur über dein Tailscale-Netz.</p>
</div>

<style>
  .pair { max-width: 420px; margin: 0 auto; padding: calc(var(--safe-top) + 64px) 24px 24px; text-align: center; }
  img { border-radius: 16px; }
  h1 { margin: 16px 0 8px; }
  pre { background: var(--surface); box-shadow: 0 0 0 1px var(--border); padding: 12px; border-radius: 12px;
        text-align: left; overflow-x: auto; font-size: 14px; }
  form { display: grid; gap: 8px; margin: 20px 0 8px; text-align: left; }
  label { font-size: 14px; font-weight: 600; }
  input { font: inherit; font-size: 16px; padding: 12px; border-radius: 12px; border: 1px solid var(--border);
          background: var(--surface); color: var(--ink); min-width: 0; }
  button { font: inherit; font-weight: 600; padding: 12px; border-radius: 12px; border: 0;
           background: var(--accent); color: var(--page); }
  button:disabled { opacity: 0.5; }
  .error { color: var(--copper); margin: 0; }
</style>
