// German texts for server codes.

export const EVIDENCE: Record<string, string> = {
  iban: "Die Buchung nennt die IBAN eines eigenen Kontos.",
  pattern: "Der Buchungstext passt zum Muster eines eigenen Kontos.",
  owner: "Die Gegenseite bist du selbst (Kontoinhaber).",
  amount: "Gleicher Betrag auf einem anderen eigenen Konto binnen 3 Tagen.",
  merchant: "Gutschrift desselben Händlers nach einem Kauf.",
  wallet: "Apple-Pay-Meldung und Bankbuchung derselben Zahlung.",
  import: "Gleicher Betrag aus Datei-Import und Bankabruf.",
  user: "Von dir bestätigt.",
};

export const LINK_KIND: Record<string, string> = {
  transfer: "Umbuchung",
  paypal: "Bezahlt über PayPal",
  refund: "Erstattung",
  duplicate: "Duplikat",
  wallet: "Apple-Pay-Meldung",
};

export const ROLE: Record<string, string> = {
  expense: "Ausgabe",
  income: "Einnahme",
  transfer: "Umbuchung – zählt nicht",
  excluded: "Nicht mitgezählt",
};

export const CATEGORY_SOURCE: Record<string, string> = {
  user: "von dir gewählt",
  transfer: "Umbuchung",
  rule: "eigene Regel",
  confirmed: "von dir für diesen Händler bestätigt",
  learned: "KI, aus deinen Zuordnungen gelernt",
  ai: "KI, vom Sprachmodell vorgeschlagen",
  keyword: "Händler erkannt",
  mcc: "Kartencode (MCC)",
  refund: "wie der ursprüngliche Kauf",
  default: "nicht erkannt",
  split: "größte Position der Bestellung",
  order: "Online-Bestellung",
};

export const ACCOUNT_KIND: Record<string, string> = {
  giro: "Girokonto", card: "Kreditkarte", paypal: "PayPal", broker: "Verrechnungskonto",
  depot: "Depot", savings: "Sparkonto", other: "Sonstiges",
};
