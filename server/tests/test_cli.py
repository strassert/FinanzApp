import waitress

from finanzen.cli import main


def test_serve_starts_without_bank_key(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'db_path = "{(tmp_path / "f.db").as_posix()}"\n'
                   f'private_key_path = "{(tmp_path / "missing.pem").as_posix()}"\n')
    served = []
    monkeypatch.setattr(waitress, "serve", lambda app, **kw: served.append(app))

    assert main(["--config", str(cfg), "serve"]) == 0
    assert len(served) == 1
    assert "kein Bankzugang" in capsys.readouterr().err
