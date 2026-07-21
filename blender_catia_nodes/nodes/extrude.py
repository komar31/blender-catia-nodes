"""
Nœud Extrude : mesh solide (profil fermé) ou surface ruban (profil ouvert),
construit via bmesh.ops.extrude_face_region / extrude_edge_only selon le cas
(voir BlenderAdapter.upsert_extrude — jamais bpy.ops).

`profile` accepte la sortie de n'importe quel nœud "bord extrudable" : Join,
Polyline ou Curve (GProfile — plusieurs edges chaînés, une polyligne à
travers des points, ou une courbe de Bézier échantillonnée), Line (GLine —
un edge seul est un profil ouvert trivial à 2 sommets), ou Circle (GCircle —
converti en profil fermé via core.geometry.circle_to_profile, au nombre de
segments déjà réglé sur le nœud Circle), et pourra accepter plus tard Fill
de la même façon. Le Plane, lui, reste une référence de construction, jamais
extrudé tel quel — son type SURFACE n'est délibérément pas accepté ici.

Contrat pour un futur nœud Fill : produire un GLine, un GProfile ou un
GCircle pour être utilisable comme profil d'Extrude.

Point cosmétique assumé : le socket 'profile' reste coloré PROFILE (comme
Join) — brancher une Line ou un Circle dessus relie donc visuellement des
couleurs de socket différentes. Ça fonctionne (Blender ne bloque pas la
connexion, et evaluate() gère tous les types), mais ce n'est pas visuellement
homogène ; à revisiter si ça gêne à l'usage.

Un seul mode pour cette itération ; garde quand même le mécanisme
EnumProperty de CatiaBaseNode pour rester homogène avec les autres nœuds
(pas de cas particulier dans base.py).
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import EPSILON, GCircle, GLine, GProfile, circle_to_profile, profile_normal_newell
from .base import CatiaBaseNode


class ExtrudeGNode(GNode):
    """GNode Extrude : profile (Line ou Join) + direction optionnelle + longueur."""

    label = "Extrude"
    inputs = [
        Socket("profile", SocketType.PROFILE),
        Socket("direction", SocketType.VECTOR),
        Socket("length", SocketType.NUMBER, default=1.0),
    ]
    outputs = [Socket("geometry", SocketType.GEOMETRY)]

    def evaluate(self, ctx):
        profile = self.get_input_value("profile", ctx)
        if profile is None:
            raise GraphError(f"{self.display_name} : 'profile' non connecté")
        if isinstance(profile, GLine):
            # un edge seul = profil ouvert trivial à 2 sommets
            profile = GProfile(
                vertices=(profile.origin, profile.origin + profile.direction * profile.length),
                closed=False,
            )
        elif isinstance(profile, GCircle):
            profile = circle_to_profile(profile)
        elif not isinstance(profile, GProfile):
            raise GraphError(
                f"{self.display_name} : 'profile' attend la sortie d'un nœud Line, Circle, Join, Polyline ou "
                f"Curve, pas {type(profile).__name__}"
            )
        if profile.closed and len(profile.vertices) < 3:
            raise GraphError(f"{self.display_name} : un profil fermé nécessite au moins 3 sommets")

        # 'direction' non connectée → normale du profil (méthode de Newell)
        # par défaut. Détection via self.incoming (câblage réel), pas via une
        # valeur sentinelle : le socket VECTOR a toujours un default_value
        # non-None, donc tester "is None" ne distinguerait pas "non connecté"
        # de "connecté à zéro".
        if self.incoming.get("direction"):
            direction_in = self.get_input_value("direction", ctx)
            if direction_in is None or direction_in.length < EPSILON:
                raise GraphError(f"{self.display_name} : direction nulle")
            direction = direction_in.normalized()
        else:
            direction = profile_normal_newell(profile)
            if direction is None:
                raise GraphError(
                    f"{self.display_name} : 'direction' non connectée et impossible à déduire "
                    "du profil (sommets colinéaires ou profil trop court)"
                )

        length = self.get_input_value("length", ctx)
        if abs(length) < EPSILON:
            raise GraphError(f"{self.display_name} : longueur nulle")

        obj = ctx.catia.upsert_extrude(self, profile, direction, length)
        return {"geometry": obj}


_MODES = (("profile", "Profil", "Extrusion d'un profil (Line, Circle ou Join) selon une direction et une longueur"),)


class ExtrudeNode(CatiaBaseNode, bpy.types.Node):
    """Nœud bpy Extrude — matérialisé en solide (ou ruban) via BlenderAdapter.upsert_extrude."""

    bl_idname = "CatiaNodeExtrude"
    bl_label = "Extrude"

    engine_class = ExtrudeGNode
    MODE_SOCKETS = {"profile": ("profile", "direction", "length")}

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=_MODES,
        default="profile",
        update=CatiaBaseNode._on_mode_changed,
    )


classes = (ExtrudeNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
