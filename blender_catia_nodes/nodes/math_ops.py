"""
Nœud Math > Operations : opérations arithmétiques sur des NUMBER, façon nœud
"Math" de Geometry Nodes. Réutilise le mécanisme mode/MODE_SOCKETS existant
(nodes/base.py) pour masquer l'entrée 'b' sur les opérations unaires
(absolute/sqrt/negate) — même principe que les modes de Point/Line/Plane,
appliqué ici au choix d'opération plutôt qu'à une méthode de construction.
"""
from __future__ import annotations

import math

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON
from .base import CatiaBaseNode

_BINARY_OPS = frozenset({"add", "subtract", "multiply", "divide", "min", "max", "power", "modulo"})
_UNARY_OPS = frozenset({"absolute", "sqrt", "negate"})


class MathGNode(GNode):
    """GNode Operations : a (+ b selon l'opération), route sur params['mode']."""

    label = "Operations"
    inputs = [
        Socket("a", SocketType.NUMBER, default=0.0),
        Socket("b", SocketType.NUMBER, default=0.0),
    ]
    outputs = [Socket("value", SocketType.NUMBER)]

    def evaluate(self, ctx):
        mode = self.params.get("mode", "add")
        a = self.get_input_value("a", ctx)
        b = self.get_input_value("b", ctx) if mode in _BINARY_OPS else None

        if mode == "add":
            value = a + b
        elif mode == "subtract":
            value = a - b
        elif mode == "multiply":
            value = a * b
        elif mode == "divide":
            if abs(b) < EPSILON:
                raise GraphError(f"{self.display_name} : division par zéro")
            value = a / b
        elif mode == "min":
            value = min(a, b)
        elif mode == "max":
            value = max(a, b)
        elif mode == "power":
            try:
                value = a**b
            except (ValueError, OverflowError) as exc:
                raise GraphError(f"{self.display_name} : {exc}") from exc
        elif mode == "modulo":
            if abs(b) < EPSILON:
                raise GraphError(f"{self.display_name} : modulo par zéro")
            value = math.fmod(a, b)
        elif mode == "absolute":
            value = abs(a)
        elif mode == "sqrt":
            if a < 0:
                raise GraphError(f"{self.display_name} : racine carrée d'un nombre négatif")
            value = math.sqrt(a)
        elif mode == "negate":
            value = -a
        else:
            raise GraphError(f"{self.display_name} : opération inconnue '{mode}'")

        return {"value": value}


_MODES = (
    ("add", "Addition", "a + b"),
    ("subtract", "Soustraction", "a - b"),
    ("multiply", "Multiplication", "a × b"),
    ("divide", "Division", "a ÷ b"),
    ("min", "Minimum", "min(a, b)"),
    ("max", "Maximum", "max(a, b)"),
    ("power", "Puissance", "a ^ b"),
    ("modulo", "Modulo", "reste de a ÷ b"),
    ("absolute", "Valeur absolue", "|a|"),
    ("sqrt", "Racine carrée", "√a"),
    ("negate", "Opposé", "-a"),
)


class MathOperationsNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Operations — pur calcul, ne matérialise aucun objet Blender."""

    bl_idname = "CatiaNodeMathOperations"
    bl_label = "Operations"

    engine_class = MathGNode
    MODE_SOCKETS = {
        **{op: ("a", "b") for op in _BINARY_OPS},
        **{op: ("a",) for op in _UNARY_OPS},
    }

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Opération",
        items=_MODES,
        default="add",
        update=CatiaBaseNode._on_mode_changed,
    )


class NODE_MT_catia_math(bpy.types.Menu):
    """Sous-menu Add > Math."""

    bl_idname = "NODE_MT_catia_math"
    bl_label = "Math"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("node.add_node", text="Operations")
        op.type = MathOperationsNode.bl_idname
        op.use_transform = True


classes = (MathOperationsNode, NODE_MT_catia_math)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
