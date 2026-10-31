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

    manager.connect("notify::dark", apply)
    apply()
