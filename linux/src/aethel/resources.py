import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

# data/ sits at the repository root next to src/; installs are editable.
DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
)


def data_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


# Accent inks, after the pen the hub was first sketched with. (label,
# light accent, dark-scheme text accent, dark-scheme fill). Every pair is
# at least 4.5:1 against its surface and against white button text.
INKS = {
    "royal": ("Royal Blue", "#2747c8", "#98a9ff", "#4a62e0"),
    "viridian": ("Viridian", "#17694f", "#6fd1ab", "#1f7a5d"),
    "oxblood": ("Oxblood", "#a1253a", "#ff97a6", "#b42f45"),
    "sepia": ("Sepia", "#8a4a1c", "#e3a779", "#9a5524"),
    "graphite": ("Graphite", "#3c4250", "#c5cbd8", "#4b5263"),
}
DEFAULT_INK = "royal"
_ink_provider: Gtk.CssProvider | None = None
_ink = DEFAULT_INK


def app_version() -> str:
    try:
        from importlib.metadata import version

        return version("aethel")
    except Exception:
        import tomllib

        try:
            with open(os.path.join(DATA_DIR, "..", "pyproject.toml"), "rb") as f:
                return tomllib.load(f)["project"]["version"]
        except (OSError, KeyError, ValueError):
            return "dev"


def set_ink(name: str | None) -> None:
    global _ink
    _ink = name if name in INKS else DEFAULT_INK
    _apply_ink()


def _apply_ink() -> None:
    if _ink_provider is None:
        return
    _label, light, dark_text, dark_fill = INKS[_ink]
    if Adw.StyleManager.get_default().get_dark():
        css = (f"@define-color accent_color {dark_text}; @define-color accent_bg_color {dark_fill}; "
               f"@define-color ink {dark_text};")
    else:
        css = (f"@define-color accent_color {light}; @define-color accent_bg_color {light}; "
               f"@define-color ink {light};")
    css += " @define-color accent_fg_color #ffffff;"
    _ink_provider.load_from_string(css) if hasattr(_ink_provider, "load_from_string") else _ink_provider.load_from_data(css, -1)


def install_styles() -> None:
    display = Gdk.Display.get_default()
    base = Gtk.CssProvider()
    base.load_from_path(data_path("style.css"))
    Gtk.StyleContext.add_provider_for_display(
        display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    dark = Gtk.CssProvider()
    dark.load_from_path(data_path("style-dark.css"))
    manager = Adw.StyleManager.get_default()

    def apply(*_):
        # Added and removed rather than reloaded, so switching schemes
        # while running costs nothing.
        if manager.get_dark():
            Gtk.StyleContext.add_provider_for_display(
                display, dark, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
        else:
            Gtk.StyleContext.remove_provider_for_display(display, dark)

    global _ink_provider
    _ink_provider = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_display(
        display, _ink_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2
    )

    manager.connect("notify::dark", apply)
    manager.connect("notify::dark", lambda *_: _apply_ink())
    apply()
    _apply_ink()
