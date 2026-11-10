# Executável único (PyInstaller) para quem não quer instalar o Python.
# Gerar (na pasta do projeto, com as dependências e o pyinstaller instalados):
#     pyinstaller packaging/portfolio-investimentos.spec
# O resultado fica em dist/ (PortfolioInvestimentos.exe no Windows; PortfolioInvestimentos no macOS e no Linux).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
PKG = ROOT / "portfolio_investimentos"

datas = [(str(PKG / "templates"), "portfolio_investimentos/templates"),
         (str(PKG / "static"), "portfolio_investimentos/static")]
datas += collect_data_files("tzdata")  # fusos horários (o Windows não tem base de dados de fusos do sistema)
binaries, hiddenimports = [], []
hiddenimports += ["waitress"]
# yfinance (cotações) e as dependências com código nativo ou ficheiros de dados; opcional: sem ele a aplicação
# usa o acesso direto ao Yahoo
for pkg in ("yfinance", "curl_cffi", "peewee", "frozendict", "multitasking"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h
# os módulos da aplicação importados dentro de funções (ex.: serviços carregados a pedido)
hiddenimports += [f"portfolio_investimentos.{p.relative_to(PKG).with_suffix('').as_posix().replace('/', '.')}"
                  for p in PKG.rglob("*.py") if p.name != "__main__.py"]

icon = str(PKG / "static" / "icons" / "icon-512.png")  # convertido para .ico/.icns pelo PyInstaller (precisa do Pillow)

a = Analysis([str(ROOT / "packaging" / "arranque.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "IPython", "matplotlib"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="PortfolioInvestimentos", console=True, upx=False,
          icon=icon if sys.platform != "linux" else None, strip=False)
