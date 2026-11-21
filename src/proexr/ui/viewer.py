import ctypes
import math
import time
from enum import IntEnum

import numpy as np
from OpenGL import GL
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QSurfaceFormat,
    QWheelEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..color.ocio_pipeline import BakedLut
from ..media.frame import Frame
from ..media.yuv import MATRIX_IDS, planes
from ..playback.stats import RollingStats
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
uniform sampler3D displayLut;
uniform sampler2D imageB;
uniform sampler2D imageU;
uniform sampler2D imageV;
uniform sampler2D imageBU;
uniform sampler2D imageBV;
uniform int layoutA;
uniform int layoutB;
uniform int yuvMatrixA;
uniform int yuvMatrixB;
uniform int yuvFullA;
uniform int yuvFullB;
uniform int channelCountB;
uniform int sourceBIsSrgb;
uniform int compareMode;
uniform int passSource;
uniform float wipeX;
uniform int lutShaper;
uniform float lutMin;
uniform float lutMax;
uniform float lutSize;

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

vec3 applyLut(vec3 v) {
    vec3 s = lutShaper == 1 ? (log2(max(v, vec3(exp2(lutMin)))) - lutMin) / (lutMax - lutMin)
                            : (v - lutMin) / (lutMax - lutMin);
    s = clamp(s, 0.0, 1.0);
    return texture(displayLut, s * ((lutSize - 1.0) / lutSize) + 0.5 / lutSize).rgb;
}

vec3 yuvToRgb(float y, vec2 c, int matrix, int full) {
    vec3 k = matrix == 0 ? vec3(0.299, 0.587, 0.114) : matrix == 1 ? vec3(0.2126, 0.7152, 0.0722)
                                                      : vec3(0.2627, 0.6780, 0.0593);
    float luma = full == 1 ? y : (y * 255.0 - 16.0) / 219.0;
    vec2 chroma = full == 1 ? c - 128.0 / 255.0 : (c * 255.0 - 128.0) / 224.0;
    float r = luma + 2.0 * (1.0 - k.x) * chroma.y;
    float b = luma + 2.0 * (1.0 - k.z) * chroma.x;
    return clamp(vec3(r, (luma - k.x * r - k.z * b) / k.y, b), 0.0, 1.0);
}

// layout: 0 packed RGB(A), 1 planar Y + U + V, 2 Y + interleaved UV (NV12)
vec4 sampleSource(sampler2D luma, sampler2D u, sampler2D v, int kind, int matrix, int full, vec2 p) {
    if (kind == 0) return texture(luma, p);
    vec2 c = kind == 1 ? vec2(texture(u, p).r, texture(v, p).r) : texture(u, p).rg;
    return vec4(yuvToRgb(texture(luma, p).r, c, matrix, full), 1.0);
}
vec4 sampleA(vec2 p) { return sampleSource(image, imageU, imageV, layoutA, yuvMatrixA, yuvFullA, p); }
vec4 sampleB(vec2 p) { return sampleSource(imageB, imageBU, imageBV, layoutB, yuvMatrixB, yuvFullB, p); }

vec4 decode(vec4 texel, int count, int isSrgb) {
    vec4 c = count == 1 ? vec4(texel.rrr, 1.0)
           : count == 2 ? vec4(texel.rg, 0.0, 1.0)
           : count == 3 ? vec4(texel.rgb, 1.0)
           : texel;
    if (isSrgb == 1 && viewTransform != 4) c.rgb = srgbToLinear(c.rgb);
    return c;
}

