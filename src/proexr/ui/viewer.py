import ctypes
import math
from enum import IntEnum

import numpy as np
from OpenGL import GL
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent, QPainter, QPen, QSurfaceFormat, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..media.frame import Frame
from . import palette

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 corner;
uniform vec2 imageSize;
uniform vec2 viewSize;
uniform vec2 pan;
uniform float zoom;
out vec2 uv;
void main() {
    vec2 p = pan + (corner * imageSize - imageSize * 0.5) * zoom + viewSize * 0.5;
    vec2 ndc = p / viewSize * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
    uv = corner;
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec2 uv;
out vec4 color;
uniform sampler2D image;
uniform int channelCount;
uniform int sourceIsSrgb;
uniform float exposure;
uniform float gain;
uniform float offset;
uniform float contrast;
uniform float saturation;
uniform vec3 balance;
uniform float gamma;
uniform int channel;
uniform int viewTransform;
uniform int showClipping;
uniform vec3 clipOver;
uniform vec3 clipUnder;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

vec3 srgbToLinear(vec3 c) {
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}
vec3 linearToSrgb(vec3 c) {
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c));
}
vec3 linearToRec709(vec3 c) {
    return mix(c * 4.5, 1.099 * pow(c, vec3(0.45)) - 0.099, step(vec3(0.018), c));
}
vec3 acesFilmic(vec3 x) {
    x *= 0.6;
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
    vec4 texel = texture(image, uv);
    vec4 c = channelCount == 1 ? vec4(texel.rrr, 1.0)
           : channelCount == 2 ? vec4(texel.rg, 0.0, 1.0)
           : channelCount == 3 ? vec4(texel.rgb, 1.0)
           : texel;
    if (sourceIsSrgb == 1) c.rgb = srgbToLinear(c.rgb);

    vec3 v = c.rgb * exp2(exposure) * gain * balance + offset;
    if (contrast != 1.0) v = sign(v) * pow(abs(v) / 0.18, vec3(contrast)) * 0.18;
    v = mix(vec3(dot(v, LUMA)), v, saturation);

    if (channel == 1) v = v.rrr;
    else if (channel == 2) v = v.ggg;
    else if (channel == 3) v = v.bbb;
    else if (channel == 4) v = vec3(c.a);
    else if (channel == 5) v = vec3(dot(v, LUMA));

    bool over = any(greaterThan(v, vec3(1.0)));
    bool under = any(lessThan(v, vec3(0.0)));
    vec3 display = max(v, 0.0);
    if (viewTransform == 1) display = linearToSrgb(display);
    else if (viewTransform == 2) display = linearToRec709(display);
    else if (viewTransform == 3) display = linearToSrgb(acesFilmic(display));
    if (gamma != 1.0) display = pow(display, vec3(1.0 / gamma));
    if (showClipping == 1 && over) display = clipOver;
    if (showClipping == 1 && under) display = clipUnder;
    color = vec4(display, 1.0);
}
"""

UNIFORMS = ("imageSize", "viewSize", "pan", "zoom", "image", "channelCount", "sourceIsSrgb", "exposure",
            "gain", "offset", "contrast", "saturation", "balance", "gamma", "channel", "viewTransform",
            "showClipping", "clipOver", "clipUnder")
PIXEL_FORMATS = {1: GL.GL_RED, 2: GL.GL_RG, 3: GL.GL_RGB, 4: GL.GL_RGBA}
TEXTURE_FORMATS = {
    np.dtype(np.uint8): (GL.GL_UNSIGNED_BYTE, {1: GL.GL_R8, 2: GL.GL_RG8, 3: GL.GL_RGB8, 4: GL.GL_RGBA8}),
    np.dtype(np.uint16): (GL.GL_UNSIGNED_SHORT, {1: GL.GL_R16, 2: GL.GL_RG16, 3: GL.GL_RGB16, 4: GL.GL_RGBA16}),
    np.dtype(np.float16): (GL.GL_HALF_FLOAT, {1: GL.GL_R16F, 2: GL.GL_RG16F, 3: GL.GL_RGB16F, 4: GL.GL_RGBA16F}),
    np.dtype(np.float32): (GL.GL_FLOAT, {1: GL.GL_R32F, 2: GL.GL_RG32F, 3: GL.GL_RGB32F, 4: GL.GL_RGBA32F}),
}
FIT_MARGIN = 0.98
MIN_ZOOM, MAX_ZOOM = 0.01, 256.0
WHEEL_ZOOM_STEP = 1.2
MIPMAP_BELOW_ZOOM = 0.75
NEAREST_FROM_ZOOM = 2.0
DEFAULT_GRADE = {"exposure": 0.0, "gain": 1.0, "offset": 0.0, "contrast": 1.0, "saturation": 1.0,
                 "balance": (1.0, 1.0, 1.0), "gamma": 1.0}


class Channel(IntEnum):
    RGB = 0
    RED = 1
    GREEN = 2
    BLUE = 3
    ALPHA = 4
    LUMINANCE = 5


class ViewTransform(IntEnum):
    RAW = 0
    SRGB = 1
    REC709 = 2
    ACES_FILMIC = 3


def surface_format() -> QSurfaceFormat:
    """OpenGL 3.3 core, double buffered with vsync. Set as default before QApplication exists."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    fmt.setSwapInterval(1)
    return fmt


