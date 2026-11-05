"""Blender scene builder for the original three-friends 3D cartoon."""
from __future__ import annotations

import json
import math
import sys
import textwrap
from pathlib import Path

import bpy
from mathutils import Vector


def material(name, color, roughness=0.62):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.roughness = roughness
    return mat


def uv_sphere(name, location, scale, mat, segments=32, rings=20):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return obj


def rounded_box(name, location, scale, mat, bevel=0.12):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    modifier = obj.modifiers.new("Soft rounded edges", "BEVEL")
    modifier.width = bevel
    modifier.segments = 4
    obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj


def cylinder_between(name, start, end, radius, mat):
    vector = Vector(end) - Vector(start)
    midpoint = (Vector(start) + Vector(end)) * 0.5
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=20, radius=radius, depth=vector.length, location=midpoint
    )
    obj = bpy.context.object
    obj.name = name
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = vector.to_track_quat("Z", "Y")
    obj.data.materials.append(mat)
    obj.modifiers.new("Soft limb normals", "WEIGHTED_NORMAL")
    return obj


def text_object(name, body, location, size, mat, align="CENTER"):
    data = bpy.data.curves.new(name, type="FONT")
    data.body = body
    data.size = size
    data.align_x = align
    data.align_y = "CENTER"
    data.extrude = 0.003
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler[0] = math.radians(90)
    obj.data.materials.append(mat)
    return obj


def point_camera(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat(
        "-Z", "Y"
    ).to_euler()


def build_character(name, x, body_mat, accent_mat, hair_mat, hair_style, dark, cream):
    base_z = 1.62
    before = set(bpy.data.objects)
    pivot = bpy.data.objects.new(f"{name} - animation pivot", None)
    bpy.context.collection.objects.link(pivot)
    pivot.location = (x, 0, base_z)
    body = uv_sphere(f"{name} - soft rounded body", (x, 0, base_z), (0.80, 0.57, 1.05), body_mat)
    uv_sphere(f"{name} - left eye", (x - 0.23, -0.51, base_z + 0.25), (0.09, 0.065, 0.14), dark)
    uv_sphere(f"{name} - right eye", (x + 0.23, -0.51, base_z + 0.25), (0.09, 0.065, 0.14), dark)
    uv_sphere(f"{name} - left eye shine", (x - 0.25, -0.573, base_z + 0.30), (0.026, 0.018, 0.039), cream)
    uv_sphere(f"{name} - right eye shine", (x + 0.21, -0.573, base_z + 0.30), (0.026, 0.018, 0.039), cream)
    mouth = uv_sphere(f"{name} - talking smile", (x, -0.58, base_z - 0.10), (0.13, 0.035, 0.055), dark)
    uv_sphere(f"{name} - left cheek", (x - 0.46, -0.50, base_z - 0.04), (0.12, 0.035, 0.055), accent_mat)
    uv_sphere(f"{name} - right cheek", (x + 0.46, -0.50, base_z - 0.04), (0.12, 0.035, 0.055), accent_mat)

    collar = uv_sphere(f"{name} - collar", (x, -0.01, base_z - 0.52), (0.54, 0.52, 0.13), accent_mat)
    collar.scale = (0.58, 0.52, 0.11)
    uv_sphere(f"{name} - left shoe", (x - 0.30, -0.12, 0.57), (0.23, 0.34, 0.13), dark)
    uv_sphere(f"{name} - right shoe", (x + 0.30, -0.12, 0.57), (0.23, 0.34, 0.13), dark)

    if hair_style == "tuft":
        for offset, height in ((-0.25, 0.06), (-0.08, 0.22), (0.12, 0.17), (0.30, 0.07)):
            uv_sphere(
                f"{name} - hair tuft", (x + offset, -0.02, base_z + 0.90 + height / 2),
                (0.19, 0.18, height + 0.12), hair_mat,
            )
    elif hair_style == "curls":
        for offset, height in ((-0.39, 0.84), (-0.20, 1.00), (0.02, 1.03),
                               (0.24, 0.98), (0.42, 0.84)):
            uv_sphere(f"{name} - curl", (x + offset, -0.02, base_z + height),
                      (0.20, 0.19, 0.21), hair_mat)
    else:
        uv_sphere(f"{name} - cap crown", (x, 0.0, base_z + 1.04), (0.69, 0.54, 0.26), hair_mat)
        uv_sphere(f"{name} - cap brim", (x, -0.37, base_z + 0.98), (0.73, 0.36, 0.075), accent_mat)

    arms = []
    for side in (-1, 1):
        shoulder = (x + side * 0.66, 0.0, base_z - 0.31)
        elbow = (x + side * 0.93, -0.02, base_z - 0.60)
        wrist = (x + side * 1.00, -0.04, base_z - 0.80)
        upper = cylinder_between(f"{name} - upper arm", shoulder, elbow, 0.105, body_mat)
        lower = cylinder_between(f"{name} - lower arm", elbow, wrist, 0.095, body_mat)
        hand = uv_sphere(f"{name} - hand", wrist, (0.14, 0.13, 0.14), accent_mat)
        arms.append((upper, lower, hand, side, shoulder))

    for obj in set(bpy.data.objects) - before:
        if obj != pivot:
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    return {"body": body, "mouth": mouth, "pivot": pivot, "arms": arms,
            "base_z": base_z, "x": x}


def setup_scene(config):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for data in bpy.data.materials:
        bpy.data.materials.remove(data)

    mats = {
        "background": material("Deep teal studio", (0.025, 0.105, 0.15)),
        "stage": material("Blue-green stage", (0.055, 0.22, 0.28)),
        "dark": material("Warm dark details", (0.035, 0.065, 0.10)),
        "cream": material("Eye sparkle", (1.0, 0.95, 0.73)),
        "pip": material("Pip mint", (0.12, 0.78, 0.59)),
        "pip_accent": material("Pip orange", (1.0, 0.47, 0.14)),
        "maya": material("Maya lilac", (0.62, 0.36, 0.88)),
        "maya_accent": material("Maya sunshine", (1.0, 0.71, 0.20)),
        "maya_hair": material("Maya plum curls", (0.20, 0.105, 0.22)),
        "ravi": material("Ravi sky blue", (0.12, 0.54, 0.87)),
        "ravi_accent": material("Ravi coral", (1.0, 0.30, 0.24)),
        "ravi_hat": material("Ravi navy cap", (0.08, 0.17, 0.29)),
        "white": material("Speech card", (0.95, 0.98, 0.90)),
        "ink": material("Speech lettering", (0.04, 0.12, 0.17)),
    }

    rounded_box("Stage platform", (0, 0.2, 0.18), (10.3, 3.1, 0.34), mats["stage"], 0.18)
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.02))
    bpy.context.object.name = "Studio floor"
    bpy.context.object.data.materials.append(mats["background"])

    characters = {
        "Pip": build_character("Pip", -3.0, mats["pip"], mats["pip_accent"], mats["dark"], "tuft", mats["dark"], mats["cream"]),
        "Maya": build_character("Maya", 0.0, mats["maya"], mats["maya_accent"], mats["maya_hair"], "curls", mats["dark"], mats["cream"]),
        "Ravi": build_character("Ravi", 3.0, mats["ravi"], mats["ravi_accent"], mats["ravi_hat"], "cap", mats["dark"], mats["cream"]),
    }

    # A softly rounded speech board and raised letters establish a clear dialogue stage.
    rounded_box("Floating speech card", (0, 0.12, 4.65), (9.5, 0.22, 1.65), mats["white"], 0.20)
    title = text_object("Episode title", "THE WATER-CYCLE MYSTERY", (0, -0.06, 5.18), 0.30, mats["ink"])
    speaker = text_object("Current speaker", "", (0, -0.075, 4.80), 0.24, mats["pip_accent"])
    dialogue = text_object("Spoken dialogue", "", (0, -0.075, 4.43), 0.22, mats["ink"])
    title.data.space_character = 1.05

    for index in range(10):
        x = -4.5 + index * 1.0
        uv_sphere(f"Backdrop sparkle {index}", (x, 1.15, 3.4 + (index % 3) * 0.43),
                  (0.045, 0.045, 0.045), mats["maya_accent"])

    bpy.ops.object.camera_add(location=(0, -15.5, 5.2))
    camera = bpy.context.object
    camera.name = "Three-friends cartoon camera"
    point_camera(camera, (0, 0, 2.85))

    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "paint.sl"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.curvature_ridge_factor = 1.25
    scene.display.shading.curvature_valley_factor = 1.0
    scene.display.shading.show_specular_highlight = True
    scene.display.shading.background_type = "WORLD"
    scene.world.color = (0.025, 0.105, 0.15)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.fps = config["fps"]
    scene.render.filepath = str(Path(config["output"]).resolve())
    scene.render.use_file_extension = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_percentage = 100
    scene.frame_start = 1
    scene.frame_end = max(1, math.ceil(config["duration"] * config["fps"]))

    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 12.0
    scene.camera.data.lens = 50

    return scene, characters, speaker, dialogue


