"""Janela própria do executável (pywebview): a cor da barra de título acompanha o tema da aplicação.

O pywebview não tem uma opção para a cor da barra de título (é do sistema operativo), por isso usa-se a API nativa:
- Windows 11: DwmSetWindowAttribute com a cor da barra (35) e do texto (36), mais o modo escuro (20);
- Windows 10: só o modo claro/escuro da barra (atributo 20; os outros são ignorados);
- macOS: barra transparente sobre o fundo da janela com a cor do tema e a aparência clara/escura (thread principal).
No Linux o executável abre no browser e nada disto se aplica. Qualquer erro fica no log e nunca interrompe a
aplicação.
"""
import logging
import re
import sys

log = logging.getLogger(__name__)

TITLE = "Portfolio Investimentos"
DEFAULT_COLOR = "#ffffff"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_color(color):
    return isinstance(color, str) and bool(_HEX.match(color))


def _rgb(color):
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def title_bar(color, dark):
    """Pinta a barra de título da janela com `color` (#rrggbb); `dark` escolhe botões e texto claros."""
    if not valid_color(color):
        return False
    try:
        if sys.platform == "win32":
            return _windows(color, dark)
        if sys.platform == "darwin":
            return _macos(color, dark)
    except Exception as exc:  # cor da janela é só cosmética
        log.info("não foi possível mudar a cor da janela: %s", exc)
    return False


def _windows(color, dark):
    import ctypes
    from ctypes import wintypes
    hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
    if not hwnd:
        return False
    dwm = ctypes.windll.dwmapi
    r, g, b = _rgb(color)

    def attr(name, value):
        v = wintypes.DWORD(value)
        return dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(name), ctypes.byref(v), ctypes.sizeof(v))
    attr(20, 1 if dark else 0)                    # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 2004+ e 11)
    ok = attr(35, r | (g << 8) | (b << 16)) == 0   # DWMWA_CAPTION_COLOR (COLORREF 0x00BBGGRR, Windows 11)
    attr(36, 0x00FFFFFF if dark else 0x00000000)  # DWMWA_TEXT_COLOR
    return ok


def _macos(color, dark):
    from AppKit import NSApp, NSAppearance, NSColor
    from PyObjCTools import AppHelper
    r, g, b = (c / 255 for c in _rgb(color))

    def apply():
        for w in NSApp.windows():
            if str(w.title()) != TITLE:
                continue
            w.setTitlebarAppearsTransparent_(True)
            w.setBackgroundColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0))
            w.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"))
    AppHelper.callAfter(apply)  # o AppKit só se mexe na thread principal
    return True


DEFAULT_SIZE = (1400, 900)


def window_geometry(screens, fraction=0.85):
    """(largura, altura, x, y) da janela: `fraction` do ecrã principal (o primeiro da lista), centrada nele.
    Sem informação do ecrã, (1400, 900, None, None): o pywebview centra a janela sozinho."""
    try:
        screen = screens[0]
        sw, sh = int(screen.width), int(screen.height)
        if sw <= 0 or sh <= 0:
            raise ValueError
    except Exception:
        return DEFAULT_SIZE[0], DEFAULT_SIZE[1], None, None
    width, height = round(sw * fraction), round(sh * fraction)
    x = int(getattr(screen, "x", 0) or 0) + (sw - width) // 2
    y = int(getattr(screen, "y", 0) or 0) + (sh - height) // 2
    return width, height, x, y


def _color_file():
    from . import data_dir
    return data_dir() / "janela.txt"


class WindowApi:
    """Ponte JavaScript → Python (window.pywebview.api) da janela própria: a página avisa quando muda de tema."""

    def __init__(self, apply=None, store=None):
        self._apply = apply or title_bar
        self._store = store or _color_file

    def set_theme(self, color, dark=False):
        if not valid_color(color):
            return False
        try:  # num ficheiro da pasta de dados: a janela abre antes da base de dados (ecrã de arranque)
            self._store().write_text(f"{color.lower()}|{1 if dark else 0}", encoding="utf-8")
        except Exception as exc:
            log.info("não foi possível guardar a cor da janela: %s", exc)
        return bool(self._apply(color, bool(dark)))


def saved_color(store=None):
    """(cor, escuro) da última vez, para a janela já abrir com a cor do tema; sem nada guardado, a do tema claro."""
    try:
        raw = (store or _color_file)().read_text(encoding="utf-8").strip()
        color, _, dark = raw.partition("|")
        if valid_color(color):
            return color, dark == "1"
    except Exception:
        pass
    return DEFAULT_COLOR, False