class Viewer(QOpenGLWidget):
    pixelHovered = Signal(object)
    zoomChanged = Signal(float)
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 200)
        self.frame: Frame | None = None
        self.grade = dict(DEFAULT_GRADE)
        self.channel = Channel.RGB
        self.view_transform = ViewTransform.SRGB
        self.show_clipping = False
        self.nearest_when_magnified = True
        self.overlays = {"safe_areas": False, "thirds": False, "center": False}
        self.pixel_aspect = 1.0
        self.hint = ""
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.is_fit = True
        self.gl_renderer = ""
        self._upload_pending = False
        self._texture_signature: tuple | None = None
        self._mipmaps_stale = True
        self._drag_origin: tuple[QPointF, QPointF] | None = None
        self._mouse: QPointF | None = None

    def show_frame(self, frame: Frame | None) -> None:
        size_changed = frame is None or self.frame is None or \
            (frame.width, frame.height) != (self.frame.width, self.frame.height)
        self.frame = frame
        self._upload_pending = frame is not None
        if size_changed and self.is_fit:
            self._fit_zoom()
        self.update()
        self._report_pixel()

    def set_grade(self, **values: float | tuple[float, float, float]) -> None:
        self.grade.update(values)
        self.update()

    def initializeGL(self) -> None:
        self._program = self._link_program()
        corners = np.array([0, 0, 1, 0, 0, 1, 1, 1], np.float32)
        self._vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._vao)
        self._vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, corners.nbytes, corners, GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, ctypes.c_void_p(0))
        GL.glBindVertexArray(0)
        self._texture = GL.glGenTextures(1)
        self._uniforms = {name: GL.glGetUniformLocation(self._program, name) for name in UNIFORMS}
        self._texture_signature = None
        self._upload_pending = self.frame is not None
        self.gl_renderer = GL.glGetString(GL.GL_RENDERER).decode(errors="replace")

    @staticmethod
    def _link_program() -> int:
        program = GL.glCreateProgram()
        for source, kind in ((VERTEX_SHADER, GL.GL_VERTEX_SHADER), (FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER)):
            shader = GL.glCreateShader(kind)
            GL.glShaderSource(shader, source)
            GL.glCompileShader(shader)
            if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(shader).decode())
            GL.glAttachShader(program, shader)
        GL.glLinkProgram(program)
        if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(program).decode())
        return program

    def _upload(self, frame: Frame) -> None:
        pixels = frame.pixels if frame.pixels.dtype in TEXTURE_FORMATS else frame.pixels.astype(np.float32)
        gl_type, internal_formats = TEXTURE_FORMATS[pixels.dtype]
        height, width, channels = pixels.shape
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        signature = (width, height, channels, pixels.dtype)
        if signature != self._texture_signature:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal_formats[channels], width, height, 0,
                            PIXEL_FORMATS[channels], gl_type, pixels)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            self._texture_signature = signature
        else:
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height, PIXEL_FORMATS[channels], gl_type, pixels)
        self._mipmaps_stale = True

    def _set_filtering(self, device_zoom: float) -> None:
        minify = GL.GL_LINEAR
        if device_zoom < MIPMAP_BELOW_ZOOM:
            if self._mipmaps_stale:
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
                self._mipmaps_stale = False
            minify = GL.GL_LINEAR_MIPMAP_LINEAR
        magnify = GL.GL_NEAREST if self.nearest_when_magnified and device_zoom >= NEAREST_FROM_ZOOM else GL.GL_LINEAR
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, minify)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, magnify)

    def _set_uniforms(self, view_w: int, view_h: int, ratio: float) -> None:
        u, g = self._uniforms, self.grade
        image_w, image_h = self._display_size()
        GL.glUniform2f(u["imageSize"], image_w, image_h)
        GL.glUniform2f(u["viewSize"], view_w, view_h)
        GL.glUniform2f(u["pan"], self.pan.x() * ratio, self.pan.y() * ratio)
        GL.glUniform1f(u["zoom"], self.zoom * ratio)
        GL.glUniform1i(u["image"], 0)
        GL.glUniform1i(u["channelCount"], self._texture_signature[2])
        GL.glUniform1i(u["sourceIsSrgb"], int(self.frame.colorspace == "srgb"))
        GL.glUniform1f(u["exposure"], g["exposure"])
        GL.glUniform1f(u["gain"], g["gain"])
        GL.glUniform1f(u["offset"], g["offset"])
        GL.glUniform1f(u["contrast"], g["contrast"])
        GL.glUniform1f(u["saturation"], g["saturation"])
        GL.glUniform3f(u["balance"], *g["balance"])
        GL.glUniform1f(u["gamma"], max(g["gamma"], 1e-3))
        GL.glUniform1i(u["channel"], int(self.channel))
        GL.glUniform1i(u["viewTransform"], int(self.view_transform))
        GL.glUniform1i(u["showClipping"], int(self.show_clipping))
        GL.glUniform3f(u["clipOver"], *palette.CLIP_OVER.getRgbF()[:3])
        GL.glUniform3f(u["clipUnder"], *palette.CLIP_UNDER.getRgbF()[:3])

    def paintGL(self) -> None:
        ratio = self.devicePixelRatioF()
        view_w, view_h = int(self.width() * ratio), int(self.height() * ratio)
        GL.glViewport(0, 0, view_w, view_h)
        GL.glClearColor(*palette.VIEWPORT.getRgbF()[:3], 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self._upload_pending and self.frame is not None:
            self._upload(self.frame)
            self._upload_pending = False
        if self.frame is not None and self._texture_signature is not None:
            GL.glUseProgram(self._program)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
            self._set_filtering(self.zoom * ratio)
            self._set_uniforms(view_w, view_h, ratio)
            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)
        self._paint_overlays()

    def _paint_overlays(self) -> None:
        painter = QPainter(self)
        if self.frame is not None:
            left, top, right, bottom = self._image_rect()
            width, height = right - left, bottom - top
            if self.overlays["safe_areas"]:
                for fraction, color in ((0.9, palette.SAFE_ACTION), (0.8, palette.SAFE_TITLE)):
                    painter.setPen(QPen(color, 1, Qt.DashLine))
                    inset_x, inset_y = width * (1 - fraction) / 2, height * (1 - fraction) / 2
                    painter.drawRect(int(left + inset_x), int(top + inset_y),
                                     int(width - 2 * inset_x), int(height - 2 * inset_y))
            if self.overlays["thirds"]:
                painter.setPen(QPen(palette.GUIDE, 1))
                for i in (1, 2):
                    x, y = left + width * i / 3, top + height * i / 3
                    painter.drawLine(int(x), int(top), int(x), int(bottom))
                    painter.drawLine(int(left), int(y), int(right), int(y))
            if self.overlays["center"]:
                cx, cy = int((left + right) / 2), int((top + bottom) / 2)
                painter.setPen(QPen(palette.GUIDE, 1))
                painter.drawLine(cx - 12, cy, cx + 12, cy)
                painter.drawLine(cx, cy - 12, cx, cy + 12)
            if self.frame.is_held:
                painter.setPen(palette.MISSING)
                painter.drawText(12, 22, "Missing frame: holding previous")
        if self.hint:
            painter.setPen(palette.TEXT_MUTED)
            painter.drawText(self.rect(), Qt.AlignCenter, self.hint)
        painter.end()

    def _display_size(self) -> tuple[float, float]:
        if self.frame is None:
            return 1.0, 1.0
        return self.frame.width * self.pixel_aspect, float(self.frame.height)

    def _image_rect(self) -> tuple[float, float, float, float]:
        width, height = self._display_size()
        cx, cy = self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y()
        half_w, half_h = width * self.zoom / 2, height * self.zoom / 2
        return cx - half_w, cy - half_h, cx + half_w, cy + half_h

    def widget_to_image(self, position: QPointF) -> tuple[float, float] | None:
        if self.frame is None:
            return None
        left, top, right, bottom = self._image_rect()
        return ((position.x() - left) / (right - left) * self.frame.width,
                (position.y() - top) / (bottom - top) * self.frame.height)

    def _fit_zoom(self) -> None:
        width, height = self._display_size()
        self.zoom = min(self.width() / width, self.height() / height) * FIT_MARGIN
        self.pan = QPointF(0, 0)
        self.zoomChanged.emit(self.zoom)

    def fit(self) -> None:
        self.is_fit = True
        self._fit_zoom()
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        if anchor is not None:
            offset = anchor - QPointF(self.width() / 2, self.height() / 2) - self.pan
            self.pan = self.pan + offset - offset * (zoom / self.zoom)
        self.zoom = zoom
        self.is_fit = False
        self.zoomChanged.emit(zoom)
        self.update()

    def show_actual_pixels(self) -> None:
        self.pan = QPointF(0, 0)
        self.set_zoom(1.0 / self.devicePixelRatioF())

    def resizeGL(self, width: int, height: int) -> None:
        if self.is_fit:
            self._fit_zoom()

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom * WHEEL_ZOOM_STEP ** steps, event.position())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag_origin = (event.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse = event.position()
        if self._drag_origin is not None:
            start, pan_at_start = self._drag_origin
            self.pan = pan_at_start + (event.position() - start)
            self.is_fit = False
            self.update()
        self._report_pixel()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.is_fit:
            self.show_actual_pixels()
        else:
            self.fit()

    def leaveEvent(self, event) -> None:
        self._mouse = None
        self.pixelHovered.emit(None)

    def _report_pixel(self) -> None:
        if self._mouse is None or self.frame is None:
            return
        x, y = (math.floor(v) for v in self.widget_to_image(self._mouse))
        if not (0 <= x < self.frame.width and 0 <= y < self.frame.height):
            self.pixelHovered.emit(None)
            return
        raw = self.frame.pixels[y, x].astype(np.float64)
        scale = {np.dtype(np.uint8): 255.0, np.dtype(np.uint16): 65535.0}.get(self.frame.pixels.dtype, 1.0)
        self.pixelHovered.emit({"x": x, "y": y, "values": raw / scale, "raw": raw,
                                "is_integer": scale != 1.0})

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
