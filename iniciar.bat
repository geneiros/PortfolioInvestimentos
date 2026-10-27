@echo off
REM Inicia o Portfolio Investimentos (Windows). Na primeira vez prepara o ambiente Python.
REM Com git clone, verifica antes se ha uma versao nova e pergunta se deve atualizar.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
call :atualizacoes
if not exist .venv (
  echo A preparar o ambiente - so na primeira vez...
  %PY% -m venv .venv || (echo Python 3.10+ nao encontrado. Instala-o em https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || .venv\Scripts\python -m pip install Flask Flask-SQLAlchemy waitress openpyxl tzdata
)
.venv\Scripts\python -m portfolio_investimentos %*
pause
exit /b

:atualizacoes
REM nunca impede o arranque: sem git, sem internet ou com alteracoes locais, arranca a versao atual
if not exist .git exit /b 0
where git >nul 2>nul || exit /b 0
echo A verificar atualizacoes...
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 fetch --quiet 2>nul
if errorlevel 1 (
  echo Sem ligacao: nao foi possivel verificar atualizacoes.
  exit /b 0
)
set NOVAS=0
for /f %%n in ('git rev-list --count HEAD..@{u} 2^>nul') do set NOVAS=%%n
if "%NOVAS%"=="0" exit /b 0
REM sem resposta em 10 segundos, atualiza (so a resposta N salta a atualizacao)
choice /c SN /t 10 /d S /m "Ha uma versao nova (%NOVAS% alteracoes). Atualizar agora"
if errorlevel 2 exit /b 0
git pull --ff-only
if errorlevel 1 (
  echo Nao foi possivel atualizar - ha ficheiros alterados nesta pasta? A arrancar a versao atual.
  exit /b 0
)
REM as dependencias podem ter mudado na versao nova
if exist .venv\Scripts\python.exe .venv\Scripts\python -m pip install -r requirements.txt
exit /b 0
