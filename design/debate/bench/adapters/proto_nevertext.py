"""Round-4 hide-policy variant: proto with HIDE_MODE = "never_text" (text is never omitted)."""
from . import proto as _p

NAME = "proto_nevertext"


def resize(source, target_canvas):
    return _p.resize(source, target_canvas, hide_mode="never_text")
