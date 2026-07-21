CATIA Nodes — addon Blender
============================

Addon Blender qui ajoute un système de nœuds entièrement custom (pas
Geometry Nodes) dans l'éditeur de nœuds natif de Blender, pour construire de
la géométrie paramétrique façon CATIA : Point, Line, Plane, Circle,
Polyline, Curve, Projection, Intersection, Parallel Curve, Join, Extrude,
plus des nœuds utilitaires (Float, Integer, Boolean, String, Operations).

Chaque nœud recalcule sa géométrie en algèbre vectorielle fermée (jamais en
relisant un objet Blender) et matérialise le résultat via bmesh — jamais
bpy.ops, pour rester réactif en interactif (slider = recalcul immédiat).


Prérequis
---------
- Blender 4.2 ou supérieur (testé sur Blender 5.2 LTS).


Installation
------------
1. Depuis Blender : Edit > Preferences > Get Extensions (ou Add-ons selon la
   version) > Install from Disk, sélectionner le dossier blender_catia_nodes/
   (ou un .zip de ce dossier).
2. Activer l'addon "CATIA Nodes".
3. Dans un éditeur de nœuds, créer un nouveau node tree de type "CATIA
   Nodes" (au lieu de "Shader"/"Geometry Nodes"/...).

Pour développer en local : lier blender_catia_nodes/ par un lien
symbolique/junction vers le dossier extensions de Blender, pour que Blender
lise toujours la source en direct (recharger le .blend suffit après une
modification, pas besoin de réinstaller).


Nœuds disponibles
------------------

Wireframe (construction géométrique) :
  Point           coordonnées / sur courbe / sur plan / intersection / projection
  Line            deux points / point + direction / tangente en un point
  Plane           trois points / point + normale / décalage parallèle / ligne + angle
  Circle          centre + rayon / centre + point / trois points
  Polyline        segments droits à travers des points connectés (fermable)
  Curve           courbe de Bézier interpolante à travers des points connectés
                  (fermable, résolution réglable)
  Projection      projette un point, une courbe ou un profil sur une surface
  Intersection    intersection plan/plan, ligne/plan ou ligne/ligne
  Parallel Curve  décale une ligne d'une distance, dans le plan d'une surface

Entrées directes du menu Add :
  Join            assemble plusieurs courbes bout à bout en un profil
  Extrude         extrude un profil (Line/Circle/Join/Polyline/Curve) en solide ou ruban

Parameters :
  Float, Integer, Boolean, String   constantes, sans entrée

Math :
  Operations      addition/soustraction/multiplication/division/min/max/
                   puissance/modulo/valeur absolue/racine carrée/opposé


Architecture (résumé)
----------------------
  core/engine.py           moteur DAG générique (nœuds, sockets, cache)
  core/geometry.py         géométrie analytique pure (dataclasses + maths)
  blender_adapter/         sockets bpy custom + matérialisation bmesh
  nodes/                   un fichier par nœud (logique + pont bpy)
  ui/panel.py               panneau latéral + bouton "Réévaluer tout"

Détails complets, conventions établies et pièges déjà rencontrés : voir
CLAUDE.md à la racine du projet.


Tests
-----
  tests/blender_test.py     harnais de référence, exécuté par un vrai
                             Blender headless :
                             blender.exe --background --factory-startup --python tests/blender_test.py
  tests/test_nodes.py
  tests/test_geometry.py    tests Python purs (sans Blender), partiels

Voir CLAUDE.md pour le détail de ce que chaque harnais couvre.


Documentation
--------------
  versions.txt          changelog complet (format X.Y.Z), dernière version
                         documentée : 0.17.0
  documentation.html     doc utilisateur en une page, avec une visualisation
                         fidèle de chaque nœud tel qu'il apparaît dans Blender
  CLAUDE.md              architecture détaillée, conventions, pièges connus


Licence
-------
GPL-3.0-or-later (voir blender_catia_nodes/blender_manifest.toml).
