"""
Nœud Curve : courbe de Bézier cubique interpolante passant exactement par
les points connectés, dans l'ordre visuel des sockets — fermée (boucle) ou
ouverte selon le toggle 'closed', échantillonnée en polyligne pour
l'affichage/l'extrusion (core.geometry.bezier_spline_to_profile). Même
mécanisme de sockets d'entrée dynamiques que Join/Polyline (un slot vide de
plus apparaît à chaque connexion), typés POINT.

'segments' contrôle le nombre d'échantillons par intervalle entre deux
points consécutifs (résolution de la courbe, dans l'esprit de
Circle.segments) — mais c'est ici une propriété du nœud (IntProperty à
bornes dures min/max), pas un socket : mélanger un socket à nombre fixe avec
les sockets point_N dynamiques aurait compliqué sync_dynamic_sockets() pour
un gain marginal, et une propriété de nœud offre de toute façon des bornes
dures directement dans le widget (contrairement aux sockets NUMBER/INTEGER
de ce projet, qui ne portent que des bornes indicatives — voir
blender_adapter/sockets.py).

Pas de véritable courbure représentée analytiquement (contrairement à
GLine/GCircle/GPlane) : le résultat est directement un GProfile (polyligne
échantillonnée), comme Polyline — la seule différence est la façon dont ses
sommets sont calculés.
"""
from __future__ import annotations

import uuid

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import bezier_spline_to_profile
from .base import CatiaBaseNode, handle_node_property_changed


class CurveGNode(GNode):
    """
    GNode Curve : `inputs` est une liste D'INSTANCE (comme JoinGNode/
    PolylineGNode) car son nombre de sockets varie.
    """

    label = "Curve"
    outputs = [Socket("profile", SocketType.PROFILE)]

    def __init__(self):
        self.inputs = []  # masque la liste de classe (vide) héritée de GNode
        super().__init__()

    def add_point_socket(self, name: str) -> None:
        sock = Socket(name, SocketType.POINT)
        self.inputs.append(sock)
        self._input_by_name[name] = sock
        self.params.setdefault(name, sock.default)

    def remove_point_socket(self, name: str) -> None:
        self.disconnect_input(name)
        self.inputs = [s for s in self.inputs if s.name != name]
        self._input_by_name.pop(name, None)
        self.params.pop(name, None)

    def evaluate(self, ctx):
        points = []
        for sock in self.inputs:
            value = self.get_input_value(sock.name, ctx)
            if value is not None:
                points.append(value)

        if len(points) < 2:
            raise GraphError(f"{self.display_name} : au moins deux points doivent être connectés")

        closed = bool(self.params.get("closed", False))
        segments = max(2, min(64, int(self.params.get("segments", 12))))
        profile = bezier_spline_to_profile(tuple(p.position for p in points), closed, segments)
        ctx.catia.upsert_curve(self, profile)
        return {"profile": profile}


class CurveNode(CatiaBaseNode, bpy.types.Node):
    """
    Nœud bpy Curve. Matérialise une courbe de Bézier échantillonnée
    (BlenderAdapter.upsert_curve) — pas de mode, init()/_sync_to_engine()
    réécrits plutôt qu'hérités (sockets d'entrée dynamiques, comme Join/
    Polyline), plus 'closed' et 'segments' dessinés par draw_buttons
    (propriétés du nœud, pas des sockets).
    """

    bl_idname = "CatiaNodeCurve"
    bl_label = "Curve"

    engine_class = CurveGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    closed: bpy.props.BoolProperty(name="Fermée", default=False, update=handle_node_property_changed)
    segments: bpy.props.IntProperty(
        name="Segments", default=12, min=2, max=64, update=handle_node_property_changed
    )

    def init(self, context):
        self.node_uuid = uuid.uuid4().hex
        self.outputs.new("CatiaSocketProfile", "profile", identifier="profile")
        self._add_point_socket()

    def copy(self, node):
        self.node_uuid = uuid.uuid4().hex
        self.obj_name = ""
        self.error_message = ""

    def draw_buttons(self, context, layout):
        layout.prop(self, "segments")
        layout.prop(self, "closed")
        super().draw_buttons(context, layout)

    def _add_point_socket(self):
        index = len(self.inputs)
        name = f"point_{index}"
        self.inputs.new("CatiaSocketPoint", name, identifier=name)

    def sync_dynamic_sockets(self):
        """Reconstruction complète des sockets — identique à JoinNode.sync_dynamic_sockets, voir sa docstring."""
        tree = self.id_data
        sockets = list(self.inputs)
        already_correct = (
            len(sockets) >= 1
            and all(s.is_linked for s in sockets[:-1])
            and not sockets[-1].is_linked
        )
        if already_correct:
            return

        connected_sources = []
        for socket in sockets:
            if socket.is_linked:
                link = socket.links[0]
                connected_sources.append((link.from_node, link.from_socket))

        for socket in list(self.inputs):
            self.inputs.remove(socket)
        for from_node, from_socket in connected_sources:
            new_socket_name = f"point_{len(self.inputs)}"
            new_socket = self.inputs.new("CatiaSocketPoint", new_socket_name, identifier=new_socket_name)
            tree.links.new(from_socket, new_socket)
        self._add_point_socket()  # slot vide en réserve

    def _sync_to_engine(self, engine_node) -> None:
        """Même logique que JoinNode._sync_to_engine (voir ses docstrings pour le détail des bugs évités), plus 'closed'/'segments'."""
        if engine_node.display_name != self.name:
            engine_node.display_name = self.name
            engine_node.mark_dirty()
        engine_node.set_param("closed", self.closed)
        engine_node.set_param("segments", self.segments)
        current_names = [s.identifier for s in self.inputs]
        engine_names = [s.name for s in engine_node.inputs]
        if current_names != engine_names:
            for name in list(engine_names):
                engine_node.remove_point_socket(name)
            for name in current_names:
                engine_node.add_point_socket(name)
        if engine_node.object_name and engine_node.object_name != self.obj_name:
            self.obj_name = engine_node.object_name


classes = (CurveNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
