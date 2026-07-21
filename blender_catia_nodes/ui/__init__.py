"""N-panel et opérateurs de l'éditeur CATIA Nodes."""
from . import panel


def register():
    panel.register()


def unregister():
    panel.unregister()
