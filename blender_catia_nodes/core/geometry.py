"""
Représentations géométriques analytiques du Niveau 1 (Point, Line, Plane).

Ces dataclasses circulent dans les sockets POINT/CURVE/SURFACE du moteur
(core/engine.py) et portent la donnée exacte — l'objet Blender associé
(Empty, mesh 2 vertices, quad) n'est qu'une cible d'affichage, jamais une
source de données pour les nœuds en aval. Toute la géométrie de ce niveau
se calcule ici, en algèbre vectorielle fermée sur ces dataclasses.

Indépendant de bpy sauf pour mathutils.Vector/Quaternion, disponibles dès
qu'on est dans l'interpréteur Python embarqué de Blender.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from mathutils import Quaternion, Vector

# Tolérance utilisée pour détecter les configurations dégénérées
# (ligne parallèle à un plan, normale quasi nulle, etc.).
EPSILON = 1e-6


@dataclass(frozen=True)
class GPoint:
    """Point analytique exact."""
    position: Vector


@dataclass(frozen=True)
class GLine:
    """
    Segment analytique exact : origin est le point de départ, direction est
    normalisée, et l'extrémité se calcule par origin + direction * length.
    """
    origin: Vector
    direction: Vector
    length: float


@dataclass(frozen=True)
class GPlane:
    """
    Repère de plan complet (le plan est conceptuellement infini ; width/height
    ne bornent que le quad de visualisation). u_axis/v_axis sont normalisés
    et orthogonaux entre eux et à normal.
    """
    origin: Vector
    normal: Vector
    u_axis: Vector
    v_axis: Vector
    width: float = 1.0
    height: float = 1.0


@dataclass(frozen=True)
class GCircle:
    """
    Cercle analytique exact — sortie du nœud Circle (nodes/circle.py).
    `segments` (déjà clampée [3, 128] côté nœud) voyage avec le cercle : à la
    fois la résolution du fil affiché (BlenderAdapter.upsert_circle) ET celle
    du polygone utilisé si ce cercle est extrudé (voir circle_to_profile) —
    un seul réglage pour les deux, plutôt que deux résolutions désynchronisées.
    """
    center: Vector
    normal: Vector
    radius: float
    segments: int = 32


@dataclass(frozen=True)
class GProfile:
    """
    Profil reconstruit par le nœud Join à partir de plusieurs segments
    chaînés (voir join_edges_into_profile) : liste ordonnée de sommets,
    fermé (polygone, ex. triangle à 3 edges) ou ouvert (polyligne).
    """
    vertices: tuple[Vector, ...]
    closed: bool


def point_on_line(line: GLine, t: float) -> Vector:
    """Point à l'abscisse normalisée t ∈ [0, 1] le long du segment."""
    return line.origin + line.direction * (t * line.length)


def line_plane_intersection(line: GLine, plane: GPlane) -> Optional[Vector]:
    """
    Intersection de la droite portée par `line` (non bornée par sa longueur —
    on prolonge la direction, comme le ferait CATIA) avec le plan infini porté
    par `plane`. Retourne None si la droite est parallèle au plan (y compris
    si elle est contenue dedans : cas dégénéré non supporté ici).
    """
    denom = line.direction.dot(plane.normal)
    if abs(denom) < EPSILON:
        return None
    t = (plane.origin - line.origin).dot(plane.normal) / denom
    return line.origin + line.direction * t


def project_vector_on_plane(position: Vector, plane: GPlane) -> Vector:
    """
    Projection orthogonale d'une position brute (Vector) sur le plan infini
    porté par `plane` — variante de project_point_on_plane qui n'exige pas
    d'envelopper la position dans un GPoint, utile pour les extrémités d'une
    GLine (voir nodes/projection.py).
    """
    offset = (position - plane.origin).dot(plane.normal)
    return position - plane.normal * offset


def project_point_on_plane(point: GPoint, plane: GPlane) -> Vector:
    """Projection orthogonale de `point` sur le plan infini porté par `plane`."""
    return project_vector_on_plane(point.position, plane)


def project_profile_on_plane(profile: GProfile, plane: GPlane) -> GProfile:
    """
    Projection orthogonale de chaque sommet de `profile` sur le plan infini
    porté par `plane` — conserve profile.closed (voir nodes/projection.py).
    """
    return GProfile(
        vertices=tuple(project_vector_on_plane(v, plane) for v in profile.vertices),
        closed=profile.closed,
    )


def plane_quad_corners(plane: GPlane) -> tuple[Vector, Vector, Vector, Vector]:
    """
    Les 4 coins du quad de visualisation, calculés analytiquement depuis
    origin/u_axis/v_axis/width/height — jamais lus depuis un mesh Blender.
    Ordre CCW (vu depuis le sens de `normal`), pour une face bien orientée.
    """
    half_u = plane.u_axis * (plane.width / 2.0)
    half_v = plane.v_axis * (plane.height / 2.0)
    return (
        plane.origin - half_u - half_v,
        plane.origin + half_u - half_v,
        plane.origin + half_u + half_v,
        plane.origin - half_u + half_v,
    )


