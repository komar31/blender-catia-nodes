"""Adaptation bpy/bmesh du moteur DAG : sockets, arbre de nœuds, matérialisation des objets Blender."""
from __future__ import annotations

from . import node_tree, sockets


def register():
    # Les sockets doivent être enregistrés avant l'arbre de nœuds : un
    # CatiaNodeTree vide s'enregistre sans problème même sans sockets, mais
    # on garde l'ordre de dépendance logique (sockets → tree) par prudence.
    sockets.register()
    node_tree.register()


def unregister():
    node_tree.unregister()
    sockets.unregister()

