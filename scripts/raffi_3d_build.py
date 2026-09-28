#!/usr/bin/env python3
"""Build the canonical lightweight Rafii live-avatar GLB and optional preview.

Run:
  blender --background --python scripts/raffi_3d_build.py -- \
    --output web/public/raffi/raffi-live-v1.glb \
    --preview-dir /tmp/rafii-3d-preview
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview-dir")
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        # Materials are recreated below. Remove only truly unused data blocks.
        for block in list(datablocks):
            if getattr(block, "users", 0) == 0:
                datablocks.remove(block)


def material(name: str, color: tuple[float, float, float, float], roughness: float = 0.82):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Specular IOR Level"].default_value = 0.28
    return mat


def smooth(obj: bpy.types.Object) -> None:
    if not getattr(obj, "data", None) or not hasattr(obj.data, "polygons"):
        return
    for poly in obj.data.polygons:
        poly.use_smooth = True


def parent_keep_world(obj: bpy.types.Object, parent: bpy.types.Object) -> None:
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = matrix


def uv_sphere(
    name: str,
    loc: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    *,
    segments: int = 28,
    rings: int = 16,
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments,
        ring_count=rings,
        location=loc,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    smooth(obj)
    if parent:
        parent_keep_world(obj, parent)
    return obj


def cone(
    name: str,
    loc: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    *,
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.48, radius2=0.06, depth=0.9, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    smooth(obj)
    if parent:
        parent_keep_world(obj, parent)
    return obj


def torus(
    name: str,
    loc: tuple[float, float, float],
    major_radius: float,
    minor_radius: float,
    scale: tuple[float, float, float],
    mat,
    *,
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(
        major_radius=major_radius,
        minor_radius=minor_radius,
        major_segments=40,
        minor_segments=12,
        location=loc,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    smooth(obj)
    if parent:
        parent_keep_world(obj, parent)
    return obj


def mouth_mesh(parent: bpy.types.Object, mat) -> bpy.types.Object:
    # A small filled oval on the front plane. Shape keys are intentionally
    # simple and stable: the web runtime blends these names by contract.
    cx, cy, cz = 0.0, -1.075, 2.49
    rx, rz = 0.28, 0.105
    count = 20
    verts = [
        (cx + math.cos(2 * math.pi * i / count) * rx, cy, cz + math.sin(2 * math.pi * i / count) * rz)
        for i in range(count)
    ]
    faces = [tuple(range(count))]
    mesh = bpy.data.meshes.new("RafiiMouthMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Mouth", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    parent_keep_world(obj, parent)

    basis = obj.shape_key_add(name="Basis")
    open_key = obj.shape_key_add(name="Open")
    wide_key = obj.shape_key_add(name="Wide")
    round_key = obj.shape_key_add(name="Round")
    smile_key = obj.shape_key_add(name="Smile")

    for i, point in enumerate(basis.data):
        x, y, z = point.co
        dx = x - cx
        dz = z - cz

        open_key.data[i].co = (cx + dx * 0.88, y - 0.018, cz + dz * 1.85)
        wide_key.data[i].co = (cx + dx * 1.35, y - 0.008, cz + dz * 0.72)
        round_key.data[i].co = (cx + dx * 0.72, y - 0.012, cz + dz * 1.35)

        smile_lift = max(0.0, abs(dx) / rx - 0.42) * 0.12
        smile_key.data[i].co = (cx + dx * 1.12, y - 0.006, cz + dz * 0.82 + smile_lift)

    return obj


def build_character():
    fur = material("Rafii Fur", (0.42, 0.37, 0.35, 1.0))
    fur_light = material("Rafii Light Fur", (0.84, 0.79, 0.74, 1.0))
    mask = material("Rafii Mask", (0.19, 0.17, 0.17, 1.0))
    hoodie = material("Rafii Hoodie", (0.86, 0.83, 0.78, 1.0))
    hoodie_shadow = material("Rafii Hoodie Shadow", (0.72, 0.69, 0.65, 1.0))
    white = material("Eye White", (0.96, 0.94, 0.90, 1.0), 0.58)
    black = material("Eye Black", (0.045, 0.038, 0.035, 1.0), 0.5)
    glint = material("Eye Glint", (1.0, 0.99, 0.95, 1.0), 0.35)

    root = bpy.data.objects.new("RafiiRoot", None)
    bpy.context.collection.objects.link(root)

    # Tiny hoodie/body under an intentionally oversized head.
    body = uv_sphere("Body", (0, 0.04, 1.38), (0.90, 0.62, 0.86), hoodie, parent=root)
    belly = uv_sphere("BellyFur", (0, -0.49, 1.15), (0.48, 0.12, 0.42), fur_light, parent=root)

    hood = torus("Hood", (0, -0.01, 2.00), 0.69, 0.14, (1.0, 0.84, 0.72), hoodie_shadow, parent=root)
    # Front hood panel softens the torus opening and keeps the silhouette plush.
    uv_sphere("HoodFront", (0, -0.45, 1.91), (0.72, 0.20, 0.30), hoodie, parent=root)

    head = uv_sphere("Head", (0, -0.01, 2.91), (1.36, 0.86, 1.12), fur, segments=36, rings=20, parent=root)

    # Ears, including smaller inner ears.
    ear_l = cone("EarL", (-0.87, -0.02, 3.84), (0.82, 0.66, 0.96), fur, parent=root)
    ear_r = cone("EarR", (0.87, -0.02, 3.84), (0.82, 0.66, 0.96), fur, parent=root)
    cone("InnerEarL", (-0.87, -0.34, 3.80), (0.48, 0.23, 0.62), mask, parent=root)
    cone("InnerEarR", (0.87, -0.34, 3.80), (0.48, 0.23, 0.62), mask, parent=root)

    # Pale forehead blaze behind the mask.
    forehead = uv_sphere("ForeheadBlaze", (0, -0.74, 3.24), (0.70, 0.10, 0.64), fur_light, parent=root)
    forehead.rotation_euler.y = 0.02

    # Raccoon mask: broad soft ellipses, slightly rotated.
    mask_l = uv_sphere("MaskL", (-0.48, -0.80, 3.03), (0.62, 0.105, 0.42), mask, parent=root)
    mask_r = uv_sphere("MaskR", (0.48, -0.80, 3.03), (0.62, 0.105, 0.42), mask, parent=root)
    mask_l.rotation_euler.y = -0.14
    mask_r.rotation_euler.y = 0.14

    # Named eye nodes are the white eyeballs; pupils and catchlights are children.
    eye_l = uv_sphere("EyeL", (-0.43, -0.91, 3.10), (0.29, 0.12, 0.34), white, parent=root)
    eye_r = uv_sphere("EyeR", (0.43, -0.91, 3.10), (0.29, 0.12, 0.34), white, parent=root)
    pupil_l = uv_sphere("PupilL", (-0.43, -1.012, 3.085), (0.17, 0.07, 0.22), black, parent=eye_l)
    pupil_r = uv_sphere("PupilR", (0.43, -1.012, 3.085), (0.17, 0.07, 0.22), black, parent=eye_r)
    uv_sphere("GlintL", (-0.485, -1.075, 3.175), (0.052, 0.028, 0.064), glint, segments=20, rings=12, parent=pupil_l)
    uv_sphere("GlintR", (0.375, -1.075, 3.175), (0.052, 0.028, 0.064), glint, segments=20, rings=12, parent=pupil_r)

    # Two-puff muzzle and small nose.
    uv_sphere("MuzzleL", (-0.23, -0.91, 2.68), (0.43, 0.18, 0.31), fur_light, parent=root)
    uv_sphere("MuzzleR", (0.23, -0.91, 2.68), (0.43, 0.18, 0.31), fur_light, parent=root)
    uv_sphere("Nose", (0, -1.095, 2.78), (0.22, 0.105, 0.15), black, segments=24, rings=14, parent=root)
    mouth_mesh(root, black)

    # Hoodie sleeves/arms and tiny dark paws.
    arm_l = uv_sphere("ArmL", (-0.73, -0.16, 1.44), (0.32, 0.30, 0.58), hoodie, parent=root)
    arm_r = uv_sphere("ArmR", (0.73, -0.16, 1.44), (0.32, 0.30, 0.58), hoodie, parent=root)
    arm_l.rotation_euler.y = -0.24
    arm_r.rotation_euler.y = 0.24
    uv_sphere("HandL", (-0.72, -0.43, 1.06), (0.25, 0.20, 0.20), mask, parent=arm_l)
    uv_sphere("HandR", (0.72, -0.43, 1.06), (0.25, 0.20, 0.20), mask, parent=arm_r)

    # Pocket and tiny feet.
    uv_sphere("Pocket", (0, -0.58, 1.19), (0.52, 0.08, 0.24), hoodie_shadow, parent=root)
    uv_sphere("FootL", (-0.43, -0.20, 0.58), (0.34, 0.39, 0.22), mask, parent=root)
    uv_sphere("FootR", (0.43, -0.20, 0.58), (0.34, 0.39, 0.22), mask, parent=root)

    # Oversized four-segment striped tail, tucked behind the body on viewer-right.
    tail_specs = [
        ("Tail01", (0.92, 0.27, 0.95), (0.52, 0.44, 0.56), mask, 0.22),
        ("Tail02", (1.25, 0.28, 1.20), (0.58, 0.46, 0.62), fur_light, 0.35),
        ("Tail03", (1.52, 0.30, 1.54), (0.60, 0.47, 0.64), mask, 0.44),
        ("Tail04", (1.67, 0.32, 1.91), (0.56, 0.44, 0.58), fur_light, 0.55),
    ]
    previous = root
    tails = []
    for name, loc, scale, mat, rot in tail_specs:
        segment = uv_sphere(name, loc, scale, mat, parent=previous)
        segment.rotation_euler.y = rot
        previous = segment
        tails.append(segment)

    # Preserve a mild forward-facing resting pose.
    root.rotation_euler = (0.0, 0.0, 0.0)
    return root


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_preview(preview_dir: Path, root: bpy.types.Object) -> None:
    preview_dir.mkdir(parents=True, exist_ok=True)

    floor_mat = material("Preview Floor", (0.92, 0.89, 0.84, 1.0), 0.95)
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0.65, 0.34))
    floor = bpy.context.object
    floor.name = "PreviewFloor"
    floor.data.materials.append(floor_mat)

    bpy.ops.object.camera_add(location=(0.0, -8.6, 2.45))
    camera = bpy.context.object
    camera.data.lens = 62
    camera.data.sensor_width = 36
    look_at(camera, Vector((0.15, 0.0, 2.30)))
    bpy.context.scene.camera = camera

    def area(name, loc, energy, size, color):
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.data.color = color
        look_at(light, Vector((0, 0, 2.3)))

    area("Key", (-4.2, -4.8, 6.8), 950, 5.0, (1.0, 0.88, 0.78))
    area("Fill", (4.8, -2.0, 4.2), 650, 4.0, (0.80, 0.88, 1.0))
    area("Rim", (1.0, 3.4, 5.4), 850, 3.0, (1.0, 0.92, 0.82))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(preview_dir / "raffi-live-v1-preview.png")
    scene.world.color = (0.055, 0.050, 0.047)
    scene.render.image_settings.color_mode = "RGBA"
    bpy.ops.render.render(write_still=True)


def export_glb(root: bpy.types.Object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for obj in root.children_recursive:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = root

    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_apply=False,
        export_animations=False,
        export_lights=False,
        export_cameras=False,
        export_morph=True,
        export_morph_normal=False,
        export_morph_tangent=False,
    )


def main() -> None:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    clear_scene()
    root = build_character()

    # Export before adding preview-only floor/lights/camera.
    export_glb(root, output)

    if args.preview_dir:
        setup_preview(Path(args.preview_dir).expanduser().resolve(), root)

    print(f"RAFFI_GLTF={output}")
    print(f"RAFFI_GLTF_BYTES={output.stat().st_size}")
    if args.preview_dir:
        print(f"RAFFI_PREVIEW={Path(args.preview_dir).expanduser().resolve() / 'raffi-live-v1-preview.png'}")


if __name__ == "__main__":
    main()
