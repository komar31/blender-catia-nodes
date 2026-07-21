"""
Sockets custom : un bpy.types.NodeSocket par SocketType du moteur (core/engine.py).

Deux familles bien distinctes :
- NUMBER / VECTOR / BOOLEAN : sockets "valeur", avec un default_value natif
  Blender (FloatProperty / FloatVectorProperty / BoolProperty). Blender
  affiche déjà nativement un champ éditable inline quand le socket n'est pas
  connecté — pas besoin de widget custom.
- POINT / CURVE / SURFACE / GEOMETRY / ANY : sockets "référence" qui portent
  soit une dataclass analytique (core/geometry.py, Niveau 1), soit une
  référence vers de la donnée mesh Blender (Niveau 2, GEOMETRY). Aucun
  littéral n'a de sens pour ces types : pas de widget, juste un label.

Réactivité temps réel (le point central du projet) : chaque changement de
default_value déclenche `_on_value_changed`, qui remonte au GNode propriétaire
via nodes/base.py.handle_socket_changed() et relance l'évaluation de tout
l'arbre (bon marché grâce au cache de core/engine.py).

Point signalé : contrairement à NUMBER/BOOLEAN, il n'existe aucun nœud source
de vecteur dans cette itération (pas de nœud "Vector" dédié) — sans
default_value éditable sur CatiaSocketVector, les modes point_direction,
point_normal et la direction optionnelle d'Extrude seraient impossibles à
utiliser sans câblage externe. Le champ est donc rendu éditable inline comme
NUMBER/BOOLEAN, au-delà de la lettre de la demande initiale.

Simplification assumée : les bornes minimum/maximum déclarées sur certains
Socket du moteur (ex. `t` ∈ [0, 1]) ne sont PAS reproduites comme bornes dures
du widget Blender ici (un seul bl_idname par SocketType, donc une seule paire
de bornes possible côté UI) ; le clamp réel de `t` est fait dans evaluate()
des nœuds concernés (core/engine.py reste la source de vérité).
"""
from __future__ import annotations

import bpy

from ..core.engine import SocketType


def _on_value_changed(self, context):
    """
    Callback update= commun à NUMBER/VECTOR/BOOLEAN : remonte la valeur vers
    le GNode et relance l'évaluation de tout l'arbre. Import différé pour
    éviter tout couplage au chargement du module (nodes/base.py n'a lui-même
    aucun besoin d'importer sockets.py).
    """
    from ..nodes.base import handle_socket_changed

    handle_socket_changed(self.node, self)


class CatiaSocketNumber(bpy.types.NodeSocket):
    """Socket NUMBER — champ flottant éditable inline si non connecté."""

    bl_idname = "CatiaSocketNumber"
    bl_label = "Nombre"

    default_value: bpy.props.FloatProperty(
        name="Valeur",
        default=0.0,
        soft_min=-1000.0,
        soft_max=1000.0,
        update=_on_value_changed,
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.30, 0.60, 0.85, 1.0)


class CatiaSocketInteger(bpy.types.NodeSocket):
    """Socket INTEGER — champ entier éditable inline si non connecté (ex: Circle.segments, nœud Integer)."""

    bl_idname = "CatiaSocketInteger"
    bl_label = "Entier"

    default_value: bpy.props.IntProperty(
        name="Valeur",
        default=0,
        soft_min=-1000,
        soft_max=1000,
        update=_on_value_changed,
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.25, 0.70, 0.55, 1.0)


class CatiaSocketVector(bpy.types.NodeSocket):
    """Socket VECTOR — champ vecteur 3D éditable inline si non connecté (voir note en tête de fichier)."""

    bl_idname = "CatiaSocketVector"
    bl_label = "Vecteur"

    default_value: bpy.props.FloatVectorProperty(
        name="Valeur",
        size=3,
        default=(0.0, 0.0, 1.0),
        subtype="XYZ",
        update=_on_value_changed,
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.column().prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.40, 0.35, 0.80, 1.0)


class CatiaSocketBoolean(bpy.types.NodeSocket):
    """Socket BOOLEAN — case à cocher inline si non connecté (sortie du nœud Boolean, ui/nodes/params.py)."""

    bl_idname = "CatiaSocketBoolean"
    bl_label = "Booléen"

    default_value: bpy.props.BoolProperty(
        name="Valeur",
        default=False,
        update=_on_value_changed,
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.85, 0.85, 0.85, 1.0)


class CatiaSocketString(bpy.types.NodeSocket):
    """Socket STRING — champ texte éditable inline si non connecté (sortie du nœud String, nodes/params.py)."""

    bl_idname = "CatiaSocketString"
    bl_label = "Texte"

    default_value: bpy.props.StringProperty(
        name="Valeur",
        default="",
        update=_on_value_changed,
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.20, 0.55, 0.55, 1.0)


