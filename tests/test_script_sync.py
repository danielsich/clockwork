"""The standalone `clockwork` script must stay in step with the package.

`clockwork` at the repo root is a copy of `src/clockwork_cli/__init__.py`
that runs without installing: a shebang on top, no `__version__` line, and a
`__main__` block at the end. A fix made in only one of the two leaves the
other behind (0.4.1 read zstd Codex rollouts in the package but not the
script), so this test fails when they drift apart.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "clockwork"
PACKAGE = ROOT / "src" / "clockwork_cli" / "__init__.py"

SHEBANG = "#!/usr/bin/env python3\n"
MAIN_BLOCK = '\n\nif __name__ == "__main__":\n    main()\n'


def expected_script():
    src = PACKAGE.read_text(encoding="utf-8")
    src = re.sub(r'^__version__ = "[^"]*"\n\n\n', "", src, count=1, flags=re.M)
    return SHEBANG + src.rstrip("\n") + "\n" + MAIN_BLOCK


def test_script_matches_package():
    actual = SCRIPT.read_text(encoding="utf-8")
    assert actual == expected_script(), (
        "clockwork and src/clockwork_cli/__init__.py have drifted apart. "
        "Apply the same change to both, or regenerate the script from the "
        "package (shebang, drop __version__, append the __main__ block)."
    )
