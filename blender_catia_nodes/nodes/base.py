"""
Pont entre bpy.types.Node et GNode (core/engine.py).

C'est le cœur du système : un bpy.types.Node ne peut pas porter d'objet
Python persistant (il est recréé par le dépilage RNA à chaque rechargement de
fichier / undo), donc les GNode vivent dans un registre runtime module-level
`_engine_nodes: {node_uuid: GNode}`, reconstruit paresseusement via
`ensure_engine_node()`. Un unique EvalContext (donc un unique BlenderAdapter,
donc un unique registre {node.id: Object}) est partagé par tout l'addon.

Principe du mode dropdown : chaque nœud concret déclare l'union de tous les
inputs de son GNode (`engine_class.inputs`) à la création (`init()`), puis
seuls les sockets pertinents pour `self.mode` restent visibles
(`socket.hide`) — masqués, pas juste désactivés.

Réactivité : la correction par rapport à la demande initiale est ici — voir
`evaluate_tree()`. Appeler ctx.evaluate() sur le seul nœud modifié ne
rafraîchit pas l'aval (mark_dirty() invalide les caches aval mais personne ne
les réévalue). Chaque callback (mode changé, socket changé) réévalue donc
TOUT l'arbre ; grâce au cache de core/engine.py, seule la chaîne réellement
dirty recalcule pour de vrai.
"""
from __future__ import annotations

import uuid

import bpy

from ..blender_adapter.adapter import BlenderAdapter
from ..blender_adapter.sockets import SOCKET_TYPE_TO_BLIDNAME
from ..core.engine import EvalContext

# GNode vivants, indexés par node_uuid (StringProperty persistée dans le .blend
# sur chaque bpy.types.Node). Reconstruits à la demande par ensure_engine_node()
# après un rechargement de fichier ou un undo/redo qui a fait disparaître
# l'instance Python précédente.
_engine_nodes: dict[str, "GNode"] = {}

# EvalContext + BlenderAdapter uniques pour toute la session d'édition — les
# id de GNode (itertools.count() dans core/engine.py) sont globalement
# uniques, donc un seul registre {id: Object} suffit même s'il existe
# plusieurs CatiaNodeTree dans le fichier.
_adapter: BlenderAdapter | None = None
_ctx: EvalContext | None = None

# Garde anti-réentrance d'evaluate_tree() : vit ici (pas dans
# CatiaNodeTree.update()) car sync_dynamic_sockets() (nœud Join) mute
# elle-même la topologie (sockets + liens), ce qui redéclenche
# NodeTree.update() de façon synchrone quel que soit le déclencheur initial
# (callback de socket, changement de mode, hook load_post...) — la garde
# doit donc protéger evaluate_tree() lui-même, pas seulement update().
_evaluating = False


def _get_context() -> EvalContext:
    global _adapter, _ctx
    if _ctx is None:
        _adapter = BlenderAdapter()
        _ctx = EvalContext(_adapter)
    return _ctx


@bpy.app.handlers.persistent
def _on_load_post(*_args, **_kwargs):
    """
    Vérifié en conditions réelles : le module Python de l'addon reste chargé
    d'une session à l'autre (register()/unregister() ne sont PAS rappelés à
    l'ouverture d'un fichier), alors que bpy.data est entièrement reconstruit
    à chaque chargement. Sans ce hook, _engine_nodes et le registre
    {node.id: Object} de BlenderAdapter continuaient de référencer d'anciens
    bpy.types.Object devenus invalides ("StructRNA of type Object has been
    removed" dès la première évaluation, sur tous les nœuds).

    On repart donc de zéro à chaque chargement de fichier, puis on réévalue
    immédiatement chaque CatiaNodeTree : ensure_engine_node() reconstruit des
    GNode neufs, et BlenderAdapter._get_or_create() les ré-adopte aux objets
    existants par leur nom stocké (object_name / obj_name) — sans action de
    l'utilisateur.
    """
    global _adapter, _ctx, _evaluating
    _engine_nodes.clear()
    _adapter = None
    _ctx = None
    _evaluating = False  # défensif : la garde n'a normalement aucune raison d'être restée bloquée
    for tree in bpy.data.node_groups:
        if tree.bl_idname == "CatiaNodeTree":
            evaluate_tree(tree)


