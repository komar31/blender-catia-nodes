"""
NodeTree custom : l'éditeur de nœuds CATIA, indépendant de Geometry Nodes.

`update()` est appelé automatiquement par Blender à chaque ajout/retrait de
lien (ou de socket) dans l'éditeur — il délègue entièrement à
nodes/base.py.evaluate_tree(), qui resynchronise engine_node.incoming depuis
les liens UI avant d'évaluer (même principe que sync_connections() du projet
CATIA : pas d'ajout/retrait incrémental fragile, on réinitialise puis on
reconstruit depuis zéro à chaque fois). La garde anti-réentrance vit dans
evaluate_tree() lui-même, pas ici — voir sa docstring : le nœud Join fait
grandir/rétrécir ses sockets à chaque évaluation, ce qui redéclenche
update() de façon synchrone quel que soit le déclencheur initial.
"""
from __future__ import annotations

import bpy


class CatiaNodeTree(bpy.types.NodeTree):
    """Arbre de nœuds custom façon CATIA : construction d'entités géométriques dans Blender."""

    bl_idname = "CatiaNodeTree"
    bl_label = "CATIA Nodes"
    bl_icon = "NODETREE"

    def update(self):
        from ..nodes.base import evaluate_tree

        evaluate_tree(self)


classes = (CatiaNodeTree,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
