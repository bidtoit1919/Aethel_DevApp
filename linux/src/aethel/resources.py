import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

# data/ sits at the repository root next to src/; installs are editable.
DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
)


def data_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def art_path(name: str) -> str:
    """Generated artwork (data/art/make_art.py)."""
    return os.path.join(DATA_DIR, "art", name)


# Accents, after the sky the name comes from (aether: the bright upper
# air). (label, light-scheme text, light fill, dark-scheme text, dark fill,
# text on the dark fill). Light fills carry white text. Every text colour is
# at least 4.5:1 on its surface, every fill at least 4.5:1 with its text.
INKS = {
    "ember": ("Ember", "#b14a0c", "#c9520f", "#ff9b5c", "#f2762e", "#1a0f07"),
    "rose": ("Dusk Rose", "#ad2f59", "#c93e6c", "#ff92b3", "#ec6a93", "#1a070e"),
    "twilight": ("Twilight", "#2f5fc4", "#3d69d6", "#93b2ff", "#6b93f2", "#06122b"),
    "aurora": ("Aurora", "#127a5c", "#16865f", "#6fdcb4", "#3cc48f", "#04170f"),
    "moon": ("Moonlight", "#4a4f5c", "#5b6170", "#d5d9e3", "#c9ced8", "#15171c"),
}
DEFAULT_INK = "ember"
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
    _label, light_text, light_fill, dark_text, dark_fill, dark_fg = INKS[_ink]
    if Adw.StyleManager.get_default().get_dark():
        text, fill, fg = dark_text, dark_fill, dark_fg
    else:
        text, fill, fg = light_text, light_fill, "#ffffff"
    css = (f"@define-color accent_color {text}; @define-color accent_bg_color {fill}; "
           f"@define-color accent_fg_color {fg}; @define-color ink {text}; @define-color ink_fill {fill};")
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

    # Artwork needs absolute file URIs, so its rules are written here.
    art = Gtk.CssProvider()
    hero = Gio.File.new_for_path(art_path("hero-dusk.png")).get_uri()
    css = (f'.hero {{ background-image: url("{hero}"); background-size: cover; '
           f'background-position: center 65%; background-repeat: no-repeat; '
           f'background-color: #1a1220; }}')
    art.load_from_string(css) if hasattr(art, "load_from_string") else art.load_from_data(css, -1)
    Gtk.StyleContext.add_provider_for_display(display, art, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    global _ink_provider
    _ink_provider = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_display(
        display, _ink_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2
    )

    manager.connect("notify::dark", apply)
    manager.connect("notify::dark", lambda *_: _apply_ink())
    apply()
    _apply_ink()
