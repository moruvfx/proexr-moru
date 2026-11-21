from dataclasses import dataclass

COLOR_SETS = (
    ("r", "g", "b", "a"),
    ("red", "green", "blue", "alpha"),
    ("x", "y", "z", None),
)
MAIN_LAYER_NAMES = ("RGBA", "RGB")


@dataclass(frozen=True)
class Layer:
    name: str
    part: int
    channel_indices: list[int]
    channel_names: list[str]

    @property
    def label(self) -> str:
        suffixes = ",".join(n.rpartition(".")[2] for n in self.channel_names)
        return f"{self.name}  ({suffixes})"


def _color_layer(base: str, channels: list[tuple[int, str]]) -> tuple[list[int], bool] | None:
    by_suffix = {suffix.lower(): index for index, suffix in channels}
    for color_set in COLOR_SETS:
        if all(c in by_suffix for c in color_set[:3]):
            indices = [by_suffix[c] for c in color_set if c and c in by_suffix]
            has_alpha = color_set[3] is not None and color_set[3] in by_suffix
            return indices, has_alpha
    return None


def _layers_in_part(part: int, channel_names: list[str], part_name: str | None) -> list[Layer]:
    groups: dict[str, list[tuple[int, str]]] = {}
    for index, full_name in enumerate(channel_names):
        base, _, suffix = full_name.rpartition(".")
        groups.setdefault(base, []).append((index, suffix))
    layers = []
    for base, channels in groups.items():
        used: set[int] = set()
        color = _color_layer(base, channels)
        if color is not None:
            indices, has_alpha = color
            used.update(indices)
            name = base or (part_name or ("RGBA" if has_alpha else "RGB"))
            if part_name and base:
                name = f"{part_name}/{base}"
            layers.append(Layer(name, part, indices, [channel_names[i] for i in indices]))
        for index, suffix in channels:
            if index in used:
                continue
            name = channel_names[index]
            if part_name:
                name = f"{part_name}/{name}"
            layers.append(Layer(name, part, [index], [channel_names[index]]))
    return layers


def group_layers(parts: list[list[str]], part_names: list[str] | None = None) -> list[Layer]:
    layers = []
    for part, channel_names in enumerate(parts):
        part_name = part_names[part] if part_names and len(parts) > 1 else None
        layers.extend(_layers_in_part(part, channel_names, part_name))
    return sorted(layers, key=lambda l: (l.part, l.name not in MAIN_LAYER_NAMES, len(l.channel_indices) == 1))
