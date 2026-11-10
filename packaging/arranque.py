"""Arranque do executável único (PyInstaller): o mesmo que `python -m portfolio_investimentos`.

Com duplo clique, a janela do terminal fecha-se logo que o programa termina: quando termina com erro (ex.: porta
ocupada, base de dados de uma versão mais recente), espera por Enter para se poder ler a mensagem.
"""
import sys


def _wait_before_closing():
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nCarrega em Enter para fechar esta janela.")
        except (EOFError, KeyboardInterrupt):
            pass


def run():
    from portfolio_investimentos.__main__ import main
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            if not isinstance(exc.code, int):
                print(exc.code)
            _wait_before_closing()
            raise SystemExit(exc.code if isinstance(exc.code, int) else 1) from None
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        _wait_before_closing()
        raise SystemExit(1) from None


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    run()
