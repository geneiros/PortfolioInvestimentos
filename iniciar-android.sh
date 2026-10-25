#!/data/data/com.termux/files/usr/bin/bash
# Inicia o Portfolio Investimentos no Android, dentro do Termux (https://f-droid.org/packages/com.termux/).
# Na primeira vez instala o Python e as dependências; depois abre a aplicação no browser do telemóvel.
#
#   bash iniciar-android.sh               arranca e abre o browser
#   bash iniciar-android.sh --atualizar   descarrega a versão mais recente (git pull) e arranca
#   PORT=8080 bash iniciar-android.sh     usa outra porta
#   bash iniciar-android.sh --importar ~/storage/downloads/ficheiro.xlsx   importa um extrato e sai
#
# O yfinance não é instalado (a dependência curl_cffi não compila no Android): a atualização de
# cotações usa o acesso direto ao Yahoo Finance, só com a biblioteca padrão do Python.
set -e
cd "$(dirname "$0")"

if [ -z "$PREFIX" ] || [ "${PREFIX#*com.termux}" = "$PREFIX" ]; then
  echo "Este script é para o Termux no Android. No computador usa ./iniciar.sh (ou iniciar.bat no Windows)."
  exit 1
fi

PORT=${PORT:-}  # vazio: a aplicação usa a 5000 ou, se estiver ocupada, a primeira porta livre
URL_FILE="${TMPDIR:-$PREFIX/tmp}/portfolio-investimentos-url"
VENV=.venv-android
DEPS="Flask>=3.0 Flask-SQLAlchemy>=3.1 waitress>=3.0 openpyxl>=3.1 tzdata"

if [ "$1" = "--atualizar" ]; then
  shift
  echo "A descarregar a versão mais recente..."
  command -v git >/dev/null 2>&1 || pkg install -y git
  git pull --ff-only
  rm -f "$VENV/.pronto"  # reinstala as dependências, caso tenham mudado
fi

if ! command -v python >/dev/null 2>&1; then
  echo "A instalar o Python (só na primeira vez)..."
  pkg update -y && pkg install -y python
fi

# o marcador guarda a lista instalada: se a lista mudar numa versão nova, volta a instalar
if [ "$(cat "$VENV/.pronto" 2>/dev/null)" != "$DEPS" ]; then
  echo "A preparar o ambiente (pode demorar alguns minutos)..."
  [ -x "$VENV/bin/python" ] || python -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  # shellcheck disable=SC2086
  "$VENV/bin/python" -m pip install $DEPS
  printf '%s' "$DEPS" > "$VENV/.pronto"
fi

# importar sem o seletor de ficheiros do browser (que pode levar o Android a fechar o Termux):
#   bash iniciar-android.sh --importar ~/storage/downloads/EUR_*.xlsx
if [ "$1" = "--importar" ]; then
  [ -d "$HOME/storage" ] || termux-setup-storage  # acesso às Transferências (só na primeira vez)
  exec "$VENV/bin/python" -m portfolio_investimentos "$@"
fi

# impede o Android de suspender o Termux enquanto a aplicação está aberta
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  trap 'termux-wake-unlock' EXIT
fi

echo
echo "No Chrome: menu ⋮ → Adicionar ao ecrã principal, para a abrires como uma aplicação."
echo "Para terminar: Ctrl+C (no teclado do Termux: CTRL e depois C)."
echo

# abre o browser no endereço que a aplicação escolher, assim que estiver a responder
rm -f "$URL_FILE"
(
  for _ in $(seq 1 30); do
    URL=$(cat "$URL_FILE" 2>/dev/null)
    if [ -n "$URL" ] && "$VENV/bin/python" -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1)" "$URL" 2>/dev/null; then
      command -v termux-open-url >/dev/null 2>&1 && termux-open-url "$URL"
      break
    fi
    sleep 1
  done
) &

PORTFOLIO_URL_FILE="$URL_FILE" "$VENV/bin/python" -m portfolio_investimentos --no-browser ${PORT:+--port "$PORT"} "$@"
