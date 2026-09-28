<script lang="ts">
  import { api, ApiError, getToken, setToken, type Status } from "./lib/api";
  import { route, go } from "./lib/router.svelte";
  import Home from "./views/Home.svelte";
  import Transactions from "./views/Transactions.svelte";
  import Explore from "./views/Explore.svelte";
  import Accounts from "./views/Accounts.svelte";
  import Categories from "./views/Categories.svelte";
  import Pair from "./views/Pair.svelte";
  import ApplePay from "./views/ApplePay.svelte";

  let status = $state<Status | null>(null);
  let error = $state<string | null>(null);
  let unpaired = $state(false);
  let offline = $state(false);

  // Pairing link: #/koppeln/<token>
  $effect(() => {
    if (route.path === "koppeln" && route.parts[1]) {
      setToken(route.parts[1]);
      history.replaceState(null, "", location.pathname);
      go("");
      loadStatus();
    }
  });

  async function loadStatus() {
    try {
      status = await api.get<Status>("/api/status");
      offline = Boolean((status as { __offline?: boolean }).__offline);
      unpaired = false;
    } catch (e) {
      handle(e);
    }
  }

  function handle(e: unknown) {
    if (e instanceof ApiError && e.status === 401) {
      unpaired = true;
      return;
    }
    error = e instanceof Error ? e.message : String(e);
    setTimeout(() => (error = null), 5000);
  }

  loadStatus();

  const tabs = [
    { path: "", label: "Übersicht", icon: "M3 13h4v8H3zM10 3h4v18h-4zM17 9h4v12h-4z" },
    { path: "umsaetze", label: "Umsätze", icon: "M4 6h16M4 12h16M4 18h10" },
    { path: "erkunden", label: "Erkunden", icon: "M3 5h4v14H3zM17 5h4v14h-4zM7 7c5 0 5 5 10 5M7 15c5 0 5-8 10-8" },
    { path: "konten", label: "Konten", icon: "M3 7h18v12H3zM3 11h18M7 15h4" },
  ];
  const titles: Record<string, string> = {
    "": "Finanzen", umsaetze: "Umsätze", erkunden: "Erkunden", konten: "Konten", kategorien: "Kategorien",
  };
</script>

{#if unpaired && !getToken()}
  <Pair />
{:else if unpaired}
  <Pair expired />
{:else}
  <header>
    <h1>{titles[route.path] ?? "Finanzen"}</h1>
    {#if status?.demo}<span class="badge">Demo</span>{/if}
  </header>

  {#if offline}
    <div class="banner">Offline – letzter Stand wird angezeigt.</div>
  {/if}
  {#if status}
    {#each status.warnings as w}
      <button class="banner warn" onclick={() => go("konten")}>
        {#if w.kind === "expired"}Zustimmung für {w.institution} abgelaufen – jetzt erneuern.
        {:else if w.kind === "expiring"}Zustimmung für {w.institution} läuft in {w.days_left} Tagen ab.
        {:else if w.kind === "rate_limited"}{w.institution}: Abruflimit erreicht, nächster Versuch später.
        {:else}{w.institution}: Abruf fehlgeschlagen.{/if}
      </button>
    {/each}
    {#if status.suggestions}
      <button class="banner" onclick={() => go("umsaetze", { vorschlaege: 1 })}>
        {status.suggestions} {status.suggestions === 1 ? "Verknüpfung" : "Verknüpfungen"} zu prüfen
      </button>
    {/if}
  {/if}

  <main>
    {#if route.path === ""}
      <Home onerror={handle} />
    {:else if route.path === "umsaetze"}
      <Transactions onerror={handle} demo={status?.demo ?? false} />
    {:else if route.path === "erkunden"}
      <Explore onerror={handle} />
    {:else if route.path === "konten"}
      <Accounts onerror={handle} demo={status?.demo ?? false} onchange={loadStatus} />
    {:else if route.path === "applepay"}
      <ApplePay onerror={handle} demo={status?.demo ?? false} />
    {:else if route.path === "kategorien"}
      <Categories onerror={handle} demo={status?.demo ?? false} />
    {:else}
      <Home onerror={handle} />
    {/if}
  </main>

  {#if error}<div class="toast" role="alert">{error}</div>{/if}

  <nav aria-label="Hauptnavigation">
    {#each tabs as t}
      <a href="#/{t.path}" aria-current={route.path === t.path ? "page" : undefined}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
        <span>{t.label}</span>
      </a>
    {/each}
  </nav>
{/if}

<style>
  header { display: flex; align-items: center; gap: 10px; padding: calc(var(--safe-top) + 14px) 16px 10px; }
  h1 { font-size: 30px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
  .badge { background: var(--copper-wash); color: var(--copper); font-size: 12px; font-weight: 600;
           padding: 3px 8px; border-radius: 999px; }
  main { padding: 0 16px calc(var(--safe-bottom) + 84px); max-width: 720px; margin: 0 auto; }
  header { max-width: 720px; margin: 0 auto; }
  .banner { all: unset; box-sizing: border-box; display: block; margin: 0 16px 10px; padding: 10px 14px;
            border-radius: 12px; background: var(--accent-wash); color: var(--accent); font-size: 14px;
            cursor: pointer; max-width: 688px; }
  .banner.warn { background: var(--copper-wash); color: var(--copper); }
  @media (min-width: 720px) { .banner { margin: 0 auto 10px; } }
  nav { position: fixed; left: 0; right: 0; bottom: 0; display: flex; justify-content: space-around;
        padding: 6px 8px calc(var(--safe-bottom) + 6px); background: color-mix(in srgb, var(--surface) 88%, transparent);
        backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-top: 1px solid var(--hairline); z-index: 10; }
  nav a { display: grid; justify-items: center; gap: 2px; color: var(--muted); text-decoration: none;
          font-size: 11px; min-width: 64px; padding: 4px 0; }
  nav a[aria-current="page"] { color: var(--accent); }
  nav svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 1.8;
            stroke-linecap: round; stroke-linejoin: round; }
  .toast { position: fixed; left: 16px; right: 16px; bottom: calc(var(--safe-bottom) + 80px); z-index: 20;
           background: var(--ink); color: var(--page); padding: 12px 14px; border-radius: 12px; font-size: 14px; }
</style>
