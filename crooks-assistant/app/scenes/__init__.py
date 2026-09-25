"""Generative UI: typed evidence, a strict scene plan, and the validator between them.

Connectors describe data (app/scenes/evidence.py, app/scenes/descriptors.py), CLIVE decides
what to show (app/scenes/scene.py, app/scenes/validate.py), and the screen shows findings, not
sources. app/scenes/planner.py plans a scene for a turn; the live app asks it only when
CLIVE_SCENES is on (app/routes/turn.py), beside the cards it has always drawn.
"""

from app.scenes import descriptors  # noqa: F401 — registers the existing read tools' descriptors
from app.scenes.evidence import (
    DEFAULT,
    Evidence,
    FieldDescriptor,
    Kind,
    Money,
    Record,
    Registry,
    Series,
    SeriesPoint,
    ToolDescriptors,
    register,
    to_evidence,
)
from app.scenes.planner import Planner, plan_scene, scene_for_turn, turn_evidence
from app.scenes.scene import ScenePlan
from app.scenes.validate import SceneContext, validate_scene

__all__ = [
    "DEFAULT",
    "Evidence",
    "FieldDescriptor",
    "Kind",
    "Money",
    "Planner",
    "Record",
    "Registry",
    "SceneContext",
    "ScenePlan",
    "Series",
    "SeriesPoint",
    "ToolDescriptors",
    "plan_scene",
    "register",
    "scene_for_turn",
    "to_evidence",
    "turn_evidence",
    "validate_scene",
]
