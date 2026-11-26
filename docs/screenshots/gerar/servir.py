"""Arranca a aplicação com os dados das capturas: python docs/screenshots/gerar/servir.py <pasta> <porta>"""
import os
import sys

os.environ["PORTFOLIO_DATA_DIR"] = sys.argv[1]
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from portfolio_investimentos import create_app  # noqa: E402
create_app({}).run(port=int(sys.argv[2]), threaded=True)
