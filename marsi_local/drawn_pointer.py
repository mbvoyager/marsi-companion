"""Draw the existing reticle as a small, input-transparent X11 window."""
from __future__ import annotations

from ctypes import (CDLL, CFUNCTYPE, POINTER, Structure, byref, cast, c_char, c_char_p,
                    c_int, c_long, c_uint, c_ulong, c_ushort, c_void_p)
import os

from .electoo import GREEN, RED


class XColor(Structure):
    _fields_ = [("pixel", c_ulong), ("red", c_ushort), ("green", c_ushort),
                ("blue", c_ushort), ("flags", c_char), ("pad", c_char)]


class XWindowAttributes(Structure):
    # XSetWindowAttributes from Xlib.h. The full layout is required on ARM too.
    _fields_ = [("background_pixmap", c_ulong), ("background_pixel", c_ulong),
                ("border_pixmap", c_ulong), ("border_pixel", c_ulong),
                ("bit_gravity", c_int), ("win_gravity", c_int), ("backing_store", c_int),
                ("backing_planes", c_ulong), ("backing_pixel", c_ulong),
                ("save_under", c_int), ("event_mask", c_long),
                ("do_not_propagate_mask", c_long), ("override_redirect", c_int),
                ("colormap", c_ulong), ("cursor", c_ulong)]