void main() {
    vec4 c = decode(sampleA(uv), channelCount, sourceIsSrgb);
    bool showB = passSource == 1 || compareMode == 1 || (compareMode == 2 && uv.x >= wipeX);
    if (showB) c = decode(sampleB(uv), channelCountB, sourceBIsSrgb);
    if (compareMode == 4) c = vec4(abs(c.rgb - decode(sampleB(uv), channelCountB, sourceBIsSrgb).rgb), 1.0);

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
    vec3 display = viewTransform == 4 ? v : max(v, 0.0);
    if (viewTransform == 4) display = applyLut(display);
    else if (viewTransform == 1) display = linearToSrgb(display);
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
            "showClipping", "clipOver", "clipUnder", "displayLut", "lutShaper", "lutMin", "lutMax", "lutSize",
            "imageB", "channelCountB", "sourceBIsSrgb", "compareMode", "passSource", "wipeX",
            "imageU", "imageV", "imageBU", "imageBV", "layoutA", "layoutB", "yuvMatrixA", "yuvMatrixB",
            "yuvFullA", "yuvFullB")
# Texture units per source slot: main plane, chroma plane 1, chroma plane 2. Unit 1 holds the display LUT.
PLANE_UNITS = ((0, 3, 4), (2, 5, 6))
LAYOUT_IDS = {"rgb": 0, "yuv420p": 1, "nv12": 2}
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
WIPE_GRAB_PIXELS = 10
DEFAULT_GRADE = {"exposure": 0.0, "gain": 1.0, "offset": 0.0, "contrast": 1.0, "saturation": 1.0,
                 "balance": (1.0, 1.0, 1.0), "gamma": 1.0}


class Channel(IntEnum):
    RGB = 0
    RED = 1
    GREEN = 2
    BLUE = 3
    ALPHA = 4
    LUMINANCE = 5


class CompareMode(IntEnum):
    OFF = 0
    B_ONLY = 1
    WIPE = 2
    SIDE_BY_SIDE = 3
    DIFFERENCE = 4


