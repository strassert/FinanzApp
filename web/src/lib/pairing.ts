// Pairing token from what the user pastes: the full link (…/#/koppeln/<token>)
// or the bare token. The home-screen app on iOS has its own storage, separate
// from Safari, so it has to be paired from inside the app.

const TOKEN = /^[A-Za-z0-9_-]{20,}$/;

export function tokenFromInput(input: string): string | null {
  const text = input.trim();
  const match = text.match(/#\/koppeln\/([^/?#\s]+)/);
  const token = match ? match[1] : text;
  return TOKEN.test(token) ? token : null;
}
