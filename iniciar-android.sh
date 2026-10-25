#!/data/data/com.termux/files/usr/bin/bash
# Inicia o Portfolio Investimentos no Android, dentro do Termux (https://f-droid.org/packages/com.termux/).
# Na primeira vez instala o Python e as dependências; depois abre a aplicação no browser do telemóvel.
#
#   bash iniciar-android.sh               arranca e abre o browser
#   bash iniciar-android.sh --atualizar   descarrega a versão mais recente (git pull) e arranca
#   PORT=8080 bash iniciar-android.sh     usa outra porta
#
# O yfinance (cotações) não é instalado: precisa de pandas/numpy, que no Android raramente compilam.
# Sem ele a aplicação funciona com as cotações já guardadas; podes atualizá-las no computador e
# copiar o ficheiro de dados (Definições → Cópia de segurança) para ~/.portfolio-investimentos/portfolio.db.
set -e
cd "$(dirname "$0")"

if [ -z "$PREFIX" ] || [ "${PREFIX#*com.termux}" = "$PREFIX" ]; then
  echo "Este script é para o Termux no Android. No computador usa ./iniciar.sh (ou iniciar.bat no Windows)."
  exit 1
fi

PORT=${PORT:-5000}
URL="http://127.0.0.1:$PORT/"
VENV=.venv-android
DEPS="Flask>=3.0 Flask-SQLAlchemy>=3.1 waitress>=3.0 openpyxl>=3.1"

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

if [ ! -f "$VENV/.pronto" ]; then
  echo "A preparar o ambiente (só na primeira vez; pode demorar alguns minutos)..."
  python -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  # shellcheck disable=SC2086
  "$VENV/bin/python" -m pip install $DEPS
  touch "$VENV/.pronto"
fi

# impede o Android de suspender o Termux enquanto a aplicação está aberta
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  trap 'termux-wake-unlock' EXIT
fi

echo
echo "Portfolio Investimentos a correr em $URL"
echo "No Chrome: menu ⋮ → Adicionar ao ecrã principal, para a abrires como uma aplicação."
echo "Para terminar: Ctrl+C (no teclado do Termux: CTRL e depois C)."
echo

# abre o browser assim que o servidor estiver a responder
(
  for _ in $(seq 1 30); do
    if "$VENV/bin/python" -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1)" "$URL" 2>/dev/null; then
      command -v termux-open-url >/dev/null 2>&1 && termux-open-url "$URL"
      break
    fi
    sleep 1
  done
) &

"$VENV/bin/python" -m portfolio_investimentos --no-browser --port "$PORT" "$@"