class ViewTransform(IntEnum):
    RAW = 0
    SRGB = 1
    REC709 = 2
    ACES_FILMIC = 3
    OCIO = 4


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
    displaySampled = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 200)
        self.frame: Frame | None = None
        self.compare_frame: Frame | None = None
        self.compare_mode = CompareMode.OFF
        self.wipe_position = 0.5
        self._is_dragging_wipe = False
        self.grade = dict(DEFAULT_GRADE)
        self.channel = Channel.RGB
        self.view_transform = ViewTransform.SRGB
        self.show_clipping = False
        self.nearest_when_magnified = True
        self.overlays = {"safe_areas": False, "thirds": False, "center": False}
        self.aspect_guide = 0.0
        self.pixel_aspect = 1.0
        self.hint = ""
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.is_fit = True
        self.gl_renderer = ""
        self._textures: list[list[int]] = [[0, 0, 0], [0, 0, 0]]
        self._uploads_pending = [False, False]
        self._texture_signatures: list[tuple | None] = [None, None]
        self._mipmaps_stale = [True, True]
        self._plane_counts = [1, 1]
        self.upload_stats = RollingStats()
        self._drag_origin: tuple[QPointF, QPointF] | None = None
        self._mouse: QPointF | None = None
        self.display_lut: BakedLut | None = None
        self._sample_width = 0
        self._sample_target: tuple[int, int, int, int] | None = None
        self._lut_pending = False
        self._lut_texture = 0

    def show_frame(self, frame: Frame | None) -> None:
        size_changed = frame is None or self.frame is None or \
            (frame.width, frame.height) != (self.frame.width, self.frame.height)
        self.frame = frame
        self._uploads_pending[0] = frame is not None
        if size_changed and self.is_fit:
            self._fit_zoom()
        self.update()
        self._report_pixel()

    def show_compare_frame(self, frame: Frame | None) -> None:
        self.compare_frame = frame
        self._uploads_pending[1] = frame is not None
        self.update()

    @property
    def is_comparing(self) -> bool:
        return self.compare_mode is not CompareMode.OFF and self.compare_frame is not None

    def request_display_sample(self, width: int) -> None:
        self._sample_width = width
        self.update()

    def set_display_lut(self, lut: BakedLut | None) -> None:
        self.display_lut = lut
        self._lut_pending = lut is not None
        self.update()

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
        names = list(GL.glGenTextures(6))
        self._textures = [names[:3], names[3:]]
        self._lut_texture = GL.glGenTextures(1)
        self._lut_pending = self.display_lut is not None
        self._uniforms = {name: GL.glGetUniformLocation(self._program, name) for name in UNIFORMS}
        self._texture_signatures = [None, None]
        self._uploads_pending = [self.frame is not None, self.compare_frame is not None]
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

    def _upload(self, slot: int, frame: Frame) -> None:
        started = time.perf_counter()
        self._upload_planes(slot, frame)
        self.upload_stats.add(time.perf_counter() - started)

    def _upload_planes(self, slot: int, frame: Frame) -> None:
        if frame.is_planar:
            plane_arrays = [p if p.ndim == 3 else p[..., None] for p in planes(frame.pixels, frame.layout)]
        else:
            pixels = frame.pixels if frame.pixels.dtype in TEXTURE_FORMATS else frame.pixels.astype(np.float32)
            plane_arrays = [pixels]
        signature = (frame.width, frame.height, frame.channel_count, plane_arrays[0].dtype, frame.layout)
        reallocate = signature != self._texture_signatures[slot]
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        for index, pixels in enumerate(plane_arrays):
            gl_type, internal_formats = TEXTURE_FORMATS[pixels.dtype]
            height, width, channels = pixels.shape
            GL.glActiveTexture(GL.GL_TEXTURE0 + PLANE_UNITS[slot][index])
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._textures[slot][index])
            if reallocate:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal_formats[channels], width, height, 0,
                                PIXEL_FORMATS[channels], gl_type, pixels)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            else:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height, PIXEL_FORMATS[channels], gl_type, pixels)
        self._texture_signatures[slot] = signature
        self._plane_counts[slot] = len(plane_arrays)
        self._mipmaps_stale[slot] = True
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _upload_lut(self, lut: BakedLut) -> None:
        size = lut.table.shape[0]
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_3D, self._lut_texture)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage3D(GL.GL_TEXTURE_3D, 0, GL.GL_RGB32F, size, size, size, 0, GL.GL_RGB, GL.GL_FLOAT, lut.table)
        for parameter in (GL.GL_TEXTURE_MIN_FILTER, GL.GL_TEXTURE_MAG_FILTER):
            GL.glTexParameteri(GL.GL_TEXTURE_3D, parameter, GL.GL_LINEAR)
        for wrap in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_WRAP_R):
            GL.glTexParameteri(GL.GL_TEXTURE_3D, wrap, GL.GL_CLAMP_TO_EDGE)
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _bind_source(self, slot: int, device_zoom: float) -> None:
        """Binds every plane of a source to its texture unit and sets filtering (mipmaps when zoomed out)."""
        use_mipmaps = device_zoom < MIPMAP_BELOW_ZOOM
        rebuild = use_mipmaps and self._mipmaps_stale[slot]
        minify = GL.GL_LINEAR_MIPMAP_LINEAR if use_mipmaps else GL.GL_LINEAR
        magnify = GL.GL_NEAREST if self.nearest_when_magnified and device_zoom >= NEAREST_FROM_ZOOM else GL.GL_LINEAR
        for index in range(self._plane_counts[slot]):
            GL.glActiveTexture(GL.GL_TEXTURE0 + PLANE_UNITS[slot][index])
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._textures[slot][index])
            if rebuild:
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, minify)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, magnify)
        if rebuild:
            self._mipmaps_stale[slot] = False
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _set_uniforms(self, view_w: int, view_h: int, ratio: float, zoom: float | None = None,
                      pan: QPointF | None = None) -> None:
        u, g = self._uniforms, self.grade
        image_w, image_h = self._display_size()
        pan = self.pan * ratio if pan is None else pan
        GL.glUniform2f(u["imageSize"], image_w, image_h)
        GL.glUniform2f(u["viewSize"], view_w, view_h)
        GL.glUniform2f(u["pan"], pan.x(), pan.y())
        GL.glUniform1f(u["zoom"], self.zoom * ratio if zoom is None else zoom)
        for name, unit in zip(("image", "imageU", "imageV", "imageB", "imageBU", "imageBV"),
                              PLANE_UNITS[0] + PLANE_UNITS[1], strict=True):
            GL.glUniform1i(u[name], unit)
        for slot, suffix in ((0, "A"), (1, "B")):
            source = self.frame if slot == 0 else self.compare_frame
            signature = self._texture_signatures[slot]
            layout = signature[4] if signature and source is not None else "rgb"
            GL.glUniform1i(u["layout" + suffix], LAYOUT_IDS[layout])
            GL.glUniform1i(u["yuvMatrix" + suffix], MATRIX_IDS[source.yuv_matrix] if source is not None else 1)
            GL.glUniform1i(u["yuvFull" + suffix], int(source is not None and source.yuv_full_range))
        GL.glUniform1i(u["channelCount"], self._texture_signatures[0][2])
        compare = self.compare_frame if self.is_comparing and self._texture_signatures[1] else None
        GL.glUniform1i(u["channelCountB"], self._texture_signatures[1][2] if compare else 4)
        GL.glUniform1i(u["sourceBIsSrgb"], int(compare is not None and compare.colorspace == "srgb"))
        mode = self.compare_mode if compare is not None else CompareMode.OFF
        GL.glUniform1i(u["compareMode"], 0 if mode is CompareMode.SIDE_BY_SIDE else int(mode))
        GL.glUniform1f(u["wipeX"], self.wipe_position)
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
        GL.glUniform1i(u["displayLut"], 1)
        lut = self.display_lut
        GL.glUniform1i(u["lutShaper"], int(lut is not None and lut.shaper == "log"))
        GL.glUniform1f(u["lutMin"], lut.domain_min if lut else 0.0)
        GL.glUniform1f(u["lutMax"], lut.domain_max if lut else 1.0)
        GL.glUniform1f(u["lutSize"], float(lut.table.shape[0]) if lut else 1.0)

    def paintGL(self) -> None:
        ratio = self.devicePixelRatioF()
        view_w, view_h = int(self.width() * ratio), int(self.height() * ratio)
        GL.glViewport(0, 0, view_w, view_h)
        GL.glClearColor(*palette.VIEWPORT.getRgbF()[:3], 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self._lut_pending and self.display_lut is not None:
            self._upload_lut(self.display_lut)
            self._lut_pending = False
        for slot, frame in enumerate((self.frame, self.compare_frame)):
            if self._uploads_pending[slot] and frame is not None:
                self._upload(slot, frame)
                self._uploads_pending[slot] = False
        if self.frame is not None and self._texture_signatures[0] is not None:
            GL.glUseProgram(self._program)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_3D, self._lut_texture)
            for slot in (1, 0):
                if self._texture_signatures[slot] is not None:
                    self._bind_source(slot, self.zoom * ratio)
            GL.glBindVertexArray(self._vao)
            if self.is_comparing and self.compare_mode is CompareMode.SIDE_BY_SIDE:
                half = view_w // 2
                for index in (0, 1):
                    GL.glViewport(index * half, 0, half, view_h)
                    self._set_uniforms(half, view_h, ratio)
                    GL.glUniform1i(self._uniforms["passSource"], index)
                    GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                GL.glViewport(0, 0, view_w, view_h)
            else:
                self._set_uniforms(view_w, view_h, ratio)
                GL.glUniform1i(self._uniforms["passSource"], 0)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            if self._sample_width:
                self._emit_display_sample(view_w, view_h)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)
        self._restore_qt_gl_state()
        self._paint_overlays()

    def _restore_qt_gl_state(self) -> None:
        """QPainter shares this GL context and assumes default state: with UNPACK_ALIGNMENT left at 1 its glyph
        cache uploads are skewed and text renders garbled (seen on NVIDIA drivers)."""
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 4)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 4)
        for unit in (GL.GL_TEXTURE0 + i for i in range(6, -1, -1)):
            GL.glActiveTexture(unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glBindTexture(GL.GL_TEXTURE_3D, 0)

    def _sample_framebuffer(self, width: int, height: int) -> int:
        if self._sample_target is not None and self._sample_target[2:] == (width, height):
            return self._sample_target[0]
        if self._sample_target is not None:
            GL.glDeleteFramebuffers(1, [self._sample_target[0]])
            GL.glDeleteTextures([self._sample_target[1]])
        texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        framebuffer = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, texture, 0)
        self._sample_target = (framebuffer, texture, width, height)
        return framebuffer

    def _emit_display_sample(self, view_w: int, view_h: int) -> None:
        image_w, image_h = self._display_size()
        width = self._sample_width
        height = max(1, round(width * image_h / image_w))
        self._sample_width = 0
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._sample_framebuffer(width, height))
        GL.glViewport(0, 0, width, height)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._textures[0][0])  # creating the sample target rebound unit 0
        self._set_uniforms(width, height, 1.0, zoom=width / image_w, pan=QPointF(0, 0))
        GL.glUniform1i(self._uniforms["compareMode"], 0)
        GL.glUniform1i(self._uniforms["passSource"], 0)
        GL.glUniform1i(self._uniforms["showClipping"], 0)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        data = GL.glReadPixels(0, 0, width, height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        GL.glViewport(0, 0, view_w, view_h)
        sample = np.frombuffer(data, np.uint8).reshape(height, width, 3)[::-1].copy()
        self.displaySampled.emit(sample)

    def _paint_overlays(self) -> None:
        painter = QPainter(self)
        if self.frame is not None:
            left, top, right, bottom = self._image_rect()
            width, height = right - left, bottom - top
            if self.aspect_guide > 0:
                self._paint_aspect_guide(painter, left, top, right, bottom)
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
            if self.is_comparing:
                self._paint_compare_marks(painter, left, top, right, bottom)
            if self.frame.is_held:
                painter.setPen(palette.MISSING)
                painter.drawText(12, 22, "Missing frame: holding previous")
        if self.hint:
            painter.setPen(palette.TEXT_MUTED)
            painter.drawText(self.rect(), Qt.AlignCenter, self.hint)
        painter.end()

    def _paint_aspect_guide(self, painter: QPainter, left: float, top: float, right: float, bottom: float) -> None:
        """Dims the image outside a centred frame of the chosen aspect ratio and outlines that frame."""
        width, height = right - left, bottom - top
        image_aspect = width / height if height else 1.0
        if self.aspect_guide >= image_aspect:
            inner_height = width / self.aspect_guide
            inner = QRectF(left, top + (height - inner_height) / 2, width, inner_height)
        else:
            inner_width = height * self.aspect_guide
            inner = QRectF(left + (width - inner_width) / 2, top, inner_width, height)
        outer = QRectF(left, top, width, height)
        painter.fillRect(QRectF(outer.left(), outer.top(), outer.width(), inner.top() - outer.top()), palette.GUIDE_MASK)
        painter.fillRect(QRectF(outer.left(), inner.bottom(), outer.width(), outer.bottom() - inner.bottom()),
                         palette.GUIDE_MASK)
        painter.fillRect(QRectF(outer.left(), inner.top(), inner.left() - outer.left(), inner.height()), palette.GUIDE_MASK)
        painter.fillRect(QRectF(inner.right(), inner.top(), outer.right() - inner.right(), inner.height()),
                         palette.GUIDE_MASK)
        painter.setPen(QPen(palette.GUIDE, 1))
        painter.drawRect(inner)

    def _wipe_x(self) -> float:
        left, _, right, _ = self._image_rect()
        return left + (right - left) * self.wipe_position

    def _paint_compare_marks(self, painter: QPainter, left: float, top: float, right: float, bottom: float) -> None:
        painter.setPen(palette.TEXT)
        if self.compare_mode is CompareMode.WIPE:
            x = int(self._wipe_x())
            painter.setPen(QPen(palette.TEXT, 2))
            painter.drawLine(x, int(top), x, int(bottom))
            painter.setBrush(palette.ACCENT)
            painter.drawEllipse(QPointF(x, (top + bottom) / 2), 7, 7)
            painter.drawText(int(left) + 8, int(top) + 18, "A")
            painter.drawText(int(right) - 16, int(top) + 18, "B")
        elif self.compare_mode is CompareMode.SIDE_BY_SIDE:
            pane = self._pane_width()
            painter.drawText(int(left) + 8, int(top) + 18, "A")
            painter.drawText(int(left + pane) + 8, int(top) + 18, "B")
        else:
            label = "B" if self.compare_mode is CompareMode.B_ONLY else "A - B"
            painter.drawText(int(left) + 8, int(top) + 18, label)

    def _display_size(self) -> tuple[float, float]:
        if self.frame is None:
            return 1.0, 1.0
        return self.frame.width * self.pixel_aspect, float(self.frame.height)

    def _pane_width(self) -> float:
        side_by_side = self.is_comparing and self.compare_mode is CompareMode.SIDE_BY_SIDE
        return self.width() / 2 if side_by_side else float(self.width())

    def _image_rect(self) -> tuple[float, float, float, float]:
        width, height = self._display_size()
        cx, cy = self._pane_width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y()
        half_w, half_h = width * self.zoom / 2, height * self.zoom / 2
        return cx - half_w, cy - half_h, cx + half_w, cy + half_h

    def widget_to_image(self, position: QPointF) -> tuple[float, float] | None:
        if self.frame is None:
            return None
        left, top, right, bottom = self._image_rect()
        position = QPointF(position.x() % self._pane_width(), position.y())
        return ((position.x() - left) / (right - left) * self.frame.width,
                (position.y() - top) / (bottom - top) * self.frame.height)

    def _fit_zoom(self) -> None:
        width, height = self._display_size()
        self.zoom = min(self._pane_width() / width, self.height() / height) * FIT_MARGIN
        self.pan = QPointF(0, 0)
        self.zoomChanged.emit(self.zoom)

    def fit(self) -> None:
        self.is_fit = True
        self._fit_zoom()
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        if anchor is not None:
            local = QPointF(anchor.x() % self._pane_width(), anchor.y())
            offset = local - QPointF(self._pane_width() / 2, self.height() / 2) - self.pan
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
        near_wipe = self.is_comparing and self.compare_mode is CompareMode.WIPE and \
            abs(event.position().x() - self._wipe_x()) <= WIPE_GRAB_PIXELS
        if event.button() == Qt.LeftButton and near_wipe:
            self._is_dragging_wipe = True
            return
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag_origin = (event.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse = event.position()
        if self._is_dragging_wipe:
            left, _, right, _ = self._image_rect()
            self.wipe_position = min(1.0, max(0.0, (event.position().x() - left) / max(1.0, right - left)))
            self.update()
            return
        if self._drag_origin is not None:
            start, pan_at_start = self._drag_origin
            self.pan = pan_at_start + (event.position() - start)
            self.is_fit = False
            self.update()
        self._report_pixel()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        self._is_dragging_wipe = False
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
        raw = self.frame.rgb_region(x, y, x + 1, y + 1)[0, 0].astype(np.float64)
        dtype = np.dtype(np.uint8) if self.frame.is_planar else self.frame.pixels.dtype
        scale = {np.dtype(np.uint8): 255.0, np.dtype(np.uint16): 65535.0}.get(dtype, 1.0)
        self.pixelHovered.emit({"x": x, "y": y, "values": raw / scale, "raw": raw,
                                "is_integer": scale != 1.0})

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
