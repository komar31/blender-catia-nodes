"""
Adaptateur Blender : matérialise l'évaluation d'un GNode en objet Blender.

Équivalent, pour bpy/bmesh, de catia/adapter.py côté projet CATIA : un
registre {node.id: bpy.types.Object} pour modifier l'objet existant en place
à chaque réévaluation plutôt que d'en recréer un nouveau. Volontairement
mécanique — toute la logique géométrique (quels points, quelle direction,
etc.) est décidée en amont par les GNode dans nodes/*.py ; cet adaptateur ne
fait que dessiner ce qu'on lui donne.

Règle absolue : jamais bpy.ops.* ici. bpy.ops passe par la pile d'undo à
chaque appel, ce qui est bien trop lent pour un usage interactif (un slider
peut déclencher plusieurs évaluations par seconde) — uniquement bpy.data et
bmesh.
"""
from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector

from ..core.geometry import GCircle, GLine, GPlane, GPoint, GProfile, circle_to_profile, plane_quad_corners


class BlenderAdapter:
    """Un adaptateur par session d'édition ; partagé par tous les GNode via EvalContext.catia."""

    COLLECTION_NAME = "CATIA Nodes"

    def __init__(self):
        self._registry: dict[int, bpy.types.Object] = {}

    # -- collection cible --------------------------------------------------
    def _collection(self) -> bpy.types.Collection:
        coll = bpy.data.collections.get(self.COLLECTION_NAME)
        if coll is None:
            coll = bpy.data.collections.new(self.COLLECTION_NAME)
        scene_root = bpy.context.scene.collection
        if coll.name not in scene_root.children:
            scene_root.children.link(coll)
        return coll

    def _ensure_in_collection(self, obj: bpy.types.Object) -> None:
        coll = self._collection()
        if obj.name not in coll.objects:
            coll.objects.link(obj)

    # -- registre / ré-adoption ---------------------------------------------
    @staticmethod
    def _desired_object_name(engine_node, label: str) -> str:
        """
        Nom cible : celui du nœud bpy associé (engine_node.display_name,
        synchronisé par nodes/base.py._sync_to_engine à chaque évaluation —
        donc toujours à jour, y compris après un renommage manuel du nœud).
        Repli sur f"{label}_{id}" dans le seul cas défensif où display_name
        serait vide (ne devrait jamais arriver : un nœud bpy a toujours un
        nom). L'unicité globale (deux nœuds différents avec le même nom, ou
        collision avec un objet non-CATIA de la scène) est gérée par Blender
        lui-même : bpy.data.objects.new()/.name= suffixent automatiquement
        (".001", ...) en cas de collision.
        """
        return engine_node.display_name or f"{label}_{engine_node.id}"

    @staticmethod
    def _matches_data_kind(obj: bpy.types.Object, data_kind: str) -> bool:
        """data_kind vaut "EMPTY" ou "MESH" — mêmes valeurs que bpy.types.Object.type, comparaison directe."""
        return obj.type == data_kind

    def _get_or_create(self, engine_node, label: str, data_kind: str) -> bpy.types.Object:
        """
        Cherche dans l'ordre : (1) le registre en mémoire, (2) un objet
        existant portant le nom précédemment stocké sur le GNode (ré-adoption
        après rechargement du .blend — le registre en mémoire est reparti de
        zéro mais l'objet Blender, lui, a survécu), (3) un objet déjà présent
        portant le nom désiré et non revendiqué par un autre nœud — filet de
        sécurité vérifié nécessaire en conditions réelles : juste après
        l'ouverture d'un fichier, un GNode neuf peut être reconstruit à un
        moment où object_name (StringProperty bpy) se lit encore vide alors
        que le nom désiré correspond à un objet bien réel et déjà présent —
        sans ce filet, un doublon était créé (Blender suffixant ".001" sur la
        collision) au lieu de ré-adopter l'objet existant, (4) sinon crée un
        objet neuf. Dans tous les cas, l'objet est ensuite renommé si besoin
        pour rester aligné sur le nom actuel du nœud associé.

        Cas particulier (Intersection) : le type de résultat peut basculer
        d'une évaluation à l'autre (point ou droite, selon ce qui est
        connecté) — donc le data_kind demandé pour un même engine_node peut
        changer. Un objet Blender ne peut pas être reconverti Empty <-> Mesh
        en place ; si l'objet retrouvé ne correspond plus au data_kind
        demandé, il est supprimé et recréé du bon type ci-dessous.
        """
        obj = self._registry.get(engine_node.id)
        if obj is None or obj.name not in bpy.data.objects:
            stored_name = getattr(engine_node, "object_name", "")
            obj = bpy.data.objects.get(stored_name) if stored_name else None
            if obj is not None:
                self._registry[engine_node.id] = obj
                self._ensure_in_collection(obj)

        if obj is not None and not self._matches_data_kind(obj, data_kind):
            old_data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if isinstance(old_data, bpy.types.Mesh) and old_data.users == 0:
                bpy.data.meshes.remove(old_data)
            self._registry.pop(engine_node.id, None)
            obj = None

        if obj is None:
            desired_name = self._desired_object_name(engine_node, label)
            existing = bpy.data.objects.get(desired_name)
            if existing is not None and existing not in self._registry.values():
                obj = existing
                self._ensure_in_collection(obj)
            else:
                if data_kind == "EMPTY":
                    obj = bpy.data.objects.new(desired_name, None)
                    obj.empty_display_type = "PLAIN_AXES"
                else:
                    mesh = bpy.data.meshes.new(desired_name)
                    obj = bpy.data.objects.new(desired_name, mesh)
                self._ensure_in_collection(obj)
            self._registry[engine_node.id] = obj

        desired_name = self._desired_object_name(engine_node, label)
        if obj.name != desired_name:
            obj.name = desired_name  # Blender suffixe automatiquement en cas de collision
        engine_node.object_name = obj.name
        return obj

    # -- réécriture de mesh --------------------------------------------------
    @staticmethod
    def _rebuild_mesh(obj: bpy.types.Object, verts, edges=(), faces=(), skin_radius: float | None = None) -> None:
        """
        Réécrit entièrement la géométrie de `obj.data` via bmesh (jamais
        bpy.ops). `skin_radius` (Line/Join uniquement, voir
        _ensure_skin_modifier) peuple la couche de données "skin" sur chaque
        vertex au moment même de la construction — bien plus simple que de la
        repeupler après coup, et de toute façon nécessaire : clear_geometry()
        supprimerait une couche posée séparément à chaque réévaluation.

        Bug vérifié en conditions réelles : la couche skin doit être créée
        AVANT les vertices (bm.verts.layers.skin.verify() en premier), pas
        après — dans l'autre ordre, ajouter une couche de custom-data
        réalloue le bloc interne du BMesh et invalide les références BMVert
        déjà obtenues ("BMesh data of type BMVert has been removed" dès
        qu'on y touche ensuite, y compris pour créer les edges). Deuxième
        point vérifié : le modifier Skin réclame au moins un sommet marqué
        "racine" (use_root) par îlot de mesh connecté, sinon Blender logue un
        avertissement à chaque évaluation ("No valid root vertex found") —
        Line et Join n'ayant chacun qu'un seul îlot, marquer le premier
        sommet suffit.
        """
        bm = bmesh.new()
        skin_layer = bm.verts.layers.skin.verify() if skin_radius is not None else None
        bm_verts = [bm.verts.new(v) for v in verts]
        bm.verts.ensure_lookup_table()
        if skin_layer is not None:
            for bv in bm_verts:
                bv[skin_layer].radius = (skin_radius, skin_radius)
            if bm_verts:
                bm_verts[0][skin_layer].use_root = True
        for i, j in edges:
            bm.edges.new((bm_verts[i], bm_verts[j]))
        for face in faces:
            bm.faces.new(tuple(bm_verts[i] for i in face))
        bm.normal_update()
        obj.data.clear_geometry()
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

    # -- lisibilité des entités en fil (Line, Join, Circle) --------------------
    SKIN_MODIFIER_NAME = "CATIA Nodes — épaisseur"
    SKIN_DEFAULT_RADIUS = 0.02

    @classmethod
    def _ensure_skin_modifier(cls, obj: bpy.types.Object) -> None:
        """
        Line/Join n'ont que des edges (jamais de face) : ils restent des
        traits de 1px même en shading Solide, quasi invisibles à l'usage.
        Point vérifié avant implémentation : le modifier Wireframe ignore
        explicitement les edges isolés (qui ne bordent aucune face) — donc
        inutilisable ici. Le modifier Skin, lui, est spécifiquement conçu
        pour donner du volume à un squelette d'edges (y compris aux
        embranchements, ex: le triangle fermé de Join) : non destructif côté
        mesh (le rayon vit dans une couche de données "skin" par vertex, pas
        dans la géométrie elle-même), réglable ensuite librement par
        l'utilisateur (rayon par sommet éditable en Edit Mode, Ctrl+A/Ctrl+X).
        Modifier ajouté une seule fois : les évaluations suivantes ne le
        réinitialisent pas.
        """
        if cls.SKIN_MODIFIER_NAME not in obj.modifiers:
            obj.modifiers.new(name=cls.SKIN_MODIFIER_NAME, type="SKIN")

    @staticmethod
    def _mark_construction_only(obj: bpy.types.Object) -> None:
        """
        Point/Line/Plane/Join/Circle sont de la géométrie de construction
        (repères et références), jamais le résultat final — exclus du rendu
        (Cycles, etc. : "Disable in Renders"). Extrude n'appelle jamais ceci :
        c'est le seul nœud à produire un résultat destiné à être rendu.
        Réappliqué à chaque évaluation pour rester verrouillé (même principe
        que Plane.display_type = "WIRE").
        """
        obj.hide_render = True

    # -- upsert par type d'entité --------------------------------------------
    def _upsert_point_object(self, engine_node, label: str, gpoint: GPoint) -> bpy.types.Object:
        """
        Empty repositionné à `gpoint.position` — représentation commune à
        Point et à tout autre nœud dont le résultat est un GPoint
        (Intersection, Projection) : `label` ne sert qu'au nom de repli
        défensif de _get_or_create (jamais vraiment utilisé, voir sa
        docstring), le nom réel vient toujours du nœud.
        """
        obj = self._get_or_create(engine_node, label, "EMPTY")
        obj.location = gpoint.position.copy()
        self._mark_construction_only(obj)
        return obj

    def upsert_point(self, engine_node, gpoint: GPoint) -> bpy.types.Object:
        """Point → Empty repositionné à `gpoint.position`."""
        return self._upsert_point_object(engine_node, "Point", gpoint)

    def _upsert_curve_object(self, engine_node, label: str, gline: GLine) -> bpy.types.Object:
        """
        Mesh 2 vertices + 1 edge en fil, coordonnées écrites en espace monde —
        représentation commune à Line et à tout autre nœud dont le résultat
        est un GLine (Projection, Intersection, Parallel Curve) : `label` ne
        sert qu'au nom de repli défensif de _get_or_create (jamais vraiment
        utilisé, voir sa docstring), le nom réel vient toujours du nœud.
        """
        obj = self._get_or_create(engine_node, label, "MESH")
        p0 = gline.origin
        p1 = gline.origin + gline.direction * gline.length
        self._rebuild_mesh(obj, [p0, p1], edges=[(0, 1)], skin_radius=self.SKIN_DEFAULT_RADIUS)
        self._ensure_skin_modifier(obj)
        self._mark_construction_only(obj)
        return obj

    def upsert_line(self, engine_node, gline: GLine) -> bpy.types.Object:
        """Line → mesh 2 vertices + 1 edge, coordonnées écrites en espace monde."""
        return self._upsert_curve_object(engine_node, "Line", gline)

    def upsert_projection(self, engine_node, gline: GLine) -> bpy.types.Object:
        """Projection (résultat droite : Line projetée) → même représentation que Line."""
        return self._upsert_curve_object(engine_node, "Projection", gline)

    def upsert_projection_point(self, engine_node, gpoint: GPoint) -> bpy.types.Object:
        """Projection (résultat point : Point projeté) → Empty, même représentation que Point."""
        return self._upsert_point_object(engine_node, "Projection", gpoint)

    def upsert_projection_profile(self, engine_node, profile: GProfile) -> bpy.types.Object:
        """Projection (résultat profil : Join/Polyline/Curve projeté) → même représentation."""
        return self._upsert_profile_object(engine_node, "Projection", profile)

    def upsert_intersection(self, engine_node, gline: GLine) -> bpy.types.Object:
        """Intersection (résultat droite : Plane ∩ Plane) → même représentation que Line."""
        return self._upsert_curve_object(engine_node, "Intersection", gline)

    def upsert_intersection_point(self, engine_node, gpoint: GPoint) -> bpy.types.Object:
        """Intersection (résultat point : Line ∩ Plane ou Line ∩ Line) → Empty, même représentation que Point."""
        return self._upsert_point_object(engine_node, "Intersection", gpoint)

    def upsert_parallel_curve(self, engine_node, gline: GLine) -> bpy.types.Object:
        """Parallel Curve → même représentation que Line (résultat : un GLine décalé, parallèle à la courbe source)."""
        return self._upsert_curve_object(engine_node, "Parallel Curve", gline)

    def upsert_plane(self, engine_node, gplane: GPlane) -> bpy.types.Object:
        """
        Plane → quad borné (proxy visuel) + custom properties plane_origin/
        plane_normal qui portent la donnée analytique réelle (le plan est
        infini conceptuellement). Affichage viewport calé sur "Wire" (Object
        Properties > Viewport Display > Display As) — c'est une référence de
        construction, pas une surface à regarder pleine ; réappliqué à chaque
        évaluation pour rester verrouillé même si l'utilisateur le change
        manuellement.
        """
        obj = self._get_or_create(engine_node, "Plane", "MESH")
        corners = plane_quad_corners(gplane)
        self._rebuild_mesh(obj, list(corners), faces=[(0, 1, 2, 3)])
        obj["plane_origin"] = tuple(gplane.origin)
        obj["plane_normal"] = tuple(gplane.normal)
        obj.display_type = "WIRE"
        self._mark_construction_only(obj)
        return obj

    def _upsert_profile_object(self, engine_node, label: str, profile: GProfile) -> bpy.types.Object:
        """
        Mesh en fil (edges seulement, jamais de face) représentant un profil,
        fermé ou ouvert selon profile.closed — représentation commune à Join
        (profil assemblé à partir d'edges), Polyline (segments droits entre
        points) et Curve (courbe de Bézier échantillonnée), toutes trois de
        simples GProfile du point de vue de ce module.
        """
        obj = self._get_or_create(engine_node, label, "MESH")
        n = len(profile.vertices)
        edge_count = n if profile.closed else n - 1
        edges = [(i, (i + 1) % n) for i in range(edge_count)]
        self._rebuild_mesh(obj, list(profile.vertices), edges=edges, skin_radius=self.SKIN_DEFAULT_RADIUS)
        self._ensure_skin_modifier(obj)
        self._mark_construction_only(obj)
        return obj

    def upsert_join(self, engine_node, profile: GProfile) -> bpy.types.Object:
        """
        Join → mesh en fil représentant le profil assemblé. Sans ça, Join
        n'apparaissait pas dans l'Outliner : seul nœud géométrique de
        l'addon à ne matérialiser aucun objet.
        """
        return self._upsert_profile_object(engine_node, "Join", profile)

    def upsert_polyline(self, engine_node, profile: GProfile) -> bpy.types.Object:
        """Polyline → même représentation que Join (résultat : des segments droits entre points connectés)."""
        return self._upsert_profile_object(engine_node, "Polyline", profile)

    def upsert_curve(self, engine_node, profile: GProfile) -> bpy.types.Object:
        """Curve → même représentation que Join/Polyline (résultat : une courbe de Bézier échantillonnée)."""
        return self._upsert_profile_object(engine_node, "Curve", profile)

    def upsert_circle(self, engine_node, gcircle: GCircle) -> bpy.types.Object:
        """
        Circle → mesh en fil (boucle fermée de gcircle.segments edges, jamais
        de face — même logique que Line/Join). Le polygone d'approximation
        (core.geometry.circle_to_profile) est le même que celui utilisé si ce
        Circle est branché dans Extrude — une seule résolution, pas deux
        calculs séparés qui pourraient diverger.
        """
        obj = self._get_or_create(engine_node, "Circle", "MESH")
        profile = circle_to_profile(gcircle)
        n = len(profile.vertices)
        edges = [(i, (i + 1) % n) for i in range(n)]
        self._rebuild_mesh(obj, list(profile.vertices), edges=edges, skin_radius=self.SKIN_DEFAULT_RADIUS)
        self._ensure_skin_modifier(obj)
        self._mark_construction_only(obj)
        return obj

    def upsert_extrude(
        self,
        engine_node,
        profile: GProfile,
        direction: Vector,
        length: float,
    ) -> bpy.types.Object:
        """
        Extrude → solide (profil fermé, bmesh.ops.extrude_face_region sur la
        face construite depuis profile.vertices) ou surface ruban (profil
        ouvert, bmesh.ops.extrude_edge_only sur la chaîne d'edges), translaté
        de `direction * length`. `direction` est supposée déjà normalisée par
        l'appelant (nodes/extrude.py décide de la direction par défaut — la
        normale de Newell du profil — cet adaptateur ne fait qu'exécuter).

        Point moins vérifié que le reste de ce fichier : extrude_edge_only
        (cas profil ouvert) suit le même pattern documenté que
        extrude_face_region (filtrer ret["geom"] sur BMVert puis translate),
        mais je l'ai testé moins longuement en conditions réelles.
        """
        obj = self._get_or_create(engine_node, "Extrude", "MESH")
        bm = bmesh.new()
        bm_verts = [bm.verts.new(v) for v in profile.vertices]
        bm.verts.ensure_lookup_table()

        if profile.closed:
            face = bm.faces.new(bm_verts)
            bm.faces.ensure_lookup_table()
            bm.normal_update()
            ret = bmesh.ops.extrude_face_region(bm, geom=[face])
        else:
            edges = [bm.edges.new((bm_verts[i], bm_verts[i + 1])) for i in range(len(bm_verts) - 1)]
            bm.edges.ensure_lookup_table()
            ret = bmesh.ops.extrude_edge_only(bm, edges=edges)

        new_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=new_verts, vec=direction * length)
        bm.normal_update()

        obj.data.clear_geometry()
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        return obj

    # -- suppression ----------------------------------------------------------
    def remove(self, engine_node) -> None:
        """Supprime l'objet Blender associé (et sa mesh si plus référencée)."""
        obj = self._registry.pop(engine_node.id, None)
        stored_name = getattr(engine_node, "object_name", "")
        if obj is None and stored_name:
            obj = bpy.data.objects.get(stored_name)
        if obj is None:
            return
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
        engine_node.object_name = ""
