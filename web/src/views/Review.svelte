<script lang="ts">
  // KI suggestions per merchant: confirm ("Passt") or pick another category ("Ändern").
  import { api, type Category, type ReviewItem } from "../lib/api";
  import { day, signed } from "../lib/format";
  import { slotVar } from "../lib/colors";

  let { onerror, demo = false, onchange }: {
    onerror: (e: unknown) => void; demo?: boolean; onchange?: () => void;
  } = $props();

  let items = $state<ReviewItem[] | null>(null);
  let categories = $state<Category[]>([]);
  let changing = $state<string | null>(null);

  async function load() {
    try {
      const [r, c] = await Promise.all([
        api.get<{ items: ReviewItem[] }>("/api/review"),
        api.get<{ items: Category[] }>("/api/categories"),
      ]);
      items = r.items;
      categories = c.items;
    } catch (e) {
      onerror(e);
    }
  }
  load();

  async function decide(item: ReviewItem, categoryId: number) {
    try {
      items = (await api.post<{ items: ReviewItem[] }>("/api/review", { key: item.key, category_id: categoryId })).items;
      changing = null;
      onchange?.();
    } catch (e) {
      onerror(e);
    }
  }

  const choices = (item: ReviewItem) =>
    categories.filter((c) => c.kind === (item.key.startsWith("+:") ? "income" : "expense"));
</script>

<p class="small muted intro">Diese Kategorien hat die App selbst vorgeschlagen. „Passt“ übernimmt sie für alle Buchungen
  dieses Händlers, auch künftige. Deine Antworten helfen beim Lernen.</p>

{#if items}
  <ul class="list">
    {#each items as item (item.key)}
      <li class="card">
        <div class="top">
          <span class="dot" style:background={slotVar(item.category.color_slot)}></span>
          <span class="grow">
            <span class="name">{item.name}</span>
            <span class="small muted">
              {item.category.name} <span class="ki">KI</span>
              · {item.source === "learned" && item.hint ? `gelernt von „${item.hint}“` : "Sprachmodell"}
            </span>
            <span class="small muted">{item.count} {item.count === 1 ? "Buchung" : "Buchungen"}, zuletzt {day(item.last_date)} · {signed(item.total)}</span>
          </span>
        </div>
        {#if changing === item.key}
          <select aria-label="Kategorie für {item.name}" disabled={demo}
                  onchange={(e) => decide(item, Number(e.currentTarget.value))}>
            <option value="" selected disabled>Kategorie wählen …</option>
            {#each choices(item) as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
          </select>
        {:else}
          <div class="actions">
            <button class="yes" disabled={demo} onclick={() => decide(item, item.category.id)}>Passt</button>
            <button disabled={demo} onclick={() => (changing = item.key)}>Ändern</button>
          </div>
        {/if}
      </li>
    {:else}
      <li class="card muted">Keine offenen Vorschläge.</li>
    {/each}
  </ul>
{:else}
  <div class="card muted">Lade …</div>
{/if}

<style>
  .intro { margin: 0 0 12px; }
  .list { list-style: none; margin: 0; padding: 0; }
  .list li { display: grid; gap: 12px; }
  .top { display: flex; gap: 10px; align-items: flex-start; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; margin-top: 7px; }
  .grow { flex: 1; min-width: 0; display: grid; gap: 1px; }
  .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ki { font-size: 10px; font-weight: 700; color: var(--s4); background: color-mix(in srgb, var(--s4) 14%, transparent);
        border-radius: 5px; padding: 1px 5px; }
  .actions { display: flex; gap: 8px; }
  .actions button { flex: 1; border: 0; border-radius: 12px; padding: 10px; cursor: pointer; font-weight: 600;
                    background: var(--surface-2); color: var(--ink); }
  .actions .yes { background: var(--accent); color: var(--accent-ink); }
  button:disabled { opacity: .5; cursor: default; }
  select { font: inherit; font-size: 16px; color: var(--ink); background: var(--surface-2); border: 0;
           border-radius: 10px; padding: 10px 12px; width: 100%; }
</style>
