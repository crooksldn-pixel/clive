"""The customers' drawings (web/customers.js), checked by Node through the renderer.

Node is a development tool, not a dependency: without it this skips, as tests/test_web_js.py does.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_the_customers_drawings_under_node():
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "customers.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
