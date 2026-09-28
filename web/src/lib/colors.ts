// Colour follows the entity (category/account slot), never its rank.
export const SLOTS = 8;

export function slotVar(slot: number | null | undefined): string {
  if (slot == null || slot < 0 || slot >= SLOTS) return "var(--other)";
  return `var(--s${slot + 1})`;
}

export function hasOwnColor(slot: number | null | undefined): boolean {
  return slot != null && slot >= 0 && slot < SLOTS;
}