def splash_html(color=DEFAULT_COLOR, dark=False):
    """Ecrã de arranque da janela própria, enquanto a aplicação se prepara (autocontido: o ícone vai embutido).
    `pmSplash(texto, erro)` muda a mensagem (chamado por evaluate_js durante o arranque)."""
    import base64
    from pathlib import Path
    if not valid_color(color):
        color, dark = DEFAULT_COLOR, False
    try:
        icon = base64.b64encode((Path(__file__).parent / "static" / "icons" / "icon-192.png").read_bytes()).decode()
        img = f'<img src="data:image/png;base64,{icon}" alt="" width="96" height="96">'
    except OSError:
        img = ""
    fg, muted, track, bar = (("#e9ecef", "#adb5bd", "rgba(255,255,255,.12)", "#6ea8fe") if dark
                             else ("#212529", "#6c757d", "rgba(0,0,0,.08)", "#0d6efd"))
    return f"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>{TITLE}</title><style>
html,body{{margin:0;height:100%;background:{color};color:{fg};font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
body{{display:flex;align-items:center;justify-content:center;user-select:none;cursor:default}}
.box{{text-align:center;max-width:32rem;padding:2rem}}
img{{border-radius:22px;box-shadow:0 6px 24px rgba(0,0,0,.18)}}
h1{{font-size:1.4rem;font-weight:600;margin:1.25rem 0 1.5rem}}
.track{{width:220px;height:3px;margin:0 auto;border-radius:3px;background:{track};overflow:hidden}}
.bar{{width:40%;height:100%;border-radius:3px;background:{bar};animation:slide 1.2s ease-in-out infinite}}
@keyframes slide{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(250%)}}}}
p{{font-size:.9rem;color:{muted};margin:1rem 0 0;line-height:1.4}}
p.error{{color:#dc3545;font-size:1rem}}
.hidden{{display:none}}
</style></head><body><div class="box">{img}<h1>{TITLE}</h1>
<div class="track" id="track"><div class="bar"></div></div>
<p id="msg">A preparar a aplicação…</p></div>
<script>window.pmSplash=function(t,e){{var m=document.getElementById("msg");m.textContent=t;
if(e){{m.className="error";document.getElementById("track").className="track hidden";}}}};</script>
</body></html>"""


# ---------------------------------------------------------------------- terminal (executável do Windows)
# No Windows o executável é gerado sem consola (sem a janela preta do terminal). Sem consola, sys.stdout é None:
# - lançado a partir de um cmd/PowerShell, liga-se a esse terminal (para --help, --demo, --importar…);
# - com duplo clique, as mensagens vão para registo.log na pasta dos dados;
# - sem a janela própria (abre no browser), num erro ou com --terminal, abre-se um terminal como antes.
# Com a saída redirecionada (CI, «> ficheiro») não se mexe em nada.
_log_file = None


def _windowed():
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _bind_console(stdin=False):
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    if stdin:
        sys.stdin = open("CONIN$", encoding="utf-8")


def _kernel32():
    import ctypes
    return ctypes.windll.kernel32


def attach_parent_console(kernel32=None):
    """Lançado a partir de um terminal: escreve nesse terminal. True se ligou."""
    if not _windowed() or sys.stdout is not None:
        return False
    try:
        k = kernel32 or _kernel32()
        if not k.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return False
        _bind_console()
        return True
    except Exception:
        return False


def log_to_file(path):
    """Sem consola nem saída redirecionada: as mensagens vão para `path` (reescrito em cada arranque)."""
    global _log_file
    if sys.stdout is not None:
        return False
    try:
        _log_file = open(path, "w", encoding="utf-8", buffering=1)
    except OSError:
        return False
    sys.stdout = sys.stderr = _log_file
    return True


def show_console(kernel32=None):
    """Abre um terminal novo e passa a escrever nele (como no executável com consola). Só no executável do
    Windows e só se a saída não tiver outro destino (um terminal, um ficheiro ou o CI)."""
    global _log_file
    if not _windowed() or (sys.stdout is not None and sys.stdout is not _log_file):
        return False
    try:
        k = kernel32 or _kernel32()
        if not k.AllocConsole():
            return False
        k.SetConsoleTitleW(TITLE)
        _bind_console(stdin=True)
        if _log_file is not None:
            _log_file.close()
            _log_file = None
        return True
    except Exception:
        return False
