"""
Nœuds "Parameters" : Float, Integer, Boolean, String — chacun un simple
littéral constant exposé en sortie, aucune entrée. Contrairement aux autres
nœuds, la valeur ne vit pas sur un socket (une sortie n'a jamais de
default_value éditable — voir sockets.py.draw() : is_output=True affiche
toujours un label) mais directement sur une propriété du nœud bpy, à la
façon du nœud "Value" natif de Geometry Nodes.

Regroupés dans un seul fichier + un seul sous-menu Add ("Parameters") car ce
sont quatre variations mineures du même schéma.
"""
from __future__ import annotations

import bpy

from ..core.engine import GNode, Socket, SocketType
from .base import CatiaBaseNode, handle_node_property_changed


def _on_value_changed(self, context):
    """Callback update= commun aux trois nœuds : réactivité immédiate, comme les sockets."""
    handle_node_property_changed(self, context)


class FloatGNode(GNode):
    label = "Float"
    outputs = [Socket("value", SocketType.NUMBER)]

    def evaluate(self, ctx):
        return {"value": self.params.get("value", 0.0)}


class IntegerGNode(GNode):
    label = "Integer"
    outputs = [Socket("value", SocketType.INTEGER)]

    def evaluate(self, ctx):
        return {"value": self.params.get("value", 0)}


class BooleanGNode(GNode):
    label = "Boolean"
    outputs = [Socket("value", SocketType.BOOLEAN)]

    def evaluate(self, ctx):
        return {"value": self.params.get("value", False)}


class StringGNode(GNode):
    label = "String"
    outputs = [Socket("value", SocketType.STRING)]

    def evaluate(self, ctx):
        return {"value": self.params.get("value", "")}


class FloatNode(CatiaBaseNode, bpy.types.Node):
    """Constante flottante — sortie 'value' (NUMBER)."""

    bl_idname = "CatiaNodeFloat"
    bl_label = "Float"

    engine_class = FloatGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    value: bpy.props.FloatProperty(name="Valeur", default=0.0, update=_on_value_changed)

    def draw_buttons(self, context, layout):
        layout.prop(self, "value", text="")
        super().draw_buttons(context, layout)

    def _sync_to_engine(self, engine_node) -> None:
        super()._sync_to_engine(engine_node)
        engine_node.set_param("value", self.value)


class IntegerNode(CatiaBaseNode, bpy.types.Node):
    """Constante entière — sortie 'value' (INTEGER)."""

    bl_idname = "CatiaNodeInteger"
    bl_label = "Integer"

    engine_class = IntegerGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    value: bpy.props.IntProperty(name="Valeur", default=0, update=_on_value_changed)

    def draw_buttons(self, context, layout):
        layout.prop(self, "value", text="")
        super().draw_buttons(context, layout)

    def _sync_to_engine(self, engine_node) -> None:
        super()._sync_to_engine(engine_node)
        engine_node.set_param("value", self.value)


class BooleanNode(CatiaBaseNode, bpy.types.Node):
    """Constante booléenne — sortie 'value' (BOOLEAN)."""

    bl_idname = "CatiaNodeBoolean"
    bl_label = "Boolean"

    engine_class = BooleanGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    value: bpy.props.BoolProperty(name="Valeur", default=False, update=_on_value_changed)

    def draw_buttons(self, context, layout):
        layout.prop(self, "value", text="")
        super().draw_buttons(context, layout)

    def _sync_to_engine(self, engine_node) -> None:
        super()._sync_to_engine(engine_node)
        engine_node.set_param("value", self.value)


class StringNode(CatiaBaseNode, bpy.types.Node):
    """Constante texte — sortie 'value' (STRING)."""

    bl_idname = "CatiaNodeString"
    bl_label = "String"

    engine_class = StringGNode

    node_uuid: bpy.props.StringProperty(default="")
    obj_name: bpy.props.StringProperty(default="")
    error_message: bpy.props.StringProperty(default="")
    value: bpy.props.StringProperty(name="Valeur", default="", update=_on_value_changed)

    def draw_buttons(self, context, layout):
        layout.prop(self, "value", text="")
        super().draw_buttons(context, layout)

    def _sync_to_engine(self, engine_node) -> None:
        super()._sync_to_engine(engine_node)
        engine_node.set_param("value", self.value)


class NODE_MT_catia_params(bpy.types.Menu):
    """Sous-menu Add > Parameters."""

    bl_idname = "NODE_MT_catia_params"
    bl_label = "Parameters"

    def draw(self, context):
        layout = self.layout
        for idname, label in (
            (FloatNode.bl_idname, "Float"),
            (IntegerNode.bl_idname, "Integer"),
            (BooleanNode.bl_idname, "Boolean"),
            (StringNode.bl_idname, "String"),
        ):
            op = layout.operator("node.add_node", text=label)
            op.type = idname
            op.use_transform = True


classes = (FloatNode, IntegerNode, BooleanNode, StringNode, NODE_MT_catia_params)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
