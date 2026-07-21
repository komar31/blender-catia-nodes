"""
Nœud Parallel Curve : décale une courbe (Line) d'une distance donnée, dans le
plan d'une surface support, perpendiculairement à la courbe — matérialisée
comme une Line. Même longueur et même direction que la courbe source, seule
l'origine se déplace le long de l'axe de décalage (surface.normal × direction).

Portée assumée pour cette itération : seul un GLine est accepté en 'curve'
(le décalage d'un Circle — un cercle concentrique de rayon différent — suit
un principe différent et n'est pas couvert ici).
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GLine
from .base import CatiaBaseNode


class ParallelCurveGNode(GNode):
    """GNode Parallel Curve : décale 'curve' (GLine) de 'distance' dans le plan de 'surface'."""

    label = "Parallel Curve"
    inputs = [
        Socket("curve", SocketType.CURVE),
        Socket("surface", SocketType.SURFACE),
        Socket("distance", SocketType.NUMBER, default=1.0),
    ]
    outputs = [Socket("curve", SocketType.CURVE)]

    def evaluate(self, ctx):
        curve = self.get_input_value("curve", ctx)
        surface = self.get_input_value("surface", ctx)
        distance = self.get_input_value("distance", ctx)
        if curve is None or surface is None:
            raise GraphError(f"{self.display_name} : 'curve' et 'surface' doivent être connectées")
        if not isinstance(curve, GLine):
            raise GraphError(
                f"{self.display_name} : 'curve' attend la sortie d'un nœud Line, pas {type(curve).__name__}"
            )
        offset_dir = surface.normal.cross(curve.direction)
        if offset_dir.length < EPSILON:
            raise GraphError(
                f"{self.display_name} : la courbe est perpendiculaire à la surface, décalage indéfini"
            )
        offset = offset_dir.normalized() * distance
        parallel = GLine(origin=curve.origin + offset, direction=curve.direction, length=curve.length)
        ctx.catia.upsert_parallel_curve(self, parallel)
        return {"curve": parallel}


class ParallelCurveNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Parallel Curve — matérialisé comme une Line via BlenderAdapter.upsert_parallel_curve."""

    bl_idname = "CatiaNodeParallelCurve"
    bl_label = "Parallel Curve"

    engine_class = ParallelCurveGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")


classes = (ParallelCurveNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
