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


class WindowApi:
    """Ponte JavaScript → Python (window.pywebview.api) da janela própria: a página avisa quando muda de tema."""

    def __init__(self, app=None, apply=None):
        self._app = app
        self._apply = apply or title_bar

    def set_theme(self, color, dark=False):
        if not valid_color(color):
            return False
        if self._app is not None:
            try:
                with self._app.app_context():
                    from .models import Setting
                    Setting.set("window_color", f"{color.lower()}|{1 if dark else 0}")
            except Exception as exc:
                log.info("não foi possível guardar a cor da janela: %s", exc)
        return bool(self._apply(color, bool(dark)))


def saved_color(app=None):
    """(cor, escuro) da última vez, para a janela já abrir com a cor do tema; sem nada guardado, a do tema claro."""
    if app is not None:
        try:
            with app.app_context():
                from .models import Setting
                raw = Setting.get("window_color") or ""
            color, _, dark = raw.partition("|")
            if valid_color(color):
                return color, dark == "1"
        except Exception:
            pass
    return DEFAULT_COLOR, False
