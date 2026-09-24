"""Generative UI V1: the server-side evidence model, scene schema and validator.

Nothing outside this package imports it yet. A connector describes the data it read
(app/scenes/evidence.py, app/scenes/descriptors.py); CLIVE — later, not here — decides what a
scene shows by building a plan over the closed set of primitives in app/scenes/scene.py; the
plan is reduced to what earned its place by the pure functions in app/scenes/validate.py. The
screen shows findings, not sources: nothing here renders, and nothing the live app renders
(app/presentation.py, app/render.py, routes) is touched by this package.
"""

from __future__ import annotations