def load_xlib():
    x11 = CDLL("libX11.so.6")
    display, xid = c_void_p, c_ulong
    signatures = {
        "XOpenDisplay": (display, [c_char_p]),
        "XCloseDisplay": (c_int, [display]),
        "XDefaultScreen": (c_int, [display]),
        "XRootWindow": (xid, [display, c_int]),
        "XDefaultDepth": (c_int, [display, c_int]),
        "XDefaultColormap": (xid, [display, c_int]),
        "XReadBitmapFile": (c_int, [display, xid, c_char_p, POINTER(c_uint), POINTER(c_uint),
                                   POINTER(xid), POINTER(c_int), POINTER(c_int)]),
        "XAllocNamedColor": (c_int, [display, xid, c_char_p, POINTER(XColor), POINTER(XColor)]),
        "XCreatePixmap": (xid, [display, xid, c_uint, c_uint, c_uint]),
        "XCreateGC": (c_void_p, [display, xid, c_ulong, c_void_p]),
        "XSetForeground": (c_int, [display, c_void_p, c_ulong]),
        "XSetBackground": (c_int, [display, c_void_p, c_ulong]),
        "XCopyPlane": (c_int, [display, xid, xid, c_void_p, c_int, c_int, c_uint, c_uint,
                              c_int, c_int, c_ulong]),
        "XCreateWindow": (xid, [display, xid, c_int, c_int, c_uint, c_uint, c_uint, c_int,
                                c_uint, c_void_p, c_ulong, POINTER(XWindowAttributes)]),
        "XMoveWindow": (c_int, [display, xid, c_int, c_int]),
        "XMapRaised": (c_int, [display, xid]),
        "XUnmapWindow": (c_int, [display, xid]),
        "XFlush": (c_int, [display]),
        "XSync": (c_int, [display, c_int]),
        "XSetErrorHandler": (c_void_p, [c_void_p]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(x11, name)
        function.restype, function.argtypes = result, arguments
    return x11


class DrawnReticle:
    def __init__(self, root, assets):
        self.root = root
        self.x11 = load_xlib()
        shape = CDLL("libXext.so.6")
        shape.XShapeQueryVersion.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
        shape.XShapeQueryVersion.restype = c_int
        shape.XShapeCombineMask.argtypes = [c_void_p, c_ulong, c_int, c_int, c_int, c_ulong, c_int]
        shape.XShapeCombineMask.restype = None
        shape.XShapeCombineRectangles.argtypes = [c_void_p, c_ulong, c_int, c_int, c_int,
                                                  c_void_p, c_int, c_int, c_int]
        shape.XShapeCombineRectangles.restype = None
        self.display = self.x11.XOpenDisplay(os.fsencode(root.winfo_screen()))
        if not self.display:
            raise RuntimeError("could not open the X11 display")
        self.refresh_id = None
        self.visible = False
        errors = []
        error_handler = CFUNCTYPE(c_int, c_void_p, c_void_p)

        @error_handler
        def record_error(display, event):
            if display == self.display:
                errors.append(True)
            elif previous_handler:
                return error_handler(previous_handler)(display, event)
            return 0

        # Xlib's default handler exits the app on a protocol error. Keep this
        # guard local to setup and forward errors for Tk's own connection.
        previous_handler = self.x11.XSetErrorHandler(cast(record_error, c_void_p))
        try:
            major, minor = c_int(), c_int()
            if (not shape.XShapeQueryVersion(self.display, byref(major), byref(minor))
                    or (major.value, minor.value) < (1, 1)):
                raise RuntimeError("X11 Shape 1.1 is required for pointer passthrough")
            screen = self.x11.XDefaultScreen(self.display)
            parent = self.x11.XRootWindow(self.display, screen)
            bitmap, size, self.hotspot = self.read_bitmap(parent, assets / "marsi-reticle.xbm")
            mask, mask_size, _ = self.read_bitmap(parent, assets / "marsi-reticle-mask.xbm")
            if mask_size != size:
                raise RuntimeError("reticle bitmap and mask sizes differ")
            width, height = size
            depth = self.x11.XDefaultDepth(self.display, screen)
            pixmap = self.x11.XCreatePixmap(self.display, parent, width, height, depth)
            gc = self.x11.XCreateGC(self.display, pixmap, 0, None)
            if not gc:
                raise RuntimeError("could not create the reticle graphics context")
            colormap = self.x11.XDefaultColormap(self.display, screen)
            self.x11.XSetForeground(self.display, gc, self.color(colormap, GREEN))
            self.x11.XSetBackground(self.display, gc, self.color(colormap, RED))
            self.x11.XCopyPlane(self.display, bitmap, pixmap, gc, 0, 0, width, height, 0, 0, 1)
            attributes = XWindowAttributes(background_pixmap=pixmap, override_redirect=1)
            cw_back_pixmap, cw_override_redirect = 1 << 0, 1 << 9
            input_output = 1
            self.window = self.x11.XCreateWindow(self.display, parent, 0, 0, width, height,
                                                 0, depth, input_output, None,
                                                 cw_back_pixmap | cw_override_redirect, byref(attributes))
            shape_bounding, shape_input, shape_set, unsorted = 0, 2, 0, 0
            shape.XShapeCombineMask(self.display, self.window, shape_bounding, 0, 0, mask, shape_set)
            shape.XShapeCombineRectangles(self.display, self.window, shape_input, 0, 0,
                                          None, 0, shape_set, unsorted)
            self.x11.XSync(self.display, 0)
            if errors:
                raise RuntimeError("X11 rejected the reticle window")
        except BaseException:
            self.x11.XCloseDisplay(self.display)
            self.display = None
            raise
        finally:
            self.x11.XSetErrorHandler(previous_handler)
        for event in ("<Motion>", "<Enter>", "<Leave>", "<Map>", "<Unmap>"):
            root.bind_all(event, self.queue_refresh, add="+")
        root.bind("<Destroy>", self.close, add="+")
        self.queue_refresh()

    def read_bitmap(self, drawable, path):
        width, height, pixmap = c_uint(), c_uint(), c_ulong()
        x_hot, y_hot = c_int(), c_int()
        result = self.x11.XReadBitmapFile(self.display, drawable, os.fsencode(path),
                                          byref(width), byref(height), byref(pixmap),
                                          byref(x_hot), byref(y_hot))
        if result:
            raise RuntimeError(f"could not load {path.name}")
        return pixmap.value, (width.value, height.value), (x_hot.value, y_hot.value)

    def color(self, colormap, name):
        allocated, exact = XColor(), XColor()
        if not self.x11.XAllocNamedColor(self.display, colormap, name.encode("ascii"),
                                        byref(allocated), byref(exact)):
            raise RuntimeError("could not allocate a reticle color")
        return allocated.pixel

    def queue_refresh(self, event=None):
        if self.display and self.refresh_id is None:
            self.refresh_id = self.root.after_idle(self.refresh)

    def refresh(self):
        self.refresh_id = None
        x, y = self.root.winfo_pointerxy()
        if self.root.winfo_containing(x, y) is None:
            if self.visible:
                self.x11.XUnmapWindow(self.display, self.window)
                self.x11.XFlush(self.display)
                self.visible = False
            return
        self.x11.XMoveWindow(self.display, self.window, x - self.hotspot[0], y - self.hotspot[1])
        self.x11.XMapRaised(self.display, self.window)
        self.x11.XFlush(self.display)
        self.visible = True

    def close(self, event):
        if event.widget is self.root and self.display:
            if self.refresh_id is not None:
                self.root.after_cancel(self.refresh_id)
            # Closing this connection releases its window, pixmaps, GC and colors.
            self.x11.XCloseDisplay(self.display)
            self.display = None
