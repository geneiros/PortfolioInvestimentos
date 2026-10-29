"""Cópias de segurança automáticas da base de dados (API de backup do SQLite, consistente com escritas em curso).

As cópias ficam em `<pasta dos dados>/copias/portfolio-AAAAMMDD-HHMMSS-<motivo>.db`; guardam-se as últimas 10.
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

KEEP = 10
_NAME = re.compile(r"^portfolio-(\d{8})-(\d{6})-([a-z0-9-]+)\.db$")
REASONS = {
    "importar": "Antes de importar", "apagar-tudo": "Antes de apagar tudo", "demonstracao": "Antes da demonstração",
    "apagar-importacao": "Antes de apagar uma importação", "restaurar": "Antes de restaurar uma cópia",
    "manual": "Pedida por ti",
}


def folder(db_path):
    return Path(db_path).parent / "copias"


def make_backup(db_path, reason="manual", keep=KEEP):
    """Grava uma cópia consistente e apaga as mais antigas; devolve o caminho."""
    dest_dir = folder(db_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9-]+", "-", reason.lower()).strip("-") or "manual"
    dest, n = dest_dir / f"portfolio-{stamp}-{slug}.db", 1
    while dest.exists():  # duas cópias no mesmo segundo
        n += 1
        dest = dest_dir / f"portfolio-{stamp}-{slug}-{n}.db"
    src, dst = sqlite3.connect(db_path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    except Exception:
        dst.close()
        dest.unlink(missing_ok=True)
        raise
    finally:
        src.close()
        dst.close()
    for old in _ordered(dest_dir)[:-keep]:
        old.unlink(missing_ok=True)
    return dest


def _ordered(dest_dir):
    """Cópias da mais antiga para a mais recente (a data do nome; no mesmo segundo, a ordem de criação)."""
    files = [p for p in dest_dir.glob("portfolio-*.db") if _NAME.match(p.name)]
    return sorted(files, key=lambda p: (_NAME.match(p.name).group(1, 2), p.stat().st_mtime_ns))


def list_backups(db_path):
    """As cópias existentes, da mais recente para a mais antiga."""
    out = []
    for p in reversed(_ordered(folder(db_path))):
        m = _NAME.match(p.name)
        when = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        reason = re.sub(r"-\d+$", "", m.group(3))
        label = REASONS.get(reason) or ("Antes de atualizar a base de dados" if reason.startswith("migracao") else reason)
        out.append(SimpleNamespace(name=p.name, when=when, label=label, size=p.stat().st_size))
    return out


def backup_path(db_path, name):
    """Caminho de uma cópia pelo nome (só nomes gerados aqui, dentro da pasta das cópias)."""
    p = folder(db_path) / name
    if not _NAME.match(name) or not p.is_file():
        raise FileNotFoundError(name)
    return p


def restore(db_path, name):
    """Substitui o conteúdo da base de dados pela cópia (feita uma cópia do estado atual antes)."""
    src_path = backup_path(db_path, name)
    probe = sqlite3.connect(src_path)
    try:
        if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("a cópia está danificada")
        probe.execute('SELECT 1 FROM "transaction" LIMIT 1')
    finally:
        probe.close()
    make_backup(db_path, "restaurar")
    src, dst = sqlite3.connect(src_path), sqlite3.connect(db_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def auto_backup(reason):
    """Cópia antes de uma operação que muda muitos dados; não se faz se não há dados reais a proteger."""
    from flask import current_app

    from ..models import Setting, Transaction
    if Setting.get("demo") == "1" or Transaction.query.first() is None:
        return None
    return make_backup(current_app.config["DB_PATH"], reason)
