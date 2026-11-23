"""Marina's look, built on the stock VRoid model.

  python3 scripts/marina-look/hairtex2.py   (run from this folder: cleaner hair textures)
  /Applications/Blender.app/Contents/MacOS/Blender --background --python scripts/marina-look/build.py
  ios/build-ipa.sh

Reads app/models/model.original.vrm.bak and writes app/models/model.vrm:
cel-shaded hair with outlines (original colour and style), plus a fitted choker, crescent and star pins, a hoodie
chain and ear piercings (accessories.py). Needs Blender's VRM add-on.
"""
import bpy, numpy as np, os
D = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(D, "..", "..", "app", "models", "model.original.vrm.bak")
OUT = os.path.join(D, "..", "..", "app", "models", "model.vrm")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.vrm")
bpy.ops.import_scene.vrm(filepath=SRC)
for name, png in (("_17", "hair_17_new.png"), ("_19", "hair_19_new.png")):
    img = bpy.data.images[name]
    new = bpy.data.images.load(os.path.join(D, png))
    w, h = new.size
    px = np.empty(w * h * 4, np.float32); new.pixels.foreach_get(px)
    img.scale(w, h)
    img.pixels.foreach_set(px)
    img.pack()
    bpy.data.images.remove(new)
    print("swapped", name, img.size[:])
hair = bpy.data.objects["Hair"]
for m in hair.data.materials:
    e = m.vrm_addon_extension.mtoon1.extensions.vrmc_materials_mtoon
    print("was", m.name, tuple(e.shade_color_factor), e.shading_toony_factor, e.shading_shift_factor)
    if "HAIR_01" in m.name:
        e.shade_color_factor = (0.40, 0.37, 0.52)
    else:
        e.shade_color_factor = (0.24, 0.21, 0.36)
    e.shading_toony_factor = 0.88
    e.shading_shift_factor = -0.05
    e.outline_width_mode = "worldCoordinates"
    e.outline_width_factor = 0.0009 if "HAIR_01" in m.name else 0.0005
    e.outline_color_factor = (0.03, 0.025, 0.05)
    e.outline_lighting_mix_factor = 0.0
    e.shading_toony_factor = 0.97
    e.parametric_rim_color_factor = (0.10, 0.10, 0.14)
    e.parametric_rim_fresnel_power_factor = 5.0
    e.parametric_rim_lift_factor = 0.0
    e.rim_lighting_mix_factor = 1.0
exec(open(os.path.join(D, "accessories.py")).read())
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
bpy.ops.object.select_all(action="DESELECT"); arm.select_set(True)
bpy.context.view_layer.objects.active = arm
print("export", bpy.ops.export_scene.vrm(filepath=OUT))
