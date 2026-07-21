"""
Nœud Projection : projection orthogonale d'un point, d'une courbe (Line) ou
d'un profil (Join/Polyline/Curve) sur une surface (Plane). Le type du
résultat suit celui de 'element' :
  - point   -> un point (GPoint), matérialisé comme un Point (Empty)
  - line    -> une droite (GLine), matérialisée comme une Line (mesh)
  - profile -> un profil (GProfile), matérialisé comme un Join/Curve (mesh)

'element' est typé ANY (comme Intersection.element1/2) plutôt qu'un type
fixe : la nature de l'entrée détermine celle du résultat, donc aucun type de
socket unique ne serait honnête. Trois sorties 'point'/'curve'/'profile' à
demeure (un GNode a une liste de sockets de sortie fixe) : seule celle
correspondant au résultat réel est peuplée, les autres valent None — même
mécanisme qu'Intersection, y compris la bascule Empty <-> Mesh de l'objet
matérialisé (voir BlenderAdapter._get_or_create / _matches_data_kind ; entre
'curve' et 'profile' l'objet reste de type MESH dans les deux cas, seule sa
géométrie change, donc pas de reconversion nécessaire pour ce cas-là).

Portée assumée pour cette itération : GPoint, GLine et GProfile sont
acceptés en 'element' (pour une Line ou un profil, chaque sommet se projette
indépendamment, la topologie — direction/longueur ou liste ordonnée de
sommets + closed — se reconstruit dessus). Circle (GCircle) pourrait être
supporté plus tard sur le même principe qu'Extrude (conversion via
circle_to_profile avant projection).
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GLine, GPoint, GProfile, project_profile_on_plane, project_vector_on_plane
from .base import CatiaBaseNode


class ProjectionGNode(GNode):
    """GNode Projection : projette 'element' (GPoint, GLine ou GProfile) sur 'surface' (GPlane)."""

    label = "Projection"
    inputs = [
        Socket("element", SocketType.ANY),
        Socket("surface", SocketType.SURFACE),
    ]
    outputs = [
        Socket("point", SocketType.POINT),
        Socket("curve", SocketType.CURVE),
        Socket("profile", SocketType.PROFILE),
    ]

    def evaluate(self, ctx):
        element = self.get_input_value("element", ctx)
        surface = self.get_input_value("surface", ctx)
        if element is None or surface is None:
            raise GraphError(f"{self.display_name} : 'element' et 'surface' doivent être connectées")

        if isinstance(element, GPoint):
            position = project_vector_on_plane(element.position, surface)
            gpoint = GPoint(position=position)
            ctx.catia.upsert_projection_point(self, gpoint)
            return {"point": gpoint, "curve": None, "profile": None}

        if isinstance(element, GLine):
            p0 = project_vector_on_plane(element.origin, surface)
            p1 = project_vector_on_plane(element.origin + element.direction * element.length, surface)
            offset = p1 - p0
            if offset.length < EPSILON:
                raise GraphError(
                    f"{self.display_name} : la courbe est perpendiculaire à la surface (projection réduite à un point)"
                )
            projected = GLine(origin=p0, direction=offset.normalized(), length=offset.length)
            ctx.catia.upsert_projection(self, projected)
            return {"point": None, "curve": projected, "profile": None}

        if isinstance(element, GProfile):
            projected_profile = project_profile_on_plane(element, surface)
            ctx.catia.upsert_projection_profile(self, projected_profile)
            return {"point": None, "curve": None, "profile": projected_profile}

        raise GraphError(
            f"{self.display_name} : 'element' attend la sortie d'un nœud Point, Line, Join, Polyline ou "
            f"Curve, pas {type(element).__name__}"
        )


class ProjectionNode(CatiaBaseNode, bpy.types.Node):
    """
    Nœud bpy Projection — matérialisé comme un Point (Empty), une Line ou un
    profil (mesh) selon le résultat réel, via BlenderAdapter.
    upsert_projection_point / upsert_projection / upsert_projection_profile.
    """

    bl_idname = "CatiaNodeProjection"
    bl_label = "Projection"

    engine_class = ProjectionGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")


classes = (ProjectionNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
