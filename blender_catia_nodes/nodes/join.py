"""
Nœud Join : assemble plusieurs entités (Line pour l'instant) bout à bout en
un profil unique — fermé (ex: triangle à 3 edges) ou ouvert. Seul nœud dont
le nombre de sockets d'entrée est dynamique : un socket "edge_N" de plus
apparaît à chaque connexion, un de moins à chaque déconnexion, avec toujours
exactement un slot vide en réserve.

Contrairement aux autres GNode (inputs figés à la classe), JoinGNode porte sa
propre liste `inputs` par instance — voir JoinGNode.__init__.
"""
from __future__ import annotations

import uuid

import bpy

from ..core.engine import GNode, GraphError, Socket, SocketType
from ..core.geometry import join_edges_into_profile
from .base import CatiaBaseNode


class JoinGNode(GNode):
    """
    GNode Join : `inputs` est une liste D'INSTANCE (pas de classe, à
    l'inverse de tous les autres GNode) car son nombre de sockets varie.
    add_edge_socket()/remove_edge_socket() la tiennent à jour, appelées par
    JoinNode._sync_to_engine() pour refléter les sockets bpy actuels.
    """

    label = "Join"
    outputs = [Socket("profile", SocketType.PROFILE)]

    def __init__(self):
        self.inputs = []  # masque la liste de classe (vide) héritée de GNode
        super().__init__()

    def add_edge_socket(self, name: str) -> None:
        sock = Socket(name, SocketType.CURVE)
        self.inputs.append(sock)
        self._input_by_name[name] = sock
        self.params.setdefault(name, sock.default)

    def remove_edge_socket(self, name: str) -> None:
        self.disconnect_input(name)
        self.inputs = [s for s in self.inputs if s.name != name]
        self._input_by_name.pop(name, None)
        self.params.pop(name, None)

    def evaluate(self, ctx):
        edges = []
        for sock in self.inputs:
            value = self.get_input_value(sock.name, ctx)
            if value is not None:
                edges.append(value)

        if not edges:
            raise GraphError(f"{self.display_name} : au moins un edge doit être connecté")

        profile = join_edges_into_profile(edges)
        if profile is None:
            raise GraphError(
                f"{self.display_name} : les segments ne se rejoignent pas bout à bout "
                "(vérifier l'ordre des connexions et que chaque extrémité est partagée)"
            )
        ctx.catia.upsert_join(self, profile)
        return {"profile": profile}


class JoinNode(CatiaBaseNode, bpy.types.Node):
    """
    Nœud bpy Join. Matérialise un mesh en fil (BlenderAdapter.upsert_join) —
    pas de mode, pas de MODE_SOCKETS, init()/_sync_to_engine() entièrement
    réécrits plutôt qu'hérités tels quels (sockets d'entrée dynamiques).
    """

    bl_idname = "CatiaNodeJoin"
    bl_label = "Join"

    engine_class = JoinGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")

    def init(self, context):
        self.node_uuid = uuid.uuid4().hex
        self.outputs.new("CatiaSocketProfile", "profile", identifier="profile")
        self._add_edge_socket()

    def copy(self, node):
        self.node_uuid = uuid.uuid4().hex
        self.obj_name = ""
        self.error_message = ""

    # draw_buttons() hérité de CatiaBaseNode : pas de "mode" ici (hasattr
    # renvoie False), donc il n'affiche que le message d'erreur éventuel.

    def _add_edge_socket(self):
        index = len(self.inputs)
        name = f"edge_{index}"
        self.inputs.new("CatiaSocketCurve", name, identifier=name)

    def sync_dynamic_sockets(self):
        """
        Reconstruit entièrement la liste de sockets d'entrée : retire tout,
        recrée un socket par edge actuellement connecté (dans l'ordre visuel
        courant, en réutilisant leurs liens existants) puis un slot vide en
        réserve. Plus simple et plus robuste qu'un patch incrémental — évite
        tout trou si un edge est déconnecté au milieu de la liste plutôt qu'à
        la fin. Appelé par nodes/base.py.evaluate_tree() avant toute
        (re)synchronisation, donc à chaque changement de lien.
        """
        tree = self.id_data
        sockets = list(self.inputs)
        # déjà dans la forme attendue (tous connectés sauf le dernier) : rien
        # à faire. Vérifier seulement le COMPTE ne suffirait pas — un edge
        # déconnecté au milieu de la liste laisserait un trou avec le même
        # total de sockets.
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
                link = socket.links[0]  # un seul lien par slot (socket non-multi)
                connected_sources.append((link.from_node, link.from_socket))

        for socket in list(self.inputs):
            self.inputs.remove(socket)
        for from_node, from_socket in connected_sources:
            new_socket_name = f"edge_{len(self.inputs)}"
            new_socket = self.inputs.new("CatiaSocketCurve", new_socket_name, identifier=new_socket_name)
            tree.links.new(from_socket, new_socket)
        self._add_edge_socket()  # slot vide en réserve

    def _sync_to_engine(self, engine_node) -> None:
        """
        Pas de mode ni de valeurs littérales à synchroniser (tous les
        sockets sont CURVE, pilotés uniquement par connexion) : on
        réconcilie seulement la liste dynamique de sockets du GNode avec
        celle, déjà à jour, du nœud bpy (sync_dynamic_sockets() a tourné
        juste avant, voir evaluate_tree()).

        Bug vérifié en conditions réelles : comparer les noms via des `set`
        (différence d'ensembles) ne garantit PAS l'ORDRE de reconstruction —
        l'itération d'un set Python n'est pas garantie stable selon les
        chaînes concernées. Sans incidence tant qu'on ajoutait les edges un
        par un (import incrémental), le bug sautait aux yeux dès qu'un GNode
        neuf devait tout reconstruire d'un coup (typiquement après
        rechargement de fichier) : la structure bpy restait correcte mais
        l'ordre des segments côté moteur pouvait être mélangé, cassant le
        chaînage du profil silencieusement. Comparaison sur listes ORDONNÉES.

        Même correction que CatiaBaseNode._sync_to_engine (non héritée ici,
        cette méthode est entièrement réécrite) : une simple assignation ne
        marque pas le GNode dirty, donc un renommage du nœud Join ne se
        répercutait pas sur son objet Blender avant la prochaine évaluation
        déclenchée pour une autre raison.

        Bug vérifié en conditions réelles, resté invisible longtemps : cette
        méthode ne recopiait jamais engine_node.object_name vers self.obj_name
        (contrairement à CatiaBaseNode._sync_to_engine, non héritée ici) —
        self.obj_name restait vide en permanence pour Join. Passait inaperçu
        car le filet de sécurité de _get_or_create() (ré-adoption par nom
        désiré) compensait silencieusement à chaque fois ; a fini par planter
        un accès direct à bpy.data.objects[join.obj_name] (chaîne vide).
        """
        if engine_node.display_name != self.name:
            engine_node.display_name = self.name
            engine_node.mark_dirty()
        current_names = [s.identifier for s in self.inputs]
        engine_names = [s.name for s in engine_node.inputs]
        if current_names != engine_names:
            for name in list(engine_names):
                engine_node.remove_edge_socket(name)
            for name in current_names:
                engine_node.add_edge_socket(name)
        if engine_node.object_name and engine_node.object_name != self.obj_name:
            self.obj_name = engine_node.object_name


classes = (JoinNode,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
