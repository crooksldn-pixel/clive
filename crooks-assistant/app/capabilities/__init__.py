"""What CROOKS OS can actually do, generated from the registries rather than remembered.

app/capabilities/manifest.py builds the manifest from app/tools/registry.py,
app/analytics/query.py, app/presentation.py and the action grammar — so a tool added or
removed changes the answer to "what can you do?" without anyone editing a sentence.

app/capabilities/delta.py keeps the manifest of the previous build beside the current one,
so "what more can you do now?" is a comparison the Mac can make in milliseconds.
"""

from app.capabilities.delta import delta, record_build, spoken_delta
from app.capabilities.manifest import build, fingerprint, spoken_summary

__all__ = ["build", "delta", "fingerprint", "record_build", "spoken_delta", "spoken_summary"]
