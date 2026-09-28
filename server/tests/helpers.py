"""Query helpers for tests."""


def tx(conn, ref=None, text=None, account=None):
    sql = """SELECT t.*, d.role, d.category_id, d.category_source, d.amount_eur_minor,
                    c.name AS category, a.name AS account
             FROM transactions t LEFT JOIN tx_derived d ON d.tx_id = t.id
             LEFT JOIN categories c ON c.id = d.category_id
             JOIN accounts a ON a.id = t.account_id WHERE 1=1"""
    args = []
    if ref:
        sql += " AND t.ext_id = ?"
        args.append(ref)
    if text:
        sql += " AND (t.description LIKE ? OR t.counterparty LIKE ?)"
        args += [f"%{text}%", f"%{text}%"]
    if account:
        sql += " AND a.institution = ?"
        args.append(account)
    return [dict(r) for r in conn.execute(sql + " ORDER BY t.booking_date, t.id", args)]


def one(conn, **kw):
    rows = tx(conn, **kw)
    assert len(rows) == 1, f"expected one row for {kw}, got {len(rows)}"
    return rows[0]


def links_of(conn, tx_id):
    return [dict(r) for r in conn.execute("SELECT * FROM links WHERE a_id=? OR b_id=?", (tx_id, tx_id))]
