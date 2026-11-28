@echo off
REM Inicia o Portfolio Investimentos (Windows). Na primeira vez prepara o ambiente Python.
REM Com git clone, verifica antes se ha uma versao nova e pergunta se deve atualizar (sem resposta em
REM 10 segundos, atualiza). PORTFOLIO_ATUALIZAR=S atualiza sem perguntar; PORTFOLIO_ATUALIZAR=N nunca atualiza.
cd /d "%~dp0"
if defined PORTFOLIO_PYTHON (
  set "PY=%PORTFOLIO_PYTHON%"
) else (
  where py >nul 2>nul && (set PY=py -3) || (set PY=python)
)
call :verificar
if "%NOVAS%"=="0" goto :arrancar
if /i "%PORTFOLIO_ATUALIZAR%"=="N" goto :arrancar
if not defined PORTFOLIO_ATUALIZAR (
  choice /c SN /t 10 /d S /m "Ha uma versao nova (%NOVAS% alteracoes). Atualizar agora"
  if errorlevel 2 goto :arrancar
)
REM o proprio iniciar.bat pode mudar com a atualizacao e o cmd le os .bat por posicao no ficheiro:
REM depois do pull abre-se de novo a versao nova e este sai (o bloco ja foi lido por inteiro)
git pull --ff-only && (
  call "%~f0" %*
  exit /b
)
echo Nao foi possivel atualizar - ha ficheiros alterados nesta pasta? A arrancar a versao atual.

:arrancar
REM fora de blocos: o PY pode mudar em :garantir_python e o cmd expande %PY% num bloco antes de o correr
if exist .venv\Scripts\python.exe goto :preparado
echo A preparar o ambiente - so na primeira vez...
call :garantir_python || (echo Python 3.10+ nao encontrado. Instala-o em https://www.python.org/downloads/ ^(marca Add Python to PATH^) e volta a abrir. & pause & exit /b 1)
%PY% -m venv .venv || (echo Nao foi possivel criar o ambiente Python ^(.venv^). & pause & exit /b 1)
:preparado
call :dependencias || (echo Nao foi possivel instalar as dependencias. Verifica a ligacao a internet e volta a abrir. & pause & exit /b 1)
.venv\Scripts\python -m portfolio_investimentos %*
pause
exit /b

:verificar
REM nunca impede o arranque: sem git, sem internet ou sem pasta .git, NOVAS fica 0 e arranca a versao atual
set NOVAS=0
if not exist .git exit /b 0
where git >nul 2>nul || exit /b 0
echo A verificar atualizacoes...
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 fetch --quiet 2>nul
if errorlevel 1 (
  echo Sem ligacao: nao foi possivel verificar atualizacoes.
  exit /b 0
)
for /f %%n in ('git rev-list --count HEAD..@{u} 2^>nul') do set NOVAS=%%n
exit /b 0

:garantir_python
REM testa a correr o Python, nao com where: o python.exe de WindowsApps e so um atalho para a Microsoft Store
if defined PORTFOLIO_PYTHON exit /b 0
%PY% --version >nul 2>nul && exit /b 0
REM sem Python: instala com o winget, se existir (nas edicoes LTSC do Windows normalmente nao existe)
where winget >nul 2>nul || exit /b 1
echo Python nao encontrado. A instalar o Python 3.12 com o winget - pode demorar alguns minutos...
REM 3.12 porque o numpy<2 nao tem pacotes para o 3.13; --scope user nao pede administrador
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
REM esta janela nao ve o PATH novo: usa o caminho completo da instalacao para o utilizador
set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
%PY% --version >nul 2>nul && exit /b 0
exit /b 1

:dependencias
REM o marcador e uma copia de requirements.txt, criada so depois de a instalacao terminar:
REM reinstala se a instalacao anterior foi interrompida ou se a lista de dependencias mudou
fc /b requirements.txt .venv\.pronto >nul 2>nul && exit /b 0
echo A instalar as dependencias...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || .venv\Scripts\python -m pip install Flask Flask-SQLAlchemy waitress openpyxl tzdata || exit /b 1
copy /y requirements.txt .venv\.pronto >nul
exit /b 0
