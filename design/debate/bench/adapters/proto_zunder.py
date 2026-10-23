"""Round-4 hide-policy variant: proto with HIDE_MODE = "z_under_bg" (colour untouched, text under bg)."""
from . import proto as _p

NAME = "proto_zunder"


def resize(source, target_canvas):
    return _p.resize(source, target_canvas, hide_mode="z_under_bg")
