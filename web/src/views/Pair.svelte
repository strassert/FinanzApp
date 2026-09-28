<script lang="ts">
  let { expired = false }: { expired?: boolean } = $props();
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
  <p class="small muted">Öffne den Link auf dem iPhone in Safari, dann „Teilen“ → „Zum Home-Bildschirm“.
    Die Verbindung läuft nur über dein Tailscale-Netz.</p>
</div>

<style>
  .pair { max-width: 420px; margin: 0 auto; padding: calc(var(--safe-top) + 64px) 24px 24px; text-align: center; }
  img { border-radius: 16px; }
  h1 { margin: 16px 0 8px; }
  pre { background: var(--surface); box-shadow: 0 0 0 1px var(--border); padding: 12px; border-radius: 12px;
        text-align: left; overflow-x: auto; font-size: 14px; }
</style>
