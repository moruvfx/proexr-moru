"""GPU viewer: all colour work happens in a GLSL fragment shader.

Source pixels are uploaded once per frame as-is (8/16-bit int, half or
float); exposure, gamma, channel isolation and the display transform are
applied on the GPU, so adjustments are real-time and never touch the file.
"""
from __future__ import annotations

import ctypes
import math

import numpy as np
from OpenGL import GL
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

VERT = """
#version 330 core
layout(location = 0) in vec2 pos;
uniform vec2 imgSize;   // image size in pixels (aspect corrected)
uniform vec2 viewSize;  // widget size in device pixels
uniform vec2 pan;       // device pixels
uniform float zoom;
out vec2 uv;
void main() {
    vec2 p = pan + (pos * imgSize - imgSize * 0.5) * zoom + viewSize * 0.5;
    vec2 ndc = p / viewSize * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
    uv = pos;
}
"""

FRAG = """
#version 330 core
in vec2 uv;
out vec4 outColor;
uniform sampler2D img;
uniform int   nch;          // channels in the texture (1..4)
uniform int   inputSRGB;    // 1 = source is display referred (sRGB/video)
uniform float exposure;     // stops
uniform float gain;
uniform float offset;
uniform float contrast;
uniform float saturation;
uniform vec3  balance;
uniform float gamma;
uniform int   channel;      // 0 RGB 1 R 2 G 3 B 4 A 5 luma
uniform int   view;         // 0 raw 1 sRGB 2 Rec.709 3 ACES filmic (approx)
uniform int   showClip;     // highlight values outside 0..1

float srgb_to_lin(float c) { return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4); }
vec3 srgb_to_lin(vec3 c) { return vec3(srgb_to_lin(c.r), srgb_to_lin(c.g), srgb_to_lin(c.b)); }
float lin_to_srgb(float c) { return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0/2.4) - 0.055; }
vec3 lin_to_srgb(vec3 c) { return vec3(lin_to_srgb(c.r), lin_to_srgb(c.g), lin_to_srgb(c.b)); }
float lin_to_709(float c) { return c < 0.018 ? c * 4.5 : 1.099 * pow(c, 0.45) - 0.099; }
vec3 lin_to_709(vec3 c) { return vec3(lin_to_709(c.r), lin_to_709(c.g), lin_to_709(c.b)); }
vec3 aces_fit(vec3 x) { // Narkowicz fit of the ACES RRT+ODT
    x *= 0.6;
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

void main() {
    vec4 t = texture(img, uv);
    vec4 c;
    if (nch == 1) c = vec4(t.rrr, 1.0);
    else if (nch == 2) c = vec4(t.rg, 0.0, 1.0);
    else if (nch == 3) c = vec4(t.rgb, 1.0);
    else c = t;
    if (inputSRGB == 1) c.rgb = srgb_to_lin(c.rgb);

    vec3 v = c.rgb * exp2(exposure) * gain * balance + offset;
    if (contrast != 1.0) v = sign(v) * pow(abs(v) / 0.18, vec3(contrast)) * 0.18;
    float l = dot(v, LUMA);
    v = mix(vec3(l), v, saturation);

    if (channel == 1) v = v.rrr;
    else if (channel == 2) v = v.ggg;
    else if (channel == 3) v = v.bbb;
    else if (channel == 4) v = vec3(c.a);
    else if (channel == 5) v = vec3(dot(v, LUMA));

    bool over = any(greaterThan(v, vec3(1.0)));
    bool under = any(lessThan(v, vec3(0.0)));
    vec3 d;
    if (view == 1) d = lin_to_srgb(max(v, 0.0));
    else if (view == 2) d = lin_to_709(max(v, 0.0));
    else if (view == 3) d = lin_to_srgb(aces_fit(max(v, 0.0)));
    else d = v;
    if (gamma != 1.0) d = pow(max(d, 0.0), vec3(1.0 / gamma));
    if (showClip == 1) {
        if (over) d = vec3(1.0, 0.0, 1.0);
        else if (under) d = vec3(0.0, 0.6, 1.0);
    }
    outColor = vec4(d, 1.0);
}
"""

_GL_FMT = {1: GL.GL_RED, 2: GL.GL_RG, 3: GL.GL_RGB, 4: GL.GL_RGBA}
_GL_TYPE = {
    np.dtype(np.uint8): (GL.GL_UNSIGNED_BYTE, {1: GL.GL_R8, 2: GL.GL_RG8, 3: GL.GL_RGB8, 4: GL.GL_RGBA8}),
    np.dtype(np.uint16): (GL.GL_UNSIGNED_SHORT, {1: GL.GL_R16, 2: GL.GL_RG16, 3: GL.GL_RGB16, 4: GL.GL_RGBA16}),
    np.dtype(np.float16): (GL.GL_HALF_FLOAT, {1: GL.GL_R16F, 2: GL.GL_RG16F, 3: GL.GL_RGB16F, 4: GL.GL_RGBA16F}),
    np.dtype(np.float32): (GL.GL_FLOAT, {1: GL.GL_R32F, 2: GL.GL_RG32F, 3: GL.GL_RGB32F, 4: GL.GL_RGBA32F}),
}

