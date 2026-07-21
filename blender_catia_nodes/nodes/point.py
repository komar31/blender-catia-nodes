"""Nœud Point : représenté par un Empty. Modes coordinates/on_curve/on_plane/intersection/projection."""
from __future__ import annotations

import bpy
from mathutils import Vector

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import (
    EPSILON,
    GPoint,
    line_plane_intersection,
    point_on_line,
    project_point_on_plane,
)
from .base import CatiaBaseNode


class PointGNode(GNode):
    """GNode Point : union des inputs de tous les modes, evaluate() route sur params['mode']."""

    label = "Point"
    inputs = [
        Socket("x", SocketType.NUMBER, default=0.0),
        Socket("y", SocketType.NUMBER, default=0.0),
        Socket("z", SocketType.NUMBER, default=0.0),
        Socket("curve", SocketType.CURVE),
        Socket("t", SocketType.NUMBER, default=0.0, minimum=0.0, maximum=1.0),
        Socket("surface", SocketType.SURFACE),
        Socket("point", SocketType.POINT),
        Socket("u", SocketType.NUMBER, default=0.0),
        Socket("v", SocketType.NUMBER, default=0.0),
    ]
    outputs = [Socket("point", SocketType.POINT)]

    def evaluate(self, ctx):
        mode = self.params.get("mode", "coordinates")

        if mode == "coordinates":
            x = self.get_input_value("x", ctx)
            y = self.get_input_value("y", ctx)
            z = self.get_input_value("z", ctx)
            position = Vector((x, y, z))

        elif mode == "on_curve":
            curve = self.get_input_value("curve", ctx)
            if curve is None:
                raise GraphError(f"{self.display_name} : 'curve' non connectée")
            t = max(0.0, min(1.0, self.get_input_value("t", ctx)))
            position = point_on_line(curve, t)

        elif mode == "on_plane":
            surface = self.get_input_value("surface", ctx)
            if surface is None:
                raise GraphError(f"{self.display_name} : 'surface' non connectée")
            u = self.get_input_value("u", ctx)
            v = self.get_input_value("v", ctx)
            position = surface.origin + surface.u_axis * u + surface.v_axis * v

        elif mode == "intersection":
            curve = self.get_input_value("curve", ctx)
            surface = self.get_input_value("surface", ctx)
            if curve is None or surface is None:
                raise GraphError(f"{self.display_name} : 'curve' et 'surface' doivent être connectées")
            position = line_plane_intersection(curve, surface)
            if position is None:
                raise GraphError(f"{self.display_name} : la courbe est parallèle à la surface")

        elif mode == "projection":
            point = self.get_input_value("point", ctx)
            surface = self.get_input_value("surface", ctx)
            if point is None or surface is None:
                raise GraphError(f"{self.display_name} : 'point' et 'surface' doivent être connectées")
            position = project_point_on_plane(point, surface)

        else:
            raise GraphError(f"{self.display_name} : mode inconnu '{mode}'")

        gpoint = GPoint(position=position)
        ctx.catia.upsert_point(self, gpoint)
        return {"point": gpoint}


_MODES = (
    ("coordinates", "Coordonnées", "Point défini par ses coordonnées X/Y/Z"),
    ("on_curve", "Sur courbe", "Point à l'abscisse normalisée t le long d'une courbe"),
    ("on_plane", "Sur plan", "Point défini par ses coordonnées U/V dans le repère d'un plan"),
    ("intersection", "Intersection", "Intersection d'une courbe et d'une surface"),
    ("projection", "Projection", "Projection orthogonale d'un point sur une surface"),
)


class PointNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Point — matérialisé en Empty (PLAIN_AXES) via BlenderAdapter.upsert_point."""

    bl_idname = "CatiaNodePoint"
    bl_label = "Point"

    engine_class = PointGNode
    MODE_SOCKETS = {
        "coordinates": ("x", "y", "z"),
        "on_curve": ("curve", "t"),
        "on_plane": ("surface", "u", "v"),
        "intersection": ("curve", "surface"),
        "projection": ("point", "surface"),
    }

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=_MODES,
        default="coordinates",
        update=CatiaBaseNode._on_mode_changed,
    )


classes = (PointNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
