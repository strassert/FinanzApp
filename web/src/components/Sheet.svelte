<script lang="ts">
  // Bottom sheet (modal dialog) for details and forms.
  import type { Snippet } from "svelte";

  let { title, onclose, children }: { title: string; onclose: () => void; children: Snippet } = $props();
  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => dialog.close();
  });
</script>

<dialog bind:this={dialog} onclose={onclose} onclick={(e) => e.target === dialog && onclose()} aria-label={title}>
  <div class="sheet">
    <div class="head">
      <h2>{title}</h2>
      <button class="close" onclick={onclose} aria-label="Schließen">✕</button>
    </div>
    {@render children()}
  </div>
</dialog>

<style>
  dialog { border: 0; padding: 0; margin: auto auto 0; width: 100%; max-width: 640px; max-height: 92vh;
           background: transparent; color: var(--ink); }
  dialog::backdrop { background: rgba(0, 0, 0, 0.35); }
  .sheet { background: var(--page); border-radius: 20px 20px 0 0; padding: 16px 16px calc(var(--safe-bottom) + 20px);
           max-height: 92vh; overflow-y: auto; }
  .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  h2 { font-size: 20px; margin: 0; }
  .close { border: 0; background: var(--surface-2); width: 32px; height: 32px; border-radius: 50%; cursor: pointer; }
</style>