class _CatiaSocketReference(bpy.types.NodeSocket):
    """
    Base commune aux sockets "référence" (POINT/CURVE/SURFACE/GEOMETRY/ANY) :
    aucun littéral éditable n'a de sens pour ces types, donc pas de
    default_value — juste un label, connecté ou non.
    """

    def draw(self, context, layout, node, text):
        layout.label(text=text)


class CatiaSocketPoint(_CatiaSocketReference):
    """Socket POINT — porte une core.geometry.GPoint (Niveau 1)."""

    bl_idname = "CatiaSocketPoint"
    bl_label = "Point"

    @classmethod
    def draw_color_simple(cls):
        return (0.90, 0.55, 0.15, 1.0)


class CatiaSocketCurve(_CatiaSocketReference):
    """Socket CURVE — porte une core.geometry.GLine (Niveau 1)."""

    bl_idname = "CatiaSocketCurve"
    bl_label = "Courbe"

    @classmethod
    def draw_color_simple(cls):
        return (0.85, 0.75, 0.20, 1.0)


class CatiaSocketProfile(_CatiaSocketReference):
    """Socket PROFILE — porte une core.geometry.GProfile (sortie du nœud Join, Niveau 1)."""

    bl_idname = "CatiaSocketProfile"
    bl_label = "Profil"

    @classmethod
    def draw_color_simple(cls):
        return (0.55, 0.30, 0.75, 1.0)


class CatiaSocketCircle(_CatiaSocketReference):
    """Socket CIRCLE — porte une core.geometry.GCircle (sortie du nœud Circle, Niveau 1)."""

    bl_idname = "CatiaSocketCircle"
    bl_label = "Cercle"

    @classmethod
    def draw_color_simple(cls):
        return (0.80, 0.30, 0.55, 1.0)


class CatiaSocketSurface(_CatiaSocketReference):
    """Socket SURFACE — porte une core.geometry.GPlane (Niveau 1)."""

    bl_idname = "CatiaSocketSurface"
    bl_label = "Surface"

    @classmethod
    def draw_color_simple(cls):
        return (0.20, 0.75, 0.35, 1.0)


class CatiaSocketGeometry(_CatiaSocketReference):
    """Socket GEOMETRY — porte une référence mesh Blender (Niveau 2 : Extrude et ce qui suivra)."""

    bl_idname = "CatiaSocketGeometry"
    bl_label = "Géométrie"

    @classmethod
    def draw_color_simple(cls):
        return (0.75, 0.20, 0.20, 1.0)


class CatiaSocketAny(_CatiaSocketReference):
    """Socket ANY — type générique (déclarée pour complétude, inutilisée en itération 1)."""

    bl_idname = "CatiaSocketAny"
    bl_label = "Générique"

    @classmethod
    def draw_color_simple(cls):
        return (0.55, 0.55, 0.55, 1.0)


classes = (
    CatiaSocketNumber,
    CatiaSocketInteger,
    CatiaSocketVector,
    CatiaSocketBoolean,
    CatiaSocketString,
    CatiaSocketPoint,
    CatiaSocketCurve,
    CatiaSocketProfile,
    CatiaSocketCircle,
    CatiaSocketSurface,
    CatiaSocketGeometry,
    CatiaSocketAny,
)

# SocketType (core/engine.py) -> bl_idname du socket bpy correspondant.
# Utilisé par nodes/base.py pour créer les sockets d'un nœud depuis la
# déclaration `inputs`/`outputs` de son GNode. SOLID n'est pas mappé : aucun
# nœud de cette itération ne l'utilise.
SOCKET_TYPE_TO_BLIDNAME: dict[SocketType, str] = {
    SocketType.NUMBER: CatiaSocketNumber.bl_idname,
    SocketType.INTEGER: CatiaSocketInteger.bl_idname,
    SocketType.VECTOR: CatiaSocketVector.bl_idname,
    SocketType.BOOLEAN: CatiaSocketBoolean.bl_idname,
    SocketType.STRING: CatiaSocketString.bl_idname,
    SocketType.POINT: CatiaSocketPoint.bl_idname,
    SocketType.CURVE: CatiaSocketCurve.bl_idname,
    SocketType.PROFILE: CatiaSocketProfile.bl_idname,
    SocketType.CIRCLE: CatiaSocketCircle.bl_idname,
    SocketType.SURFACE: CatiaSocketSurface.bl_idname,
    SocketType.GEOMETRY: CatiaSocketGeometry.bl_idname,
    SocketType.ANY: CatiaSocketAny.bl_idname,
}


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
