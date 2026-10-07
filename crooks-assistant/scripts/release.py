#!/usr/bin/env python3
"""The release service's command line, from scripts/ like the rest: the same as `python -m app.release`.

Why it exists: every other operator command lives in scripts/, and scripts/map.py reads the
scripts to know which packages a command loads. The service itself is started by its unit as
`python -m app.release tick` from its pinned copy (docs/RELEASE_SERVICE.md).

    python scripts/release.py plan        the dry run: what it would do now, and why; writes nothing
    python scripts/release.py status      the line CLIVE shows on the Builds screen
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.release.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