def stable_uv_basis(normal: Vector, rotation_deg: float = 0.0) -> tuple[Vector, Vector]:
    """
    Base orthonormée (u, v) du plan orthogonal à `normal`, choisie de façon
    déterministe (donc stable d'une évaluation à l'autre) : world_up = +Z,
    sauf si normal est quasi colinéaire à Z auquel cas on bascule sur +X.
    `rotation_deg` fait tourner (u, v) autour de `normal`.
    """
    normal = normal.normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    if abs(normal.dot(world_up)) > 0.999:
        world_up = Vector((1.0, 0.0, 0.0))
    u_axis = world_up.cross(normal).normalized()
    v_axis = normal.cross(u_axis).normalized()
    if rotation_deg:
        quat = Quaternion(normal, math.radians(rotation_deg))
        u_axis = quat @ u_axis
        v_axis = quat @ v_axis
    return u_axis, v_axis


def join_edges_into_profile(edges: list[GLine]) -> Optional[GProfile]:
    """
    Enchaîne des segments dans l'ordre donné (celui des sockets edge_N du
    nœud Join, pas l'ordre de câblage) pour reconstruire un profil : chaque
    segment doit rejoindre le suivant par une extrémité commune (tolérance
    EPSILON). Retourne None si un maillon ne rejoint pas le précédent
    (profil invalide) — c'est à l'appelant (JoinGNode.evaluate) de lever une
    GraphError avec un message adapté, comme pour les autres helpers de ce
    module. Un profil est fermé si le dernier sommet rejoint le premier.
    """
    if not edges:
        return None

    first = edges[0]
    vertices = [first.origin]
    current = first.origin + first.direction * first.length
    vertices.append(current)

    for edge in edges[1:]:
        start = edge.origin
        end = edge.origin + edge.direction * edge.length
        if (start - current).length < EPSILON:
            current = end
        elif (end - current).length < EPSILON:
            current = start
        else:
            return None  # ce segment ne rejoint pas le précédent
        vertices.append(current)

    closed = (vertices[-1] - vertices[0]).length < EPSILON
    if closed:
        vertices = vertices[:-1]  # dernier sommet dupliqué avec le premier : on l'enlève
    return GProfile(vertices=tuple(vertices), closed=closed)


def profile_normal_newell(profile: GProfile) -> Optional[Vector]:
    """
    Normale du profil au sens de Newell (moyenne pondérée des produits
    vectoriels des sommets successifs) : robuste même si les sommets ne sont
    pas parfaitement coplanaires, contrairement à un simple produit vectoriel
    entre deux arêtes. Généralise proprement l'ancien fallback "normale du
    plan" pour un profil quelconque (fermé ou ouvert). None si le profil a
    moins de 3 sommets ou est dégénéré (normale quasi nulle).
    """
    vertices = profile.vertices
    if len(vertices) < 3:
        return None
    normal = Vector((0.0, 0.0, 0.0))
    n = len(vertices)
    for i in range(n):
        cur = vertices[i]
        nxt = vertices[(i + 1) % n]
        normal = normal + Vector((
            (cur.y - nxt.y) * (cur.z + nxt.z),
            (cur.z - nxt.z) * (cur.x + nxt.x),
            (cur.x - nxt.x) * (cur.y + nxt.y),
        ))
    if normal.length < EPSILON:
        return None
    return normal.normalized()


def circumcenter_normal_radius(p1: Vector, p2: Vector, p3: Vector) -> Optional[tuple[Vector, Vector, float]]:
    """
    Cercle circonscrit au triangle (p1, p2, p3) : (centre, normale, rayon).
    Formule vectorielle fermée (produit vectoriel), sans passage par une
    projection 2D intermédiaire — vérifiée contre deux cas connus (triangle
    équilatéral inscrit dans le cercle unité ; triangle rectangle, où
    l'hypoténuse est un diamètre). None si les trois points sont colinéaires
    (aucun cercle défini).
    """
    a = p2 - p1
    b = p3 - p1
    cross_ab = a.cross(b)
    denom = 2.0 * cross_ab.dot(cross_ab)
    if denom < EPSILON:
        return None
    numerator = (a.dot(a) * b - b.dot(b) * a).cross(cross_ab)
    to_center = numerator / denom
    center = p1 + to_center
    radius = to_center.length
    normal = cross_ab.normalized()
    return center, normal, radius


def line_line_intersection(line1: GLine, line2: GLine) -> Optional[Vector]:
    """
    Point d'intersection de deux droites (portées par line1/line2, non
    bornées par leur longueur — comme line_plane_intersection). Calcule le
    point le plus proche sur chaque droite (formule fermée standard à partir
    des produits scalaires des directions) puis vérifie que ces deux points
    coïncident (tolérance EPSILON) : sinon les droites sont parallèles ou
    gauches (non coplanaires), auquel cas aucune intersection réelle
    n'existe. Retourne None dans les deux cas dégénérés.
    """
    d1 = line1.direction
    d2 = line2.direction
    w0 = line1.origin - line2.origin
    a = d1.dot(d1)
    b = d1.dot(d2)
    c = d2.dot(d2)
    d = d1.dot(w0)
    e = d2.dot(w0)
    denom = a * c - b * b
    if abs(denom) < EPSILON:
        return None  # droites parallèles
    s = (b * e - c * d) / denom
    t = (a * e - b * d) / denom
    p1 = line1.origin + d1 * s
    p2 = line2.origin + d2 * t
    if (p1 - p2).length > EPSILON:
        return None  # droites gauches (non coplanaires) : pas d'intersection réelle
    return (p1 + p2) / 2.0


