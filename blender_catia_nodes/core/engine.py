"""
Moteur d'évaluation du graphe de nœuds géométriques.

Reproduit la logique de Blender : DAG de nœuds, tri topologique,
cache par nœud, invalidation en cascade (dirty propagation) quand un
paramètre ou une connexion change.

Ce module est indépendant de l'UI (NodeGraphQt) et de CATIA : il ne
connaît que des GNode et un EvalContext générique. C'est ce qui permet
de tester le moteur sans lancer CATIA ni Qt.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional


class SocketType(Enum):
    NUMBER = auto()
    INTEGER = auto()
    VECTOR = auto()
    BOOLEAN = auto()
    STRING = auto()
    POINT = auto()       # dataclass analytique GPoint (Niveau 1, voir core/geometry.py)
    CURVE = auto()      # référence CATIA HybridShape (courbe)
    PROFILE = auto()    # dataclass analytique GProfile (Niveau 1, chaîne de sommets issue du nœud Join)
    CIRCLE = auto()     # dataclass analytique GCircle (Niveau 1, centre/normale/rayon)
    SURFACE = auto()
    SOLID = auto()
    GEOMETRY = auto()   # type générique, accepte curve/surface/solid/point
    ANY = auto()


@dataclass
class Socket:
    name: str
    type: SocketType
    default: Any = None
    multi: bool = False  # accepte plusieurs connexions entrantes (ex: Output.geometries)
    choices: Optional[list[str]] = None  # STRING : liste déroulante au lieu d'un champ libre
    minimum: float = -1000.0  # NUMBER : borne basse du slider (ajustable dans l'UI)
    maximum: float = 1000.0  # NUMBER : borne haute du slider (ajustable dans l'UI)
    multiline: bool = False  # STRING : zone de texte multi-ligne (QPlainTextEdit) au lieu d'un simple champ
    file_picker: bool = False  # STRING : sélecteur de fichier (chemin) au lieu d'un champ libre
    file_filter: Optional[str] = None  # STRING+file_picker : filtre QFileDialog custom (sinon celui par défaut de NodeFilePicker)
    table: bool = False  # STRING : grille éditable (lignes/colonnes) sérialisée en JSON
    orderable: bool = False  # multi=True : widget liste + monter/descendre pour contrôler l'ordre des connexions (ex: Spline.points), au lieu du simple ordre de câblage


class GraphError(Exception):
    """Erreur de câblage ou de configuration du graphe."""


class CycleError(GraphError):
    """Le graphe contient un cycle — non supporté (comme dans Blender)."""


_id_counter = itertools.count()


class GNode:
    """
    Nœud générique du graphe. Chaque type concret (Point, Extrude, ...)
    hérite de cette classe, déclare `inputs`/`outputs`, et implémente
    `evaluate()`.
    """

    inputs: list[Socket] = []
    outputs: list[Socket] = []
    label: str = "Node"

    def __init__(self):
        self.id = next(_id_counter)
        # Nom affiché côté UI (distinct de `label`, le nom de *type* utilisé
        # pour le debug/les messages d'erreur) : synchronisé par
        # nodes/base.py.sync_to_engine() avec le nom du nœud NodeGraphQt, et
        # utilisé pour nommer la feature CATIA correspondante — garder
        # core/engine.py indépendant de NodeGraphQt (juste une chaîne).
        self.display_name: str = self.label
        # Nom du "Set Géométrique" (conteneur visuel façon Frame de Blender,
        # voir nodes/geometrical_set.py) dans lequel ce nœud est visuellement
        # placé, ou None par défaut. Synchronisé par
        # ui/app.py._sync_geometrical_sets() avant chaque évaluation ; lu par
        # les adaptateurs pour savoir dans quel HybridBody CATIA créer la
        # feature correspondante. Simple chaîne, comme display_name, pour
        # garder ce module indépendant de NodeGraphQt/CATIA.
        self.target_body: Optional[str] = None
        self.params: dict[str, Any] = {s.name: s.default for s in self.inputs}
        self._cache: Optional[dict[str, Any]] = None
        self._dirty: bool = True
        self._input_by_name: dict[str, Socket] = {s.name: s for s in self.inputs}
        # connexions entrantes : {input_name: [(source_node, output_name), ...]}
        # une entrée normale ne contient jamais plus d'un élément ; une
        # entrée "multi" (Socket.multi = True) peut en contenir plusieurs,
        # comme un port multi-entrées de Blender.
        self.incoming: dict[str, list[tuple["GNode", str]]] = {}
        # nœuds en aval qui dépendent de ce nœud (pour la propagation dirty)
        self._downstream: set["GNode"] = set()

    # -- câblage du graphe --------------------------------------------
    def connect_input(self, input_name: str, source_node: "GNode", output_name: str):
        sock = self._input_by_name.get(input_name)
        valid_out = {s.name for s in source_node.outputs}
        if sock is None:
            raise GraphError(f"{self.label} : entrée inconnue '{input_name}'")
        if output_name not in valid_out:
            raise GraphError(f"{source_node.label} : sortie inconnue '{output_name}'")
        entry = (source_node, output_name)
        if sock.multi:
            entries = self.incoming.setdefault(input_name, [])
            if entry in entries:
                return  # déjà connecté : ne pas marquer dirty pour rien
            entries.append(entry)
        else:
            if self.incoming.get(input_name) == [entry]:
                return  # déjà connecté à la même source : idem
            self.incoming[input_name] = [entry]
        source_node._downstream.add(self)
        self.mark_dirty()

    def disconnect_input(
        self,
        input_name: str,
        source_node: "GNode | None" = None,
        output_name: str | None = None,
    ):
        """
        Sans source_node : supprime toutes les connexions de cette entrée.
        Avec source_node/output_name : supprime uniquement cette connexion
        précise (utile pour les entrées multi).
        """
        entries = self.incoming.get(input_name)
        if not entries:
            return
        if source_node is None:
            for src, _ in entries:
                src._downstream.discard(self)
            del self.incoming[input_name]
        else:
            entry = (source_node, output_name)
            if entry not in entries:
                return  # rien à retirer : ne pas marquer dirty pour rien
            entries.remove(entry)
            source_node._downstream.discard(self)
            if not entries:
                del self.incoming[input_name]
        self.mark_dirty()

    def set_param(self, name: str, value: Any):
        if self.params.get(name) == value:
            return  # valeur inchangée : ne pas marquer dirty pour rien
        self.params[name] = value
        self.mark_dirty()

    # -- propagation dirty ------------------------------------------------
    def mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._cache = None
            for node in self._downstream:
                node.mark_dirty()

    # -- évaluation ---------------------------------------------------------
    def get_input_value(self, name: str, ctx: "EvalContext") -> Any:
        sock = self._input_by_name.get(name)
        entries = self.incoming.get(name)
        if entries:
            if sock is not None and sock.multi:
                values = []
                for src, out_name in entries:
                    result = ctx.evaluate(src)
                    values.append(result.get(out_name))
                return values
            src, out_name = entries[0]
            result = ctx.evaluate(src)
            return result.get(out_name)
        return self.params.get(name)

    def evaluate(self, ctx: "EvalContext") -> dict[str, Any]:
        """
        À surcharger dans les sous-classes : lire les entrées via
        `get_input_value`, appeler `ctx.catia.xxx(...)`, retourner un
        dict {nom_de_sortie: valeur}.
        """
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.label}#{self.id}>"


class EvalContext:
    """
    Porte le cache d'évaluation courant et l'accès à l'adaptateur CATIA,
    pour que chaque nœud puisse créer de la géométrie pendant son
    évaluation. Une instance par évaluation complète du graphe.
    """

    def __init__(self, catia_adapter):
        self.catia = catia_adapter
        self._visiting: set[int] = set()

    def evaluate(self, node: GNode) -> dict[str, Any]:
        if node._cache is not None and not node._dirty:
            return node._cache
        if node.id in self._visiting:
            raise CycleError(f"Cycle détecté sur {node}")
        self._visiting.add(node.id)
        try:
            result = node.evaluate(self)
        finally:
            self._visiting.discard(node.id)
        node._cache = result
        node._dirty = False
        return result


def topological_order(nodes: list[GNode]) -> list[GNode]:
    """Tri topologique de Kahn — utile pour le debug ou une évaluation batch explicite."""
    incoming_count = {n: len(n.incoming) for n in nodes}
    ready = [n for n in nodes if incoming_count[n] == 0]
    order: list[GNode] = []
    while ready:
        n = ready.pop()
        order.append(n)
        for downstream in n._downstream:
            incoming_count[downstream] -= 1
            if incoming_count[downstream] == 0:
                ready.append(downstream)
    if len(order) != len(nodes):
        raise CycleError("Le graphe contient un cycle.")
    return order
