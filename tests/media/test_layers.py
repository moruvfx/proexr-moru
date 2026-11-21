from proexr.media.layers import group_layers


def test_main_rgba_and_aov_layers_are_grouped():
    layers = group_layers([["A", "B", "G", "R", "diffuse.B", "diffuse.G", "diffuse.R", "Z"]])
    assert [(layer.name, layer.channel_names) for layer in layers] == [
        ("RGBA", ["R", "G", "B", "A"]),
        ("diffuse", ["diffuse.R", "diffuse.G", "diffuse.B"]),
        ("Z", ["Z"]),
    ]
    assert layers[0].channel_indices == [3, 2, 1, 0]


def test_vector_and_single_channel_layers():
    layers = group_layers([["N.X", "N.Y", "N.Z", "mask.alpha", "depth.V"]])
    assert [(layer.name, layer.channel_names) for layer in layers] == [
        ("N", ["N.X", "N.Y", "N.Z"]),
        ("mask.alpha", ["mask.alpha"]),
        ("depth.V", ["depth.V"]),
    ]


def test_multipart_layers_carry_part_index_and_name():
    layers = group_layers([["R", "G", "B"], ["R", "G", "B", "A"]], part_names=["beauty", "spec"])
    assert [(layer.name, layer.part) for layer in layers] == [("beauty", 0), ("spec", 1)]


def test_rgb_without_alpha_is_named_rgb():
    assert group_layers([["R", "G", "B"]])[0].name == "RGB"