def register():
    bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    bpy.app.handlers.load_post.remove(_on_load_post)


def is_catia_node(node: bpy.types.Node) -> bool:
    """True si `node` est un de nos nœuds (par opposition à Frame, Reroute, ...)."""
    return isinstance(node, CatiaBaseNode)


def handle_socket_changed(node: bpy.types.Node, socket: bpy.types.NodeSocket) -> None:
    """
    Appelé par le callback update= de blender_adapter/sockets.py quand un
    default_value change. C'est ici que vit la réactivité "slider temps
    réel" : pas de bouton à cliquer, la resynchronisation + réévaluation
    sont immédiates.
    """
    if not is_catia_node(node):
        return
    node.ensure_engine_node()
    evaluate_tree(node.id_data)


def handle_node_property_changed(node: bpy.types.Node, context) -> None:
    """
    Équivalent de handle_socket_changed() pour les nœuds dont la valeur vit
    directement sur le nœud plutôt que sur un socket (Float/Boolean/String :
    une sortie n'a jamais de default_value éditable — is_output=True dans
    sockets.py.draw() — donc leur valeur est une propriété du nœud lui-même).
    """
    if not is_catia_node(node):
        return
    node.ensure_engine_node()
    evaluate_tree(node.id_data)


def evaluate_tree(node_tree: bpy.types.NodeTree) -> None:
    """
    Réévalue tous les nœuds CATIA de `node_tree`. Bon marché grâce au cache
    de core/engine.py : seule la portion réellement dirty recalcule. Une
    erreur sur un nœud (géométrie dégénérée, cycle...) est capturée pour ne
    pas casser l'évaluation des autres branches ni le callback UI appelant.

    Resynchronise systématiquement la topologie (engine_node.incoming) depuis
    les liens bpy avant d'évaluer — pas seulement les paramètres. Point vérifié
    en conditions réelles (Blender 5.2) : après un rechargement de fichier (ou
    un undo, ou une réactivation de l'addon), le registre `_engine_nodes` est
    vidé et ensure_engine_node() recrée des GNode neufs dont `incoming` est
    vide, alors que les liens existent toujours côté bpy. Sans cette
    resynchronisation ici, une simple réévaluation post-rechargement perdait
    silencieusement toutes les connexions tant qu'aucun lien n'était
    retouché manuellement (ce qui aurait redéclenché NodeTree.update()).

    Commence par un hook générique `sync_dynamic_sockets()` (implémenté par
    JoinNode, absent des autres nœuds — d'où le hasattr) qui fait
    grandir/rétrécir les sockets à nombre variable AVANT toute
    resynchronisation, pour que _sync_connections() voie déjà la bonne
    forme. Cette mutation de topologie redéclenche NodeTree.update() de
    façon synchrone : c'est pour ça que la garde anti-réentrance est ici et
    pas seulement dans CatiaNodeTree.update().
    """
    global _evaluating
    if _evaluating:
        return
    _evaluating = True
    try:
        for node in node_tree.nodes:
            if is_catia_node(node) and hasattr(node, "sync_dynamic_sockets"):
                node.sync_dynamic_sockets()

        ctx = _get_context()
        catia_nodes = [n for n in node_tree.nodes if is_catia_node(n)]
        engine_by_node = {n: n.ensure_engine_node() for n in catia_nodes}
        _sync_connections(node_tree, engine_by_node)

        for node, engine_node in engine_by_node.items():
            try:
                ctx.evaluate(engine_node)
            except Exception as exc:  # GraphError/CycleError ou erreur géométrique de evaluate()
                node.set_error(str(exc))
            else:
                node.clear_error()
    finally:
        _evaluating = False