def main():
    if "--" not in sys.argv:
        raise SystemExit("Pass a config JSON path after Blender's -- separator")
    config_path = Path(sys.argv[sys.argv.index("--") + 1])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    scene, characters, speaker_label, dialogue_label = setup_scene(config)
    cues = config["cues"]
    speaker_colors = {
        "Pip": (1.0, 0.32, 0.08, 1),
        "Maya": (0.58, 0.30, 0.88, 1),
        "Ravi": (0.95, 0.25, 0.18, 1),
    }

    def update_dialogue(scene):
        seconds = max(0.0, (scene.frame_current - 1) / scene.render.fps)
        active = next((cue for cue in reversed(cues) if cue["start"] <= seconds),
                      cues[0])
        speaker = active["speaker"]
        speaker_label.data.body = speaker.upper()
        speaker_label.data.materials.clear()
        speaker_label.data.materials.append(bpy.data.materials.get({
            "Pip": "Pip orange", "Maya": "Maya sunshine", "Ravi": "Ravi coral",
        }[speaker]))
        dialogue_label.data.body = textwrap.fill(active["text"], width=65)
        dialogue_label.data.align_x = "CENTER"
        characters[speaker]["pivot"].location.z = (
            characters[speaker]["base_z"] + 0.05 * math.sin(seconds * 6.0)
        )
        for name, character in characters.items():
            talking = name == speaker and active["start"] <= seconds <= active["end"]
            character["mouth"].scale.z = 0.12 if talking and int(seconds * 5) % 2 == 0 else 0.055
            character["mouth"].location.z = character["base_z"] - (0.08 if talking else 0.10)

    bpy.app.handlers.frame_change_pre.clear()
    bpy.app.handlers.frame_change_pre.append(update_dialogue)
    scene.frame_set(1)
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
