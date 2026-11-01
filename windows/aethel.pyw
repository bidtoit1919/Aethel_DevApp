"""Start Aethel for Windows without a console window.

The Start-menu shortcut made by scripts/install.ps1 runs this file with
MSYS2's pythonw.exe. It puts this checkout's src/ and Aethel's private
package folder (%LOCALAPPDATA%\Aethel\site, where install.ps1 puts pyte) on
the path. pythonw has no console, so start-up errors go to
%LOCALAPPDATA%\Aethel\aethel.log.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Aethel")
sys.path.insert(0, os.path.join(HERE, "src"))
if os.path.isdir(os.path.join(STATE, "site")):
    sys.path.insert(1, os.path.join(STATE, "site"))

os.makedirs(STATE, exist_ok=True)
log = open(os.path.join(STATE, "aethel.log"), "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = log
if sys.stdout is None:
    sys.stdout = log

try:
    from aethel.__main__ import main

    main()
except SystemExit:
    raise
except BaseException:
    traceback.print_exc(file=log)
    raise
