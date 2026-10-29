"""Versão do esquema da base de dados (`PRAGMA user_version` do SQLite) e passos de migração.

Uma base de dados nova é criada já na versão mais recente. Numa base existente, antes de aplicar passos
pendentes faz-se uma cópia (ver `services/backups.py`) e cada passo corre numa transação própria: se falhar,
a base fica como estava e a aplicação diz onde está a cópia.

Para alterar o esquema: acrescenta uma função ao fim de `MIGRATIONS` (nunca alteres as que já saíram).
Os passos têm de ser idempotentes, porque as bases criadas antes de haver versões têm a versão 0 mas já
podem ter algumas destas alterações.
"""
import sqlite3

from sqlalchemy import inspect

from .models import db


def _columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _add_column(conn, table, column, sql_type):
    if column not in _columns(conn, table):
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {sql_type}')


def _m001_transaction_result(conn):
    _add_column(conn, "transaction", "result", "FLOAT")


def _m002_instrument_last_quote(conn):
    _add_column(conn, "instrument", "last_quote", "DATE")


# (versão, descrição, função)
MIGRATIONS = [
    (1, "Resultado indicado pela corretora em cada venda", _m001_transaction_result),
    (2, "Data da última cotação obtida de cada ativo", _m002_instrument_last_quote),
]
LATEST = MIGRATIONS[-1][0]


class MigrationError(RuntimeError):
    pass


def schema_version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _run_step(path, version, fn):
    """Um passo numa transação (BEGIN explícito: o sqlite3 não abre uma para o DDL)."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("BEGIN")
        try:
            fn(conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def upgrade(app):
    """Cria o esquema (base nova) ou leva uma base existente à versão mais recente."""
    from .services import backups
    path = app.config["DB_PATH"]
    if not inspect(db.engine).has_table("transaction"):
        db.create_all()
        _set_version(path, LATEST)
        return
    version = schema_version(path)
    if version > LATEST:
        raise MigrationError(
            f"A base de dados é de uma versão mais recente da aplicação (esquema {version}, esta suporta até "
            f"{LATEST}). Atualiza a aplicação antes de a abrir.")
    pending = [m for m in MIGRATIONS if m[0] > version]
    if pending:
        db.engine.dispose()
        saved = backups.make_backup(path, f"migracao-v{version}-v{LATEST}")
        for number, description, fn in pending:
            try:
                _run_step(path, number, fn)
            except Exception as exc:
                raise MigrationError(f"Falhou a atualização da base de dados (passo {number}: {description}): "
                                     f"{exc}. A base ficou como estava; há uma cópia em {saved}.") from exc
    db.create_all()  # tabelas novas (não mexe nas que já existem)


def _set_version(path, version):
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
    finally:
        conn.close()
