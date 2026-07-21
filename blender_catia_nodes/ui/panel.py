"""
Panneau latéral (N-panel) de l'éditeur CATIA Nodes.

Le seul contrôle exposé est le bouton "Réévaluer tout" : un filet de
sécurité / debug, puisque la réactivité normale (sliders, changement de mode,
câblage) est censée être immédiate — voir nodes/base.py.evaluate_tree(),
appelée automatiquement par tous les callbacks update=.
"""
from __future__ import annotations

import bpy


def _active_catia_tree(context):
    """Retourne l'arbre CATIA actuellement affiché dans l'éditeur de nœuds, ou None."""
    space = context.space_data
    if space is None or space.type != "NODE_EDITOR":
        return None
    if space.tree_type != "CatiaNodeTree":
        return None
    return space.edit_tree


class CATIA_OT_reevaluate_all(bpy.types.Operator):
    """Réévalue tous les nœuds de l'arbre CATIA actif (bon marché grâce au cache de core/engine.py)."""

    bl_idname = "catia.reevaluate_all"
    bl_label = "Réévaluer tout"
    bl_description = "Réévalue tous les nœuds de l'arbre CATIA actif (filet de sécurité — la mise à jour est normalement immédiate)"

    @classmethod
    def poll(cls, context):
        return _active_catia_tree(context) is not None

    def execute(self, context):
        from ..nodes.base import evaluate_tree

        evaluate_tree(_active_catia_tree(context))
        return {"FINISHED"}


class CATIA_PT_panel(bpy.types.Panel):
    """N-panel visible uniquement quand un CatiaNodeTree est affiché dans l'éditeur de nœuds."""

    bl_idname = "CATIA_PT_panel"
    bl_label = "CATIA Nodes"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "CATIA"

    @classmethod
    def poll(cls, context):
        return _active_catia_tree(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.operator(CATIA_OT_reevaluate_all.bl_idname, icon="FILE_REFRESH")


classes = (CATIA_OT_reevaluate_all, CATIA_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
