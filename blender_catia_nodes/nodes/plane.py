"""
Nœud Plane : représenté par un quad borné (proxy visuel) + custom properties
plane_origin/plane_normal portant la donnée analytique réelle (voir
BlenderAdapter.upsert_plane). Modes three_points/point_normal/offset_parallel/
through_line_angle, plus width/height/rotation communs à tous les modes.

Deux sorties : 'surface' (GPlane, pour construire d'autres entités dessus ou
comme référence — jamais extrudée telle quelle) et 'vector' (la normale,
réutilisable telle quelle — ex: câblée directement dans Extrude.direction,
puisqu'il n'existe pas de nœud "Vector" générique dans cette itération).
"""
from __future__ import annotations

import math

import bpy
from mathutils import Quaternion

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GPlane, stable_uv_basis
from .base import CatiaBaseNode


class PlaneGNode(GNode):
    """GNode Plane : union des inputs de tous les modes, evaluate() route sur params['mode']."""

    label = "Plane"
    inputs = [
        Socket("point1", SocketType.POINT),
        Socket("point2", SocketType.POINT),
        Socket("point3", SocketType.POINT),
        Socket("point", SocketType.POINT),
        Socket("normal", SocketType.VECTOR),
        Socket("source_plane", SocketType.SURFACE),
        Socket("distance", SocketType.NUMBER, default=1.0),
        Socket("line", SocketType.CURVE),
        Socket("reference_plane", SocketType.SURFACE),
        Socket("angle", SocketType.NUMBER, default=0.0, minimum=-360.0, maximum=360.0),
        Socket("width", SocketType.NUMBER, default=1.0, minimum=0.0),
        Socket("height", SocketType.NUMBER, default=1.0, minimum=0.0),
        Socket("rotation", SocketType.NUMBER, default=0.0, minimum=-360.0, maximum=360.0),
    ]
    outputs = [
        Socket("surface", SocketType.SURFACE),
        Socket("vector", SocketType.VECTOR),  # normale du plan, réutilisable (ex: direction d'Extrude)
    ]

    def evaluate(self, ctx):
        mode = self.params.get("mode", "three_points")
        width = self.get_input_value("width", ctx)
        height = self.get_input_value("height", ctx)
        rotation = self.get_input_value("rotation", ctx)

        if mode == "three_points":
            p1 = self.get_input_value("point1", ctx)
            p2 = self.get_input_value("point2", ctx)
            p3 = self.get_input_value("point3", ctx)
            if p1 is None or p2 is None or p3 is None:
                raise GraphError(f"{self.display_name} : 'point1', 'point2' et 'point3' doivent être connectés")
            origin = (p1.position + p2.position + p3.position) / 3.0
            u_vec = p2.position - p1.position
            if u_vec.length < EPSILON:
                raise GraphError(f"{self.display_name} : point1 et point2 sont confondus")
            normal_vec = u_vec.cross(p3.position - p1.position)
            if normal_vec.length < EPSILON:
                raise GraphError(f"{self.display_name} : les trois points sont colinéaires")
            u_axis = u_vec.normalized()
            normal = normal_vec.normalized()
            v_axis = normal.cross(u_axis).normalized()
            u_axis, v_axis = _spin(u_axis, v_axis, normal, rotation)

        elif mode == "point_normal":
            point = self.get_input_value("point", ctx)
            normal_in = self.get_input_value("normal", ctx)
            if point is None:
                raise GraphError(f"{self.display_name} : 'point' non connecté")
            if normal_in is None or normal_in.length < EPSILON:
                raise GraphError(f"{self.display_name} : normale nulle")
            origin = point.position
            normal = normal_in.normalized()
            u_axis, v_axis = stable_uv_basis(normal, rotation)

        elif mode == "offset_parallel":
            source = self.get_input_value("source_plane", ctx)
            distance = self.get_input_value("distance", ctx)
            if source is None:
                raise GraphError(f"{self.display_name} : 'source_plane' non connectée")
            normal = source.normal
            origin = source.origin + normal * distance
            # on conserve l'orientation du plan source (juste décalé), plutôt
            # que de recalculer une base déterministe indépendante
            u_axis, v_axis = _spin(source.u_axis, source.v_axis, normal, rotation)

        elif mode == "through_line_angle":
            line = self.get_input_value("line", ctx)
            reference = self.get_input_value("reference_plane", ctx)
            angle = self.get_input_value("angle", ctx)
            if line is None or reference is None:
                raise GraphError(f"{self.display_name} : 'line' et 'reference_plane' doivent être connectées")
            axis = line.direction
            origin = line.origin + axis * (line.length / 2.0)
            # normale de départ (angle=0) : composante de reference.normal
            # perpendiculaire à la ligne — le plan "le plus parallèle" à la
            # référence tout en contenant la ligne, comme dans CATIA.
            n0 = reference.normal - axis * reference.normal.dot(axis)
            if n0.length < EPSILON:
                raise GraphError(f"{self.display_name} : la ligne est perpendiculaire à reference_plane")
            n0 = n0.normalized()
            normal = Quaternion(axis, math.radians(angle)) @ n0
            u_axis = axis
            v_axis = normal.cross(u_axis).normalized()
            u_axis, v_axis = _spin(u_axis, v_axis, normal, rotation)

        else:
            raise GraphError(f"{self.display_name} : mode inconnu '{mode}'")

        gplane = GPlane(origin=origin, normal=normal, u_axis=u_axis, v_axis=v_axis, width=width, height=height)
        ctx.catia.upsert_plane(self, gplane)
        return {"surface": gplane, "vector": normal}


def _spin(u_axis, v_axis, normal, rotation_deg):
    """Rotation cosmétique additionnelle de (u_axis, v_axis) autour de `normal`, commune à tous les modes."""
    if not rotation_deg:
        return u_axis, v_axis
    quat = Quaternion(normal, math.radians(rotation_deg))
    return quat @ u_axis, quat @ v_axis


_MODES = (
    ("three_points", "Trois points", "Plan passant par trois points"),
    ("point_normal", "Point + normale", "Plan défini par un point et une normale"),
    ("offset_parallel", "Décalage parallèle", "Plan parallèle à un plan source, décalé d'une distance"),
    ("through_line_angle", "Ligne + angle", "Plan contenant une ligne, incliné d'un angle depuis un plan de référence"),
)


class PlaneNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Plane — matérialisé en quad + custom properties via BlenderAdapter.upsert_plane."""

    bl_idname = "CatiaNodePlane"
    bl_label = "Plane"

    engine_class = PlaneGNode
    MODE_SOCKETS = {
        "three_points": ("point1", "point2", "point3", "width", "height", "rotation"),
        "point_normal": ("point", "normal", "width", "height", "rotation"),
        "offset_parallel": ("source_plane", "distance", "width", "height", "rotation"),
        "through_line_angle": ("line", "reference_plane", "angle", "width", "height", "rotation"),
    }

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=_MODES,
        default="three_points",
        update=CatiaBaseNode._on_mode_changed,
    )


classes = (PlaneNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
