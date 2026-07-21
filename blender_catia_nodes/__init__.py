"""
CATIA Nodes — addon Blender (Extension, voir blender_manifest.toml pour les
métadonnées — nom/version/licence ne vivent plus dans un bl_info ici).

Système de nœuds custom façon CATIA (construction d'entités géométriques par
différentes méthodes : Point, Line, Plane, Extrude) affiché dans l'éditeur de
nœuds natif de Blender, via un NodeTree entièrement custom (PAS Geometry
Nodes). Le moteur d'évaluation (DAG, cache, dirty propagation) est
core/engine.py, indépendant de bpy — voir blender_adapter/ pour le pont vers
bpy/bmesh et nodes/ pour les nœuds concrets.
"""
from __future__ import annotations

from . import blender_adapter, nodes, ui


def register():
    # Ordre de dépendance : sockets → arbre de nœuds (blender_adapter), puis
    # nœuds concrets qui les référencent, puis UI qui référence les nœuds.
    blender_adapter.register()
    nodes.register()
    ui.register()


def unregister():
    ui.unregister()
    nodes.unregister()
    blender_adapter.unregister()
