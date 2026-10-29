#!/usr/bin/env bash
# Inicia o Portfolio Investimentos (macOS / Linux). Na primeira vez prepara o ambiente Python.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10 ou superior não encontrado. Instala-o em https://www.python.org/downloads/"
  exit 1
fi
# o marcador é uma cópia de requirements.txt, criada só depois de a instalação terminar:
# reinstala se a instalação anterior foi interrompida ou se a lista de dependências mudou
if [ ! -x .venv/bin/python ]; then
  echo "A preparar o ambiente (só na primeira vez)..."
  "$PY" -m venv .venv
fi
if ! cmp -s requirements.txt .venv/.pronto; then
  echo "A instalar as dependências..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || .venv/bin/python -m pip install Flask Flask-SQLAlchemy waitress openpyxl tzdata
  cp requirements.txt .venv/.pronto
fi
exec .venv/bin/python -m portfolio_investimentos "$@"
