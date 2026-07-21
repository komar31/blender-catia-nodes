"""
Nœud Intersection : calcule l'intersection entre deux entités quelconques —
plane/plane, line/plane, line/line (les combinaisons curve/plane, line/
surface et plane/surface citées par la spec sont des alias de ces trois cas
dans le modèle Niveau 1 actuel, où CURVE == GLine et SURFACE == GPlane, sans
type de courbe ou de surface distinct). Le type du résultat dépend de ce qui
est connecté :
  - plane ∩ plane  -> une droite (GLine)
  - line ∩ plane   -> un point (GPoint)
  - line ∩ line    -> un point (GPoint), si elles sont coplanaires et non
                       parallèles (sinon : gauches, pas d'intersection réelle)

'element1'/'element2' sont typés ANY (SocketType.ANY, jusque-là déclaré mais
inutilisé) plutôt qu'un type fixe : contrairement à Extrude.profile (toujours
un "bord extrudable"), ici la nature même de l'entrée détermine le type du
résultat, donc aucun type de socket unique ne serait honnête.

Deux sorties 'point'/'curve' à demeure (un GNode a une liste de sockets de
sortie fixe, pas un type dynamique) : seule celle qui correspond au résultat
réel est peuplée, l'autre vaut None. L'objet Blender matérialisé bascule en
conséquence entre Empty et mesh-Line — voir BlenderAdapter._get_or_create,
qui recrée l'objet si son type ne correspond plus au résultat courant.
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import GLine, GPlane, GPoint, line_line_intersection, line_plane_intersection, plane_plane_intersection
from .base import CatiaBaseNode


class IntersectionGNode(GNode):
    """GNode Intersection : dispatch sur les types réels de 'element1'/'element2'."""

    label = "Intersection"
    inputs = [
        Socket("element1", SocketType.ANY),
        Socket("element2", SocketType.ANY),
        Socket("length", SocketType.NUMBER, default=5.0, minimum=0.0),
    ]
    outputs = [
        Socket("point", SocketType.POINT),
        Socket("curve", SocketType.CURVE),
    ]

    def evaluate(self, ctx):
        e1 = self.get_input_value("element1", ctx)
        e2 = self.get_input_value("element2", ctx)
        if e1 is None or e2 is None:
            raise GraphError(f"{self.display_name} : 'element1' et 'element2' doivent être connectés")

        if isinstance(e1, GPlane) and isinstance(e2, GPlane):
            result = plane_plane_intersection(e1, e2)
            if result is None:
                raise GraphError(f"{self.display_name} : les deux plans sont parallèles (aucune intersection)")
            point_on_line, direction = result
            length = self.get_input_value("length", ctx)
            gline = GLine(origin=point_on_line - direction * (length / 2.0), direction=direction, length=length)
            ctx.catia.upsert_intersection(self, gline)
            return {"point": None, "curve": gline}

        if isinstance(e1, GLine) and isinstance(e2, GLine):
            position = line_line_intersection(e1, e2)
            if position is None:
                raise GraphError(
                    f"{self.display_name} : les deux droites sont parallèles ou non coplanaires (pas d'intersection)"
                )
            gpoint = GPoint(position=position)
            ctx.catia.upsert_intersection_point(self, gpoint)
            return {"point": gpoint, "curve": None}

        line, plane = (e1, e2) if isinstance(e1, GLine) else (e2, e1)
        if isinstance(line, GLine) and isinstance(plane, GPlane):
            position = line_plane_intersection(line, plane)
            if position is None:
                raise GraphError(f"{self.display_name} : la droite est parallèle au plan (aucune intersection)")
            gpoint = GPoint(position=position)
            ctx.catia.upsert_intersection_point(self, gpoint)
            return {"point": gpoint, "curve": None}

        raise GraphError(
            f"{self.display_name} : 'element1'/'element2' attendent la sortie d'un nœud Line ou Plane, pas "
            f"{type(e1).__name__}/{type(e2).__name__}"
        )


class IntersectionNode(CatiaBaseNode, bpy.types.Node):
    """
    Nœud bpy Intersection — matérialisé comme un Point (Empty) ou une Line
    (mesh) selon le résultat réel, via BlenderAdapter.upsert_intersection /
    upsert_intersection_point.
    """

    bl_idname = "CatiaNodeIntersection"
    bl_label = "Intersection"

    engine_class = IntersectionGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")


classes = (IntersectionNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
