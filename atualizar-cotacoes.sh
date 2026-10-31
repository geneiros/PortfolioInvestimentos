#!/usr/bin/env bash
# Atualiza as cotações, câmbios e notícias e sai (para uma consola Bash ou uma tarefa agendada, ex.: PythonAnywhere).
#   bash atualizar-cotacoes.sh            (todos os ativos)
#   bash atualizar-cotacoes.sh --abertas  (só as posições abertas)
# Variáveis (opcionais):
#   VENV                 virtualenv a usar (por omissão ~/.virtualenvs/pi)
#   PORTFOLIO_DATA_DIR   pasta dos dados (por omissão ~/dados; tem de ser a mesma da aplicação web)
set -e
cd "$(dirname "$0")"
VENV=${VENV:-$HOME/.virtualenvs/pi}
if [ ! -x "$VENV/bin/python" ]; then
  echo "Não encontrei o virtualenv em $VENV. Indica o caminho com VENV=... bash atualizar-cotacoes.sh"
  exit 1
fi
export PORTFOLIO_DATA_DIR=${PORTFOLIO_DATA_DIR:-$HOME/dados}
exec "$VENV/bin/python" -m portfolio_investimentos --refresh "$@"
