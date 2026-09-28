<script lang="ts">
  import { api, type Category, type Rule } from "../lib/api";
  import { slotVar } from "../lib/colors";

  let { onerror, demo = false }: { onerror: (e: unknown) => void; demo?: boolean; onchange?: () => void } = $props();

  let categories = $state<Category[]>([]);
  let rules = $state<Rule[]>([]);
  let newName = $state("");
  let newKind = $state("expense");
  let rulePattern = $state("");
  let ruleCategory = $state<number | null>(null);

  async function load() {
    try {
      const data = await api.get<{ items: Category[]; rules: Rule[] }>("/api/categories");
      categories = data.items;
      rules = data.rules;
    } catch (e) {
      onerror(e);
    }
  }
  load();

  async function addCategory() {
    try {
      await api.post("/api/categories", { name: newName.trim(), kind: newKind });
      newName = "";
      load();
    } catch (e) {
      onerror(e);
    }
  }

  async function addRule() {
    try {
      await api.post("/api/rules", { pattern: rulePattern.trim(), category_id: ruleCategory });
      rulePattern = "";
      load();
    } catch (e) {
      onerror(e);
    }
  }

  async function removeRule(id: number) {
    try {
      await api.del(`/api/rules/${id}`);
      load();
    } catch (e) {
      onerror(e);
    }
  }

  const groups = $derived([
    { title: "Ausgaben", items: categories.filter((c) => c.kind === "expense") },
    { title: "Einnahmen", items: categories.filter((c) => c.kind === "income") },
  ]);
</script>

<p class="small muted">Vorrang bei der Zuordnung: deine Wahl am Umsatz → Umbuchung → deine Regeln → erkannte Händler → Kartencode (MCC) → „Sonstiges“.</p>

<section class="card">
  <h2>Eigene Regeln</h2>
  {#if rules.length}
    <ul class="rows">
      {#each rules as r (r.id)}
        <li><span class="grow">Text enthält <strong>{r.pattern}</strong> → {r.category}</span>
          <button class="remove" disabled={demo} onclick={() => removeRule(r.id)} aria-label="Regel löschen">✕</button></li>
      {/each}
    </ul>
  {:else}
    <p class="small muted">Noch keine. Regeln entstehen auch beim Ändern der Kategorie eines Umsatzes.</p>
  {/if}
  <div class="add">
    <input type="text" placeholder="Text enthält …" bind:value={rulePattern} disabled={demo} />
    <select bind:value={ruleCategory} disabled={demo} aria-label="Kategorie">
      <option value={null}>Kategorie</option>
      {#each categories as c}<option value={c.id}>{c.name}</option>{/each}
    </select>
    <button disabled={demo || rulePattern.trim().length < 3 || ruleCategory === null} onclick={addRule}>Hinzufügen</button>
  </div>
</section>

{#each groups as g}
  <section class="card">
    <h2>{g.title}</h2>
    <ul class="rows">
      {#each g.items as c (c.id)}
        <li><span class="swatch" style:background={c.kind === "expense" ? slotVar(c.color_slot) : "var(--s1)"}></span>
          <span class="grow">{c.name}</span>
          {#if c.kind === "expense" && (c.color_slot ?? 99) >= 8}<span class="small muted">in „Weitere“</span>{/if}</li>
      {/each}
    </ul>
  </section>
{/each}

<section class="card">
  <h2>Neue Kategorie</h2>
  <div class="add">
    <input type="text" placeholder="Name" bind:value={newName} disabled={demo} />
    <select bind:value={newKind} disabled={demo} aria-label="Art">
      <option value="expense">Ausgabe</option><option value="income">Einnahme</option>
    </select>
    <button disabled={demo || !newName.trim()} onclick={addCategory}>Anlegen</button>
  </div>
</section>

<style>
  p { margin: 0 4px 12px; }
  .rows { list-style: none; margin: 0; padding: 0; }
  .rows li { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-top: 1px solid var(--hairline); }
  .rows li:first-child { border-top: 0; padding-top: 0; }
  .grow { flex: 1; min-width: 0; }
  .remove { border: 0; background: var(--surface-2); width: 30px; height: 30px; border-radius: 50%; cursor: pointer; }
  .add { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .add input, .add select { flex: 1 1 140px; font: inherit; font-size: 16px; color: var(--ink); background: var(--surface-2);
    border: 0; border-radius: 10px; padding: 10px 12px; min-width: 0; }
  .add button { border: 0; border-radius: 10px; padding: 10px 14px; background: var(--accent); color: var(--accent-ink);
    font-weight: 600; cursor: pointer; }
  button:disabled { opacity: .45; cursor: default; }
</style>
