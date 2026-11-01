import threading

from gi.repository import GLib


def run(fn, callback, *args) -> None:
    # Blocking work (network, subprocess, disk) stays off the UI thread;
    # callback(result) runs on the main loop. An exception is passed to
    # the callback as the result so callers can turn it into a sentence.
    def work():
        try:
            result = fn(*args)
        except Exception as error:  # handed to the caller, never swallowed
            result = error
        GLib.idle_add(lambda: callback(result) and False)

    threading.Thread(target=work, daemon=True).start()
