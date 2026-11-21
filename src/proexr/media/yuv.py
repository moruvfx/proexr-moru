"""Planar video frames (YUV 4:2:0) kept as decoded and converted to RGB on the GPU; CPU helpers for probes."""
import numpy as np

# Kr, Kb luma weights per matrix; the GPU shader uses the same numbers.
MATRICES = {"bt601": (0.299, 0.114), "bt709": (0.2126, 0.0722), "bt2020": (0.2627, 0.0593)}
MATRIX_IDS = {"bt601": 0, "bt709": 1, "bt2020": 2}
LAYOUTS = ("rgb", "yuv420p", "nv12")
_AV_COLORSPACE = {1: "bt709", 5: "bt601", 6: "bt601", 9: "bt2020", 10: "bt2020"}


def pick_matrix(av_colorspace: int, height: int) -> str:
    """FFmpeg AVColorSpace value to matrix name; unspecified follows the usual HD/SD convention."""
    return _AV_COLORSPACE.get(av_colorspace, "bt709" if height >= 720 else "bt601")


def planes(pixels: np.ndarray, layout: str) -> list[np.ndarray]:
    """Split the decoder's (h*3/2, w) buffer into Y, then U and V (yuv420p) or interleaved UV (nv12)."""
    height = pixels.shape[0] * 2 // 3
    width = pixels.shape[1]
    luma = pixels[:height]
    chroma = pixels[height:]
    if layout == "yuv420p":
        quarter = chroma.shape[0] // 2
        return [luma, chroma[:quarter].reshape(height // 2, width // 2), chroma[quarter:].reshape(height // 2, width // 2)]
    if layout == "nv12":
        return [luma, chroma.reshape(height // 2, width // 2, 2)]
    raise ValueError(f"Not a planar layout: {layout}")


def to_rgb(pixels: np.ndarray, layout: str, matrix: str, full_range: bool,
           region: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """(h, w, 3) uint8 RGB of the whole frame or of region (x0, y0, x1, y1)."""
    split = planes(pixels, layout)
    height, width = split[0].shape
    x0, y0, x1, y1 = region or (0, 0, width, height)
    luma = split[0][y0:y1, x0:x1].astype(np.float32)
    rows = np.arange(y0, y1) // 2
    cols = np.arange(x0, x1) // 2
    if layout == "yuv420p":
        cb = split[1][rows][:, cols].astype(np.float32)
        cr = split[2][rows][:, cols].astype(np.float32)
    else:
        uv = split[1][rows][:, cols].astype(np.float32)
        cb, cr = uv[..., 0], uv[..., 1]
    if full_range:
        y, cb, cr = luma / 255.0, (cb - 128.0) / 255.0, (cr - 128.0) / 255.0
    else:
        y, cb, cr = (luma - 16.0) / 219.0, (cb - 128.0) / 224.0, (cr - 128.0) / 224.0
    kr, kb = MATRICES[matrix]
    kg = 1.0 - kr - kb
    r = y + 2.0 * (1.0 - kr) * cr
    b = y + 2.0 * (1.0 - kb) * cb
    g = (y - kr * r - kb * b) / kg
    rgb = np.stack([r, g, b], axis=-1)
    return (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
