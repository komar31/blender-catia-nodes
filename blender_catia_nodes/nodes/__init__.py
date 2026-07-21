"""
Nœuds concrets : Point/Line/Plane/Circle/Polyline/Curve/Projection/
Intersection/Parallel Curve sous le sous-menu "Wireframe" ; Join/Extrude en
entrées directes du menu Add ; Float/Integer/Boolean/String sous
"Parameters" ; Operations sous "Math". Ce module câble aussi le menu Add de
l'éditeur de nœuds.

Pattern `self.node_operator(layout, bl_idname)` (entrées directes) vérifié
contre le template officiel Blender (scripts/templates_py/custom_nodes.py,
branche main) : c'est une méthode propre à bpy.types.NODE_MT_add (et
NODE_MT_swap), pas une méthode générique de Menu — d'où l'usage de
l'opérateur standard "node.add_node" (documenté, disponible partout) pour les
sous-menus (Wireframe/Parameters/Math), qui ne sont PAS des instances de
NODE_MT_add.
"""
from __future__ import annotations

import bpy

from . import (
    base,
    circle,
    curve,
    extrude,
    intersection,
    join,
    line,
    math_ops,
    parallel_curve,
    params,
    plane,
    point,
    polyline,
    projection,
)

_MODULES = (
    point,
    line,
    plane,
    circle,
    polyline,
    curve,
    projection,
    intersection,
    parallel_curve,
    join,
    extrude,
    params,
    math_ops,
)

# bl_idname de chaque nœud regroupé sous le sous-menu Add > Wireframe.
WIREFRAME_NODE_IDNAMES = (
    (point.PointNode.bl_idname, "Point"),
    (line.LineNode.bl_idname, "Line"),
    (plane.PlaneNode.bl_idname, "Plane"),
    (circle.CircleNode.bl_idname, "Circle"),
    (polyline.PolylineNode.bl_idname, "Polyline"),
    (curve.CurveNode.bl_idname, "Curve"),
    (projection.ProjectionNode.bl_idname, "Projection"),
    (intersection.IntersectionNode.bl_idname, "Intersection"),
    (parallel_curve.ParallelCurveNode.bl_idname, "Parallel Curve"),
)

# bl_idname de chaque nœud en entrée directe du menu Add (hors sous-menus).
NODE_IDNAMES = (
    join.JoinNode.bl_idname,
    extrude.ExtrudeNode.bl_idname,
)


class NODE_MT_catia_wireframe(bpy.types.Menu):
    """Sous-menu Add > Wireframe (Point/Line/Plane)."""

    bl_idname = "NODE_MT_catia_wireframe"
    bl_label = "Wireframe"

    def draw(self, context):
        layout = self.layout
        for idname, label in WIREFRAME_NODE_IDNAMES:
            op = layout.operator("node.add_node", text=label)
            op.type = idname
            op.use_transform = True


def draw_add_menu(self, context):
    """Ajoute les nœuds CATIA (+ sous-menus) au menu Add, uniquement sur un CatiaNodeTree."""
    if context.space_data.tree_type != "CatiaNodeTree":
        return
    layout = self.layout
    layout.menu(NODE_MT_catia_wireframe.bl_idname)
    for idname in NODE_IDNAMES:
        self.node_operator(layout, idname)
    layout.separator()
    layout.menu(params.NODE_MT_catia_params.bl_idname)
    layout.menu(math_ops.NODE_MT_catia_math.bl_idname)


def register():
    base.register()  # hook load_post : voir base.py._on_load_post
    for module in _MODULES:
        module.register()
    bpy.utils.register_class(NODE_MT_catia_wireframe)
    bpy.types.NODE_MT_add.append(draw_add_menu)
    bpy.types.NODE_MT_swap.append(draw_add_menu)


def unregister():
    bpy.types.NODE_MT_add.remove(draw_add_menu)
    bpy.types.NODE_MT_swap.remove(draw_add_menu)
    bpy.utils.unregister_class(NODE_MT_catia_wireframe)
    for module in reversed(_MODULES):
        module.unregister()
    base.unregister()