VIEWS = ["Raw (no transform)", "sRGB", "Rec.709", "ACES filmic (approx)"]
CHANNELS = ["RGB", "Red", "Green", "Blue", "Alpha", "Luminance"]


def default_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(1)          # vsync: no tearing during playback
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    return fmt


class Viewer(QOpenGLWidget):
    pixelHovered = Signal(object)    # dict or None
    zoomChanged = Signal(float)
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 200)
        self.frame = None
        self._pending = None
        self._tex = None
        self._tex_sig = None
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.fit_mode = True
        self.pixel_aspect = 1.0
        self.adj = dict(exposure=0.0, gain=1.0, offset=0.0, contrast=1.0,
                        saturation=1.0, balance=(1.0, 1.0, 1.0), gamma=1.0)
        self.channel = 0
        self.view = 1
        self.show_clip = False
        self.nearest_when_zoomed = True
        self.overlays = dict(safe=False, grid=False, center=False)
        self.message = ""
        self._drag = None
        self._mouse = None
        self.bg = QColor(26, 26, 28)

    # ---------------------------------------------------------- frames ---
    def set_frame(self, frame):
        new_size = (self.frame is None or frame is None or
                    (frame.width, frame.height) != (self.frame.width, self.frame.height))
        self.frame = frame
        self._pending = frame
        if new_size and self.fit_mode:
            self._fit()
        self.update()
        self._emit_pixel()

    def set_adjust(self, **kw):
        self.adj.update(kw)
        self.update()
        self._emit_pixel()

    # ---------------------------------------------------------- GL -------
    def initializeGL(self):
        self._prog = self._link(VERT, FRAG)
        quad = np.array([0, 0, 1, 0, 0, 1, 1, 1], dtype=np.float32)
        self._vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._vao)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, ctypes.c_void_p(0))
        GL.glBindVertexArray(0)
        self._tex = GL.glGenTextures(1)
        self._uni = {n: GL.glGetUniformLocation(self._prog, n) for n in (
            "imgSize", "viewSize", "pan", "zoom", "img", "nch", "inputSRGB", "exposure",
            "gain", "offset", "contrast", "saturation", "balance", "gamma", "channel",
            "view", "showClip")}
        self.gl_info = {
            "renderer": GL.glGetString(GL.GL_RENDERER).decode(errors="ignore"),
            "version": GL.glGetString(GL.GL_VERSION).decode(errors="ignore"),
        }

    @staticmethod
    def _link(vs, fs):
        prog = GL.glCreateProgram()
        for src, kind in ((vs, GL.GL_VERTEX_SHADER), (fs, GL.GL_FRAGMENT_SHADER)):
            sh = GL.glCreateShader(kind)
            GL.glShaderSource(sh, src)
            GL.glCompileShader(sh)
            if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(sh).decode())
            GL.glAttachShader(prog, sh)
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
        return prog

    def _upload(self, frame):
        data = frame.data
        if data.dtype not in _GL_TYPE:
            data = data.astype(np.float32)
        gltype, ifmts = _GL_TYPE[data.dtype]
        ch = data.shape[2]
        h, w = data.shape[:2]
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        sig = (w, h, ch, data.dtype)
        if sig != self._tex_sig:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, ifmts[ch], w, h, 0, _GL_FMT[ch], gltype, data)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            self._tex_sig = sig
        else:
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, _GL_FMT[ch], gltype, data)
        self._mips_dirty = True

    def paintGL(self):
        dpr = self.devicePixelRatioF()
        vw, vh = int(self.width() * dpr), int(self.height() * dpr)
        GL.glViewport(0, 0, vw, vh)
        GL.glClearColor(self.bg.redF(), self.bg.greenF(), self.bg.blueF(), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self._pending is not None:
            self._upload(self._pending)
            self._pending = None
        if self.frame is not None and self._tex_sig is not None:
            GL.glUseProgram(self._prog)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            z = self.zoom * dpr
            if z < 0.75:
                if self._mips_dirty:
                    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
                    self._mips_dirty = False
                minf = GL.GL_LINEAR_MIPMAP_LINEAR
            else:
                minf = GL.GL_LINEAR
            magf = GL.GL_NEAREST if (self.nearest_when_zoomed and z >= 2.0) else GL.GL_LINEAR
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, minf)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, magf)
            u = self._uni
            w, h = self._image_size()
            GL.glUniform2f(u["imgSize"], w, h)
            GL.glUniform2f(u["viewSize"], vw, vh)
            GL.glUniform2f(u["pan"], self.pan.x() * dpr, self.pan.y() * dpr)
            GL.glUniform1f(u["zoom"], z)
            GL.glUniform1i(u["img"], 0)
            GL.glUniform1i(u["nch"], self._tex_sig[2])
            GL.glUniform1i(u["inputSRGB"], 1 if self.frame.colorspace == "srgb" else 0)
            a = self.adj
            GL.glUniform1f(u["exposure"], a["exposure"])
            GL.glUniform1f(u["gain"], a["gain"])
            GL.glUniform1f(u["offset"], a["offset"])
            GL.glUniform1f(u["contrast"], a["contrast"])
            GL.glUniform1f(u["saturation"], a["saturation"])
            GL.glUniform3f(u["balance"], *a["balance"])
            GL.glUniform1f(u["gamma"], max(a["gamma"], 1e-3))
            GL.glUniform1i(u["channel"], self.channel)
            GL.glUniform1i(u["view"], self.view)
            GL.glUniform1i(u["showClip"], int(self.show_clip))
            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)
        self._paint_overlays()

    def _paint_overlays(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        if self.frame is not None:
            x0, y0, x1, y1 = self._image_rect()
            if self.overlays.get("safe"):
                for frac, col in ((0.9, QColor(255, 210, 80, 170)), (0.8, QColor(120, 200, 255, 170))):
                    p.setPen(QPen(col, 1, Qt.DashLine))
                    dx, dy = (x1 - x0) * (1 - frac) / 2, (y1 - y0) * (1 - frac) / 2
                    p.drawRect(int(x0 + dx), int(y0 + dy), int(x1 - x0 - 2 * dx), int(y1 - y0 - 2 * dy))
            if self.overlays.get("grid"):
                p.setPen(QPen(QColor(255, 255, 255, 60), 1))
                for i in (1, 2):
                    x = x0 + (x1 - x0) * i / 3
                    y = y0 + (y1 - y0) * i / 3
                    p.drawLine(int(x), int(y0), int(x), int(y1))
                    p.drawLine(int(x0), int(y), int(x1), int(y))
            if self.overlays.get("center"):
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                p.setPen(QPen(QColor(255, 255, 255, 140), 1))
                p.drawLine(int(cx - 12), int(cy), int(cx + 12), int(cy))
                p.drawLine(int(cx), int(cy - 12), int(cx), int(cy + 12))
            if self.frame.held:
                p.setPen(QColor(255, 120, 80))
                p.drawText(12, 22, "MISSING FRAME (holding previous)")
        if self.message:
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
        p.end()

    # ------------------------------------------------------- geometry ---
    def _image_size(self):
        if self.frame is None:
            return 1.0, 1.0
        return self.frame.width * self.pixel_aspect, float(self.frame.height)

    def _image_rect(self):
        w, h = self._image_size()
        cx = self.width() / 2 + self.pan.x()
        cy = self.height() / 2 + self.pan.y()
        return (cx - w * self.zoom / 2, cy - h * self.zoom / 2,
                cx + w * self.zoom / 2, cy + h * self.zoom / 2)

    def widget_to_image(self, pos):
        x0, y0, x1, y1 = self._image_rect()
        if self.frame is None or x1 == x0:
            return None
        ix = (pos.x() - x0) / (x1 - x0) * self.frame.width
        iy = (pos.y() - y0) / (y1 - y0) * self.frame.height
        return ix, iy

    def _fit(self):
        w, h = self._image_size()
        if w <= 0 or h <= 0:
            return
        self.zoom = min(self.width() / w, self.height() / h) * 0.98
        self.pan = QPointF(0, 0)
        self.zoomChanged.emit(self.zoom)

    def fit(self):
        self.fit_mode = True
        self._fit()
        self.update()

    def set_zoom(self, z, anchor=None):
        z = max(0.01, min(z, 256.0))
        if anchor is not None:
            # keep the image point under the cursor fixed
            c = QPointF(self.width() / 2, self.height() / 2)
            rel = anchor - c - self.pan
            self.pan = self.pan + rel - rel * (z / self.zoom)
        self.zoom = z
        self.fit_mode = False
        self.zoomChanged.emit(z)
        self.update()

    def actual_pixels(self):
        self.set_zoom(1.0 / self.devicePixelRatioF())
        self.pan = QPointF(0, 0)
        self.update()

    def resizeGL(self, w, h):
        if self.fit_mode:
            self._fit()

    # ------------------------------------------------------- input -----
    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom * (1.2 ** steps), e.position())

    def mousePressEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag = (e.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        self._mouse = e.position()
        if self._drag is not None:
            start, pan0 = self._drag
            self.pan = pan0 + (e.position() - start)
            self.fit_mode = False
            self.update()
        self._emit_pixel()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e):
        if self.fit_mode:
            self.actual_pixels()
        else:
            self.fit()

    def leaveEvent(self, e):
        self._mouse = None
        self.pixelHovered.emit(None)

    def _emit_pixel(self):
        if self._mouse is None or self.frame is None:
            return
        pt = self.widget_to_image(self._mouse)
        if pt is None:
            return
        x, y = int(math.floor(pt[0])), int(math.floor(pt[1]))
        f = self.frame
        if 0 <= x < f.width and 0 <= y < f.height:
            px = f.data[y, x].astype(np.float64)
            if f.data.dtype == np.uint8:
                norm = px / 255.0
            elif f.data.dtype == np.uint16:
                norm = px / 65535.0
            else:
                norm = px
            self.pixelHovered.emit({"x": x, "y": y, "raw": px, "value": norm,
                                    "dtype": str(f.data.dtype)})
        else:
            self.pixelHovered.emit(None)

    # drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
