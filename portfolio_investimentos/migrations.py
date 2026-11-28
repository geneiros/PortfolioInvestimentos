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


def _m003_drop_news(conn):
    conn.execute("DROP TABLE IF EXISTS news")


def _m004_other_asset_liquidity(conn):
    # a tabela só existe se já se usou o Património; senão o create_all cria-a com as colunas novas
    if not _columns(conn, "other_asset"):
        return
    _add_column(conn, "other_asset", "liquidity", "VARCHAR(16)")
    _add_column(conn, "other_asset", "home", "BOOLEAN DEFAULT 0")
    _add_column(conn, "other_asset", "linked", "INTEGER")


def _m005_instrument_ter(conn):
    _add_column(conn, "instrument", "ter", "FLOAT")


def _m006_fundamental_more(conn):
    if not _columns(conn, "fundamental"):  # tabela ainda não criada: o create_all cria-a já com as colunas
        return
    for column in ("owner", "nopat", "net_cash", "manual_owner", "manual_nopat", "manual_net_cash"):
        _add_column(conn, "fundamental", column, "FLOAT")


# (versão, descrição, função)
def _m007_watch_rules(conn):
    """As ações do Radar passam a ter parâmetros e alertas (watch_rule); os alertas de preço de cada ativo passam a
    ser parâmetros desse ativo (criado em Acompanhamento se ainda não estava) e o preço-alvo vira «Preço abaixo de»
    sem alerta."""
    _add_column(conn, "watch_item", "method", "VARCHAR(16)")
    _add_column(conn, "watch_item", "criteria", "TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS watch_rule (
        id INTEGER NOT NULL PRIMARY KEY, watch_id INTEGER NOT NULL REFERENCES watch_item (id) ON DELETE CASCADE,
        kind VARCHAR(16) NOT NULL, threshold FLOAT, alert BOOLEAN, met BOOLEAN, state VARCHAR(32),
        triggered_on DATETIME, message VARCHAR(255), creation DATETIME)""")
    now = "datetime('now')"

    def watch_for(ticker):
        row = conn.execute("SELECT id FROM watch_item WHERE instrument = ? ORDER BY id LIMIT 1", (ticker,)).fetchone()
        if row:
            return row[0]
        cur = conn.execute(f"INSERT INTO watch_item (instrument, creation) VALUES (?, {now})", (ticker,))
        return cur.lastrowid
    for wid, target in conn.execute("SELECT id, target_price FROM watch_item WHERE target_price IS NOT NULL").fetchall():
        conn.execute(f"INSERT INTO watch_rule (watch_id, kind, threshold, alert, creation) VALUES (?, 'price_below', ?, 0, "
                     f"{now})", (wid, target))
    if "alert" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
        for ticker, kind, threshold, active, triggered in conn.execute(
                "SELECT instrument, kind, threshold, active, triggered_on FROM alert").fetchall():
            conn.execute(f"INSERT INTO watch_rule (watch_id, kind, threshold, alert, met, triggered_on, creation) "
                         f"VALUES (?, ?, ?, ?, ?, ?, {now})",
                         (watch_for(ticker), kind, threshold, 1 if active or triggered else 0,
                          1 if triggered else None, triggered))
        conn.execute("DELETE FROM alert")


def _m008_watch_lists(conn):
    """Várias listas de acompanhamento: as ações que já havia ficam na primeira («A minha lista»); as Oportunidades
    dão lugar à triagem e os métodos passam a lentes (graham → graham_def)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS watch_list (
        id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(60) NOT NULL, creation DATETIME)""")
    if not _columns(conn, "watch_item"):
        return
    _add_column(conn, "watch_item", "list_id", "INTEGER REFERENCES watch_list (id) ON DELETE CASCADE")
    if conn.execute("SELECT COUNT(*) FROM watch_item").fetchone()[0]:
        cur = conn.execute("INSERT INTO watch_list (title, creation) VALUES ('A minha lista', datetime('now'))")
        conn.execute("UPDATE watch_item SET list_id = ? WHERE list_id IS NULL", (cur.lastrowid,))
    conn.execute("UPDATE watch_item SET method = 'graham_def' WHERE method = 'graham'")


def _m009_watch_board(conn):
    """As listas passam a quadro: estados (colunas) por lista e, em cada ação, o estado, a prioridade, a ordem, o
    «porque entrou» e as notas da leitura (a nota que havia passa para lá). Os estados criam-se ao abrir a lista."""
    conn.execute("""CREATE TABLE IF NOT EXISTS watch_state (
        id INTEGER NOT NULL PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES watch_list (id) ON DELETE CASCADE,
        title VARCHAR(40) NOT NULL, position INTEGER)""")
    if not _columns(conn, "watch_item"):
        return
    _add_column(conn, "watch_item", "state_id", "INTEGER REFERENCES watch_state (id) ON DELETE SET NULL")
    _add_column(conn, "watch_item", "priority", "VARCHAR(8) DEFAULT 'media'")
    _add_column(conn, "watch_item", "position", "INTEGER DEFAULT 0")
    _add_column(conn, "watch_item", "reason", "TEXT")
    _add_column(conn, "watch_item", "notes", "TEXT")
    conn.execute("UPDATE watch_item SET notes = note WHERE notes IS NULL AND note IS NOT NULL")
    conn.execute("UPDATE watch_item SET priority = 'media' WHERE priority IS NULL")


def _m010_broker_country(conn):
    _add_column(conn, "broker", "country", "VARCHAR(2)")


MIGRATIONS = [
    (1, "Resultado indicado pela corretora em cada venda", _m001_transaction_result),
    (2, "Data da última cotação obtida de cada ativo", _m002_instrument_last_quote),
    (3, "Notícias retiradas da aplicação", _m003_drop_news),
    (4, "Património: nível de liquidez, casa própria e crédito ligado ao imóvel", _m004_other_asset_liquidity),
    (5, "Custo anual (TER) de cada ETF", _m005_instrument_ter),
    (6, "Valor de cada ação: owner earnings, NOPAT e caixa líquida", _m006_fundamental_more),
    (7, "Acompanhamento: parâmetros e alertas de cada ação (os alertas de preço passam para lá)", _m007_watch_rules),
    (8, "Prospeção: várias listas de acompanhamento e as lentes da triagem", _m008_watch_lists),
    (9, "Prospeção: as listas em quadro (estados, prioridade, notas)", _m009_watch_board),
    (10, "Fiscal: país da fonte dos juros por corretora", _m010_broker_country),
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