def plane_plane_intersection(plane1: GPlane, plane2: GPlane) -> Optional[tuple[Vector, Vector]]:
    """
    Droite d'intersection de deux plans infinis : direction = n1 × n2, et un
    point sur la droite obtenu par résolution du système des deux équations
    de plan plus une troisième contrainte arbitraire (le point de la droite
    le plus proche de l'origine du repère) — formule standard à trois plans
    (n1·p=d1, n2·p=d2, direction·p=0) via produit triple, vérifiée sur deux
    cas connus (plans XY/XZ -> axe X ; plans z=2/y=3 -> droite (0,3,2) +
    t·(1,0,0)). Retourne None si les deux plans sont parallèles (normales
    colinéaires, y compris confondus).
    """
    n1 = plane1.normal.normalized()
    n2 = plane2.normal.normalized()
    direction = n1.cross(n2)
    if direction.length < EPSILON:
        return None
    d1 = n1.dot(plane1.origin)
    d2 = n2.dot(plane2.origin)
    det = direction.dot(direction)
    p0 = (d1 * n2.cross(direction) + d2 * direction.cross(n1)) / det
    return p0, direction.normalized()


def circle_to_profile(circle: GCircle) -> GProfile:
    """
    Approxime un cercle par un polygone régulier fermé à circle.segments
    sommets, dans la base u/v déterministe de stable_uv_basis (même base que
    Plane). Utilisée à la fois par BlenderAdapter.upsert_circle (affichage du
    fil) et par ExtrudeGNode (un Circle est un profil fermé comme un autre).
    """
    u_axis, v_axis = stable_uv_basis(circle.normal, 0.0)
    n = circle.segments
    vertices = tuple(
        circle.center
        + (u_axis * math.cos(2.0 * math.pi * i / n) + v_axis * math.sin(2.0 * math.pi * i / n)) * circle.radius
        for i in range(n)
    )
    return GProfile(vertices=vertices, closed=True)


def _cubic_bezier_point(p0: Vector, c1: Vector, c2: Vector, p3: Vector, t: float) -> Vector:
    """Point à l'abscisse t ∈ [0, 1] sur la courbe de Bézier cubique (p0, c1, c2, p3)."""
    mt = 1.0 - t
    return p0 * (mt ** 3) + c1 * (3.0 * mt * mt * t) + c2 * (3.0 * mt * t * t) + p3 * (t ** 3)


def bezier_spline_to_profile(points: tuple[Vector, ...], closed: bool, segments: int) -> GProfile:
    """
    Approxime une courbe de Bézier cubique interpolante passant exactement
    par chaque point de `points`, échantillonnée en un GProfile — voir
    nodes/curve.py. Conversion standard Catmull-Rom -> Bézier : la tangente
    en Pi vaut (P[i+1] - P[i-1]) / 2 (extrapolée aux extrémités d'un profil
    ouvert avec le seul voisin existant, donnant une tangente = corde du
    premier/dernier segment), et les points de contrôle Bézier du segment
    [Pi, Pi+1] sont (Pi, Pi + Ti/3, Pi+1 - Ti+1/3, Pi+1) — C1-continue à
    chaque point de contrôle.

    `segments` échantillons par intervalle entre deux points consécutifs
    (résolution, comme circle.segments pour Circle) : t=0 en tête de chaque
    intervalle correspond exactement au point de contrôle Pi, donc la
    courbe passe bien par les points source à ces indices de la liste
    retournée. Le tout dernier point (fin du dernier intervalle) est ajouté
    explicitement pour un profil ouvert ; pour un profil fermé le dernier
    intervalle referme sur le premier point déjà présent, pas de doublon.
    """
    n = len(points)
    tangents = []
    for i in range(n):
        if closed:
            tangents.append((points[(i + 1) % n] - points[(i - 1) % n]) / 2.0)
        elif i == 0:
            tangents.append(points[1] - points[0])
        elif i == n - 1:
            tangents.append(points[n - 1] - points[n - 2])
        else:
            tangents.append((points[i + 1] - points[i - 1]) / 2.0)

    span_count = n if closed else n - 1
    vertices = []
    for i in range(span_count):
        p0 = points[i]
        p3 = points[(i + 1) % n]
        c1 = p0 + tangents[i] / 3.0
        c2 = p3 - tangents[(i + 1) % n] / 3.0
        for k in range(segments):
            t = k / segments
            vertices.append(_cubic_bezier_point(p0, c1, c2, p3, t))
    if not closed:
        vertices.append(points[-1])
    return GProfile(vertices=tuple(vertices), closed=closed)