def _sync_connections(node_tree: bpy.types.NodeTree, engine_by_node: dict) -> None:
    """
    Reconstruit entièrement engine_node.incoming pour chaque nœud, depuis les
    liens réellement présents dans node_tree.links — pas d'ajout/retrait
    incrémental fragile, on réinitialise puis on reconstruit à chaque fois
    (même principe que sync_connections() du projet CATIA).
    """
    for engine_node in engine_by_node.values():
        for input_name in list(engine_node.incoming.keys()):
            engine_node.disconnect_input(input_name)

    for link in node_tree.links:
        from_node = link.from_node
        to_node = link.to_node
        if from_node not in engine_by_node or to_node not in engine_by_node:
            continue  # lien vers/depuis un nœud non-CATIA (ex: Frame) : ignoré
        engine_by_node[to_node].connect_input(
            link.to_socket.identifier, engine_by_node[from_node], link.from_socket.identifier
        )


class CatiaBaseNode:
    """
    Mixin (pas un bpy.types.Node à lui seul) : fournit le pont vers le GNode
    et la gestion du mode dropdown. Chaque nœud concret (nodes/point.py, ...)
    hérite de `(CatiaBaseNode, bpy.types.Node)`.

    Point d'API resté incertain : l'héritage des annotations bpy.props à
    travers un mixin Python "plain" (ni PropertyGroup ni bpy_struct) n'est
    pas garanti de façon fiable par bpy.utils.register_class selon les
    versions. Par prudence, node_uuid/obj_name/error_message/mode sont donc
    déclarées explicitement sur CHAQUE classe concrète (nodes/point.py etc.),
    pas ici — ce mixin ne porte que des méthodes.
    """

    engine_class = None  # à surcharger : la classe GNode correspondante
    MODE_SOCKETS: dict[str, tuple[str, ...]] = {}  # à surcharger : mode -> noms des inputs visibles

    @classmethod
    def poll(cls, node_tree: bpy.types.NodeTree) -> bool:
        return node_tree.bl_idname == "CatiaNodeTree"

    # -- cycle de vie bpy.types.Node -----------------------------------------
    def init(self, context):
        self.node_uuid = uuid.uuid4().hex
        for sock in self.engine_class.inputs:
            bl_idname = SOCKET_TYPE_TO_BLIDNAME[sock.type]
            new_socket = self.inputs.new(bl_idname, sock.name, identifier=sock.name)
            # Bug vérifié en conditions réelles : sans ceci, le default_value
            # bpy du socket reste à la valeur par défaut générique de sa
            # classe (0.0 pour CatiaSocketNumber) au lieu de reprendre le
            # `default` déclaré sur le Socket moteur — Plane.width/height
            # (default=1.0) affichaient 0.0 à la création.
            if sock.default is not None and hasattr(new_socket, "default_value"):
                new_socket.default_value = sock.default
        for sock in self.engine_class.outputs:
            bl_idname = SOCKET_TYPE_TO_BLIDNAME[sock.type]
            self.outputs.new(bl_idname, sock.name, identifier=sock.name)
        self._apply_visibility()

    def copy(self, node):
        """Nœud dupliqué : nouvel uuid et nouvel objet Blender, pas de partage avec la source."""
        self.node_uuid = uuid.uuid4().hex
        self.obj_name = ""
        self.error_message = ""

    def free(self):
        """
        Nœud supprimé de l'arbre : on libère son GNode et son objet Blender.
        Les références croisées (incoming/downstream) des autres nœuds sont
        nettoyées par le prochain CatiaNodeTree.update() (reconstruction
        complète depuis les liens UI, voir blender_adapter/node_tree.py) —
        pas besoin de les toucher ici.
        """
        engine_node = _engine_nodes.pop(self.node_uuid, None)
        if engine_node is not None:
            _get_context().catia.remove(engine_node)

    def draw_buttons(self, context, layout):
        if hasattr(self, "mode"):  # absent sur Join et les nœuds Parameters (pas de méthode à choisir)
            layout.prop(self, "mode", text="")
        if self.error_message:
            col = layout.column()
            col.alert = True
            col.label(text=self.error_message, icon="ERROR")

    # -- pont vers le GNode ---------------------------------------------------
    def ensure_engine_node(self):
        """Retrouve (ou recrée) le GNode et le resynchronise avec l'état UI courant."""
        engine_node = _engine_nodes.get(self.node_uuid)
        if engine_node is None:
            engine_node = self.engine_class()
            engine_node.object_name = self.obj_name  # ré-adoption : voir BlenderAdapter._get_or_create
            _engine_nodes[self.node_uuid] = engine_node
        self._sync_to_engine(engine_node)
        return engine_node

    def _sync_to_engine(self, engine_node) -> None:
        # Bug vérifié en conditions réelles : une simple assignation ne passe
        # pas par set_param() et ne marque donc jamais le GNode dirty — tant
        # que rien d'autre ne le rendait dirty entre-temps, renommer un nœud
        # ne renommait l'objet Blender associé qu'au hasard d'une évaluation
        # ultérieure (ex: bouger un slider), jamais immédiatement.
        if engine_node.display_name != self.name:
            engine_node.display_name = self.name
            engine_node.mark_dirty()
        if hasattr(self, "mode"):  # absent sur JoinNode (pas de méthode de construction à choisir)
            engine_node.set_param("mode", self.mode)
        for socket in self.inputs:
            if socket.is_linked:
                continue  # valeur pilotée par la connexion, pas par le default_value local
            value = _socket_literal_value(socket)
            if value is not None:
                engine_node.set_param(socket.identifier, value)
        # l'adaptateur peut avoir dû choisir un nom d'objet différent (première
        # création, ou ré-adoption ayant échoué) : on le rapatrie pour qu'il
        # soit persisté dans le .blend via obj_name.
        if engine_node.object_name and engine_node.object_name != self.obj_name:
            self.obj_name = engine_node.object_name

    def _apply_visibility(self) -> None:
        """
        Masque les sockets non pertinents pour le mode courant. Point vérifié
        en conditions réelles (Blender 5.2) : `socket.hide = True` est un
        no-op silencieux tant que le socket a un lien actif — Blender refuse
        de masquer un socket connecté. On détache donc d'abord les sockets
        qui deviennent non pertinents (changer de mode invalide leur
        connexion, comme changer de méthode de construction dans CATIA)
        avant de les masquer.
        """
        if not hasattr(self, "mode"):  # Float/Boolean/String, Join : rien à masquer
            return
        visible = set(self.MODE_SOCKETS.get(self.mode, ()))
        tree = self.id_data
        for socket in self.inputs:
            should_hide = socket.identifier not in visible
            if should_hide and socket.is_linked:
                for link in list(socket.links):
                    tree.links.remove(link)
            socket.hide = should_hide

    # -- callback partagé pour l'EnumProperty "mode" de chaque nœud concret --
    def _on_mode_changed(self, context):
        self._apply_visibility()
        self.ensure_engine_node()
        evaluate_tree(self.id_data)

    # -- affichage d'erreur (géométrie dégénérée, cycle, ...) ------------------
    def set_error(self, message: str) -> None:
        if self.error_message != message:
            print(f"[CATIA Nodes] {self.name} : {message}")
        self.error_message = message
        self.use_custom_color = True
        self.color = (0.6, 0.15, 0.15)

    def clear_error(self) -> None:
        if self.use_custom_color:
            self.use_custom_color = False
        if self.error_message:
            self.error_message = ""


def _socket_literal_value(socket: bpy.types.NodeSocket):
    """
    Convertit le default_value d'un socket "valeur" (NUMBER/INTEGER/VECTOR/
    BOOLEAN/STRING) vers le type Python attendu par core/geometry.py. None pour les sockets
    "référence" (POINT/CURVE/SURFACE/GEOMETRY/ANY), qui n'ont pas de littéral.
    """
    if socket.bl_idname == "CatiaSocketNumber":
        return float(socket.default_value)
    if socket.bl_idname == "CatiaSocketInteger":
        return int(socket.default_value)
    if socket.bl_idname == "CatiaSocketVector":
        from mathutils import Vector

        return Vector(socket.default_value)
    if socket.bl_idname == "CatiaSocketBoolean":
        return bool(socket.default_value)
    if socket.bl_idname == "CatiaSocketString":
        return str(socket.default_value)
    return None
