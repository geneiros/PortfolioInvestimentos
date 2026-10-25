@echo off
REM Inicia o Portfolio Investimentos (Windows). Na primeira vez prepara o ambiente Python.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo A preparar o ambiente - so na primeira vez...
  %PY% -m venv .venv || (echo Python 3.10+ nao encontrado. Instala-o em https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || .venv\Scripts\python -m pip install Flask Flask-SQLAlchemy waitress openpyxl tzdata
)
.venv\Scripts\python -m portfolio_investimentos %*
pause
