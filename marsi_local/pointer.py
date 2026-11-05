"""Native two-colour X11 reticle; no animation, polling or input interception."""
from __future__ import annotations

import logging
from pathlib import Path

from .electoo import GREEN, RED


def install_reticle(root):
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
