"""Install the reticle with a native pointer fallback."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .electoo import GREEN, RED


def install_reticle(root, *, drawn=False):
    """Keep the same centred pointer over the archive, entry and controls."""
    import tkinter as tk
    cursor = "crosshair"  # Portable development fallback for Windows/macOS.
    if root.tk.call("tk", "windowingsystem") == "x11":
        assets = Path(__file__).with_name("assets")
        cursor = ("@" + (assets / "marsi-reticle.xbm").as_posix(),
                  (assets / "marsi-reticle-mask.xbm").as_posix(), GREEN, RED)
        try:
            root.configure(cursor=cursor)
        except tk.TclError:
            logging.getLogger("marsi.local.display").warning("Custom pointer unavailable; using the native crosshair.")
            cursor = ("crosshair", GREEN, RED)
        if drawn and os.getenv("MARSI_CURSOR") != "native" and not os.getenv("WAYLAND_DISPLAY"):
            from .drawn_pointer import DrawnReticle
            try:
                root.drawn_reticle = DrawnReticle(root, assets)
            except (OSError, RuntimeError, AttributeError, tk.TclError) as error:
                logging.getLogger("marsi.local.display").warning("Drawn reticle unavailable (%s); using the native pointer.", error)
            else:
                cursor = "none"
    root.configure(cursor=cursor)
    root.option_add("*Cursor", cursor)

    def apply(widget):
        if "cursor" in widget.keys():
            widget.configure(cursor=cursor)
        for child in widget.winfo_children():
            apply(child)

    apply(root)

    def mapped(event):
        if event.widget is root:
            # At boot the window manager and display may still be mapping the
            # fullscreen window. Reassert the final cursor once mapping settles.
            root.after_idle(lambda: apply(root))

    root.bind("<Map>", mapped, add="+")
    return root.cget("cursor")
