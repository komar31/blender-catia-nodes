"""
Nœud Line : représenté par un mesh 2 vertices + 1 edge. Modes
two_points/point_direction/tangent_at_point.

Deux sorties : 'curve' (GLine, pour les autres modes Line/Point/Plane ou pour
Join) et 'vector' (sa direction normalisée, réutilisable telle quelle — ex:
câblée directement dans Extrude.direction — même principe que Plane.vector).
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GLine, point_on_line
from .base import CatiaBaseNode


class LineGNode(GNode):
    """GNode Line : union des inputs de tous les modes, evaluate() route sur params['mode']."""

    label = "Line"
    inputs = [
        Socket("point1", SocketType.POINT),
        Socket("point2", SocketType.POINT),
        Socket("point", SocketType.POINT),
        Socket("direction", SocketType.VECTOR, default=None),
        Socket("length", SocketType.NUMBER, default=1.0, minimum=0.0),
        Socket("curve", SocketType.CURVE),
        Socket("t", SocketType.NUMBER, default=0.0, minimum=0.0, maximum=1.0),
    ]
    outputs = [
        Socket("curve", SocketType.CURVE),
        Socket("vector", SocketType.VECTOR),  # direction de la ligne, réutilisable (ex: direction d'Extrude)
    ]

    def evaluate(self, ctx):
        mode = self.params.get("mode", "two_points")

        if mode == "two_points":
            p1 = self.get_input_value("point1", ctx)
            p2 = self.get_input_value("point2", ctx)
            if p1 is None or p2 is None:
                raise GraphError(f"{self.display_name} : 'point1' et 'point2' doivent être connectés")
            delta = p2.position - p1.position
            length = delta.length
            if length < EPSILON:
                raise GraphError(f"{self.display_name} : point1 et point2 sont confondus")
            origin = p1.position
            direction = delta / length

        elif mode == "point_direction":
            point = self.get_input_value("point", ctx)
            direction_in = self.get_input_value("direction", ctx)
            length = self.get_input_value("length", ctx)
            if point is None:
                raise GraphError(f"{self.display_name} : 'point' non connecté")
            if direction_in is None or direction_in.length < EPSILON:
                raise GraphError(f"{self.display_name} : direction nulle")
            origin = point.position
            direction = direction_in.normalized()

        elif mode == "tangent_at_point":
            curve = self.get_input_value("curve", ctx)
            length = self.get_input_value("length", ctx)
            if curve is None:
                raise GraphError(f"{self.display_name} : 'curve' non connectée")
            t = max(0.0, min(1.0, self.get_input_value("t", ctx)))
            origin = point_on_line(curve, t)
            direction = curve.direction

        else:
            raise GraphError(f"{self.display_name} : mode inconnu '{mode}'")

        gline = GLine(origin=origin, direction=direction, length=length)
        ctx.catia.upsert_line(self, gline)
        return {"curve": gline, "vector": direction}


_MODES = (
    ("two_points", "Deux points", "Ligne reliant deux points"),
    ("point_direction", "Point + direction", "Ligne depuis un point, selon une direction et une longueur"),
    ("tangent_at_point", "Tangente en un point", "Ligne tangente à une courbe à l'abscisse t"),
)


class LineNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Line — matérialisé en mesh 2 vertices + 1 edge via BlenderAdapter.upsert_line."""

    bl_idname = "CatiaNodeLine"
    bl_label = "Line"

    engine_class = LineGNode
    MODE_SOCKETS = {
        "two_points": ("point1", "point2"),
        "point_direction": ("point", "direction", "length"),
        "tangent_at_point": ("curve", "t", "length"),
    }

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=_MODES,
        default="two_points",
        update=CatiaBaseNode._on_mode_changed,
    )


classes = (LineNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
