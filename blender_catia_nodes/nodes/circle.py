"""
Nœud Circle : représenté par un mesh en fil (boucle fermée, N segments —
voir BlenderAdapter.upsert_circle). Modes center_radius/center_point/
three_points, plus 'segments' (bornée [3, 128]) commune aux trois.
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GCircle, circumcenter_normal_radius, project_point_on_plane
from .base import CatiaBaseNode


class CircleGNode(GNode):
    """GNode Circle : union des inputs de tous les modes, evaluate() route sur params['mode']."""

    label = "Circle"
    inputs = [
        Socket("center", SocketType.POINT),
        Socket("normal", SocketType.VECTOR),
        Socket("radius", SocketType.NUMBER, default=1.0, minimum=0.0),
        Socket("surface", SocketType.SURFACE),
        Socket("point", SocketType.POINT),
        Socket("point1", SocketType.POINT),
        Socket("point2", SocketType.POINT),
        Socket("point3", SocketType.POINT),
        Socket("segments", SocketType.INTEGER, default=32, minimum=3, maximum=128),
    ]
    outputs = [Socket("circle", SocketType.CIRCLE)]

    def evaluate(self, ctx):
        mode = self.params.get("mode", "center_radius")
        # Bornée [3, 128] : pas de bornes dures reproduites sur le widget
        # (simplification déjà assumée pour toutes les sockets NUMBER/INTEGER,
        # voir blender_adapter/sockets.py) — on clampe ici, comme 't' ailleurs.
        segments = max(3, min(128, int(self.get_input_value("segments", ctx))))

        if mode == "center_radius":
            center = self.get_input_value("center", ctx)
            normal_in = self.get_input_value("normal", ctx)
            radius = self.get_input_value("radius", ctx)
            if center is None:
                raise GraphError(f"{self.display_name} : 'center' non connecté")
            if normal_in is None or normal_in.length < EPSILON:
                raise GraphError(f"{self.display_name} : normale nulle")
            if radius <= EPSILON:
                raise GraphError(f"{self.display_name} : le rayon doit être positif")
            center_pos = center.position
            normal = normal_in.normalized()

        elif mode == "center_point":
            surface = self.get_input_value("surface", ctx)
            center = self.get_input_value("center", ctx)
            point = self.get_input_value("point", ctx)
            if surface is None or center is None or point is None:
                raise GraphError(f"{self.display_name} : 'surface', 'center' et 'point' doivent être connectés")
            # 'center' et 'point' sont projetés sur 'surface' : garantit un
            # cercle bien défini dans ce plan même si les points d'entrée ne
            # sont pas exactement coplanaires (comme Plane.through_line_angle,
            # simplification assumée et documentée plutôt que silencieuse).
            normal = surface.normal
            center_pos = project_point_on_plane(center, surface)
            point_pos = project_point_on_plane(point, surface)
            radius = (point_pos - center_pos).length
            if radius < EPSILON:
                raise GraphError(f"{self.display_name} : 'point' coïncide avec 'center' une fois projetés sur 'surface'")

        elif mode == "three_points":
            p1 = self.get_input_value("point1", ctx)
            p2 = self.get_input_value("point2", ctx)
            p3 = self.get_input_value("point3", ctx)
            if p1 is None or p2 is None or p3 is None:
                raise GraphError(f"{self.display_name} : 'point1', 'point2' et 'point3' doivent être connectés")
            result = circumcenter_normal_radius(p1.position, p2.position, p3.position)
            if result is None:
                raise GraphError(f"{self.display_name} : les trois points sont colinéaires")
            center_pos, normal, radius = result

        else:
            raise GraphError(f"{self.display_name} : mode inconnu '{mode}'")

        gcircle = GCircle(center=center_pos, normal=normal, radius=radius, segments=segments)
        ctx.catia.upsert_circle(self, gcircle)
        return {"circle": gcircle}


_MODES = (
    ("center_radius", "Centre et rayon", "Cercle défini par son centre, sa normale et son rayon"),
    ("center_point", "Centre et point", "Cercle défini par son centre et un point du cercle, dans le plan d'un support"),
    ("three_points", "Trois points", "Cercle circonscrit passant par trois points"),
)


class CircleNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Circle — matérialisé en boucle fermée via BlenderAdapter.upsert_circle."""

    bl_idname = "CatiaNodeCircle"
    bl_label = "Circle"

    engine_class = CircleGNode
    MODE_SOCKETS = {
        "center_radius": ("center", "normal", "radius", "segments"),
        "center_point": ("surface", "center", "point", "segments"),
        "three_points": ("point1", "point2", "point3", "segments"),
    }

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=_MODES,
        default="center_radius",
        update=CatiaBaseNode._on_mode_changed,
    )


classes = (CircleNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
