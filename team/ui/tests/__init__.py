"""UI tests. Run from the worktree root:

    python -m unittest discover -s team/ui/tests -t team/ui -v

Importing this package puts `team/ui/tests` and `team/ui/tools` on sys.path, so
every test module can write `from browser_support import ...`, `import cdp`
and `import mock_server` whichever way the tests were started.
"""

import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.join(os.path.dirname(_TESTS_DIR), "tools")

for _path in (_TOOLS_DIR, _TESTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)
