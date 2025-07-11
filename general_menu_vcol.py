import bpy
import random
import json
import re
import math
import mathutils
from collections import defaultdict
from bpy_extras.io_utils import ExportHelper, ImportHelper

# -----------------------------
# Globals
# -----------------------------
vertex_data_store = {}
vertex_backup_store = {}
saved_values = {}
vertex_backup_store = {}
_vc_gradient_copy_data = {}
_vc_gradient_presets = {}
# -----------------------------
# Helpers
# -----------------------------
def vc_gradient_live_update(self, context):
    try:
        bpy.ops.object.vc_set_gradient()
    except Exception:
        pass
    return None

def ensure_vertex_color_attribute(obj):
    mesh = obj.data
    attr = mesh.color_attributes.get("Attribute")
    if not attr:
        if mesh.color_attributes:
            mesh.color_attributes[0].name = "Attribute"
            attr = mesh.color_attributes[0]
        else:
            attr = mesh.color_attributes.new("Attribute", 'BYTE_COLOR', 'CORNER')
    mesh.color_attributes.active_color = attr
    return attr

def run_in_vertex_paint_mode(operator_func, **kwargs):
    obj = bpy.context.object
    prev = obj.mode
    bpy.ops.object.mode_set(mode='VERTEX_PAINT')
    ensure_vertex_color_attribute(obj)
    operator_func(**kwargs)
    bpy.ops.object.mode_set(mode=prev)

def backup_vertex_colors(obj):
    attr = ensure_vertex_color_attribute(obj)
    vertex_backup_store[obj.name] = [tuple(lc.color) for lc in attr.data]

def restore_vertex_colors(obj):
    if obj.name not in vertex_backup_store:
        return
    attr = ensure_vertex_color_attribute(obj)
    backup = vertex_backup_store[obj.name]
    # Solo iteramos hasta el mínimo entre loops actuales y datos guardados
    count = min(len(attr.data), len(backup))
    for i in range(count):
        attr.data[i].color = backup[i]
    obj.data.update()


def linear_to_srgb(c):
    if c <= 0.0031308:
        return 12.92 * c
    else:
        return 1.055 * (c ** (1.0 / 2.4)) - 0.055

def sample_update(self, context):
    lin = self.vc_sample_color_picker
    srgb = tuple(linear_to_srgb(c) for c in lin)
    brush = context.tool_settings.vertex_paint.brush
    brush.color = srgb
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

# -----------------------------
# Color & Curve Helpers
# -----------------------------
def apply_balance(c, shadows, midtones, highlights):
    """Apply simple shadows/midtones/highlights balance to channel."""
    if c < 0.333:
        return c + shadows * (0.333 - c) / 0.333
    elif c < 0.666:
        return c + midtones * (0.666 - c) / 0.333
    else:
        return c + highlights * (1.0 - c) / 0.334

def apply_curve_point(c, shadow_pt, mid_pt, highlight_pt):
    """Simple 3-point curve interpolation with safeguards contra división por cero."""
    # Si mid_pt está en 0, evitamos dividir por cero y devolvemos el valor en shadow_pt escalado linealmente
    if mid_pt <= 0.0:
        return c * shadow_pt
    # Si mid_pt está en 1, evitamos dividir por cero en la segunda rama
    if mid_pt >= 1.0:
        return shadow_pt + (c - mid_pt) * (highlight_pt - shadow_pt)

    if c < mid_pt:
        # División segura porque mid_pt > 0
        return (c / mid_pt) * shadow_pt
    else:
        denom = 1.0 - mid_pt
        # denom > 0 porque mid_pt < 1
        return shadow_pt + ((c - mid_pt) / denom) * (highlight_pt - shadow_pt)

# -----------------------------
# Main Update
# -----------------------------
def update_vertex_colors(obj, context):
    if obj.name not in vertex_backup_store:
        backup_vertex_colors(obj)
    restore_vertex_colors(obj)

    # Pre-paint operations
    bpy.ops.object.mode_set(mode='VERTEX_PAINT')
    bpy.ops.paint.vertex_color_levels(offset=obj.vc_levels_offset, gain=obj.vc_levels_gain)
    bpy.ops.paint.vertex_color_hsv(h=obj.vc_hue, s=obj.vc_saturation, v=obj.vc_value)
    bpy.ops.paint.vertex_color_brightness_contrast(brightness=obj.vc_brightness, contrast=obj.vc_contrast)
    bpy.ops.object.mode_set(mode='OBJECT')

    attr = ensure_vertex_color_attribute(obj)
    use_r = obj.vc_channel_r
    use_g = obj.vc_channel_g
    use_b = obj.vc_channel_b

    for lc in attr.data:
        # Store original
        orig_r, orig_g, orig_b, a = lc.color
        r, g, b = orig_r, orig_g, orig_b

        # --- Apply all adjustments to temp variables ---
        # Gamma correction
        gamma = obj.vc_gamma
        inv_gamma = 1.0 / gamma if gamma != 0 else 1.0
        r, g, b = (pow(c, inv_gamma) for c in (r, g, b))

        # Exposure
        expo = 2.0 ** obj.vc_exposure
        r, g, b = (c * expo for c in (r, g, b))

        # Posterize
        levels = obj.vc_posterize
        if levels > 1:
            r = round(r * (levels - 1)) / (levels - 1)
            g = round(g * (levels - 1)) / (levels - 1)
            b = round(b * (levels - 1)) / (levels - 1)

        # Vibrance
        vib = obj.vc_vibrant
        mx = max(r, g, b); mn = min(r, g, b)
        sat = mx - mn
        adjustment = vib * (1 - sat)
        avg = (r + g + b) / 3
        r += (r - avg) * adjustment
        g += (g - avg) * adjustment
        b += (b - avg) * adjustment

        # Noise
        noise_amp = obj.vc_noise
        r += random.uniform(-noise_amp, noise_amp)
        g += random.uniform(-noise_amp, noise_amp)
        b += random.uniform(-noise_amp, noise_amp)

        # Color Balance
        r = apply_balance(r, obj.vc_shadows_balance, obj.vc_midtones_balance, obj.vc_highlights_balance)
        g = apply_balance(g, obj.vc_shadows_balance, obj.vc_midtones_balance, obj.vc_highlights_balance)
        b = apply_balance(b, obj.vc_shadows_balance, obj.vc_midtones_balance, obj.vc_highlights_balance)

        # RGB Curves
        r = apply_curve_point(r, obj.vc_curve_shadows, obj.vc_curve_midtones, obj.vc_curve_highlights)
        g = apply_curve_point(g, obj.vc_curve_shadows, obj.vc_curve_midtones, obj.vc_curve_highlights)
        b = apply_curve_point(b, obj.vc_curve_shadows, obj.vc_curve_midtones, obj.vc_curve_highlights)

        # --- Apply channel toggles ---
        final_r = modified_r = min(max(r, 0.0), 1.0)
        final_g = modified_g = min(max(g, 0.0), 1.0)
        final_b = modified_b = min(max(b, 0.0), 1.0)

        r_out = modified_r if use_r else orig_r
        g_out = modified_g if use_g else orig_g
        b_out = modified_b if use_b else orig_b

        lc.color = (r_out, g_out, b_out, a)

    obj.data.update()
    context.view_layer.update()


def live_update(self, context):
    if self.show_vc_fine_tune:
        update_vertex_colors(self, context)

# -----------------------------
# Panel redesign
# -----------------------------
class VertexColorPanel(bpy.types.Panel):
    bl_label = "Vertex Color Toolset"
    bl_idname = "VIEW3D_PT_vertex_color_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VertexColRefineKit'

    def draw(self, context):
        layout = self.layout
        obj = context.object
        scene = context.scene

        if not obj or obj.type != 'MESH':
            layout.label(text="Select a mesh object.")
            return

        # Basic Controls
        row = layout.row(align=True)
        row.operator("object.vc_smooth", text="Smooth Color")
        row.operator("object.vc_sharp_color", text="Sharp Color")

        row = layout.row(align=True)
        row.operator("object.vc_clean_color", text="Clean Color")
        row.operator("object.vc_dirty", text="Dirty Color")

        row = layout.row(align=True)
        row.operator("object.vc_invert", text="Invert Color")
        row.operator("object.vc_grayscale", text="Grayscale")

        row = layout.row(align=True)
        row.operator("object.vc_sepia", text="Sepia")
        row.operator("object.vc_cartoon", text="Cartoon")

        row = layout.row(align=True)
        row.operator("object.vc_hot", text="Hot")
        row.operator("object.vc_cold", text="Cold")
        row = layout.row(align=True)
        
        row.operator("object.vc_set_color", text="Set Color")
        # Color Picker
        layout.prop(obj, "vc_sample_color_picker", text="")

        # Channel Toggles
        row = layout.row(align=True)
        row.prop(obj, "vc_channel_r", toggle=True, text="R")
        row.prop(obj, "vc_channel_g", toggle=True, text="G")
        row.prop(obj, "vc_channel_b", toggle=True, text="B")

        # Fine Tune Settings
        layout.operator("object.vc_show_fine_tune", text="Fine‑Tune Settings", icon='PREFERENCES')
        if obj.show_vc_fine_tune:
            col = layout.column(align=True)
            for prop_name in [
                "vc_levels_offset", "vc_levels_gain", "vc_hue",
                "vc_saturation", "vc_value", "vc_brightness", "vc_contrast"
            ]:
                col.prop(obj, prop_name, slider=True)

            if any([obj.vc_channel_r, obj.vc_channel_g, obj.vc_channel_b]):
                layout.separator()
                layout.label(text="Advanced Adjustments:")
                adv = layout.column(align=True)
                for prop_name in ["vc_gamma", "vc_exposure", "vc_posterize", "vc_vibrant", "vc_noise"]:
                    adv.prop(obj, prop_name, slider=True)

                layout.separator()
                layout.label(text="Color Balance:")
                cb = layout.column(align=True)
                for prop_name in ["vc_shadows_balance", "vc_midtones_balance", "vc_highlights_balance"]:
                    cb.prop(obj, prop_name, slider=True)

                layout.separator()
                layout.label(text="RGB Curve Points:")
                cr = layout.column(align=True)
                for prop_name in ["vc_curve_shadows", "vc_curve_midtones", "vc_curve_highlights"]:
                    cr.prop(obj, prop_name, slider=True)

            row = layout.row(align=True)
            row.operator("object.vc_accept_changes", text="Apply")
            row.operator("object.vc_cancel_changes", text="Cancel")
            row = layout.row(align=True)
            row.operator("object.vc_save_values", text="Save Values")
            row.operator("object.vc_apply_saved_values", text="Apply Saved")
            layout.operator("object.vc_reset_values", text="Reset Values")

        # Gradient Settings
        layout.separator()
        layout.operator("object.vc_show_gradient", text="Gradient Settings", icon='IPO_LINEAR')
        if obj.show_vc_gradient:
            box = layout.box()
            box.prop(obj, "vc_gradient_axis", text="Mode")

            # Color Stops
            box.label(text="Color Stops:")
            stops_box = box.box()
            for idx, stop in enumerate(obj.vc_gradient_stops):
                row = stops_box.row(align=True)
                row.prop(stop, "factor", text=f"Pos {idx}")
                row.prop(stop, "color", text="")

            # Add/Remove
            row = stops_box.row(align=True)
            row.operator("object.vc_add_gradient_stop", icon='ADD', text="Add Stop")
            row.operator("object.vc_remove_gradient_stop", icon='REMOVE', text="Remove Stop")

            # Apply/Cancel Gradient
            row = box.row(align=True)
            row.operator("object.vc_apply_gradient", text="Apply", icon='CHECKMARK')
            row.operator("object.vc_cancel_gradient", text="Cancel", icon='CANCEL')

            # Copy/Paste
            row = box.row(align=True)
            row.operator("object.vc_copy_values", icon='COPYDOWN', text="Copy Values")
            row.operator("object.vc_paste_values", icon='PASTEDOWN', text="Paste Values")
            
            # Export/Import JSON
            row = box.row(align=True)
            row.operator("object.vc_export_json", icon='EXPORT', text="Export JSON")
            row.operator("object.vc_import_json", icon='IMPORT', text="Import JSON")

            # Save/Apply Preset
            row = box.row(align=True)
            row.operator("object.vc_save_preset", icon='FILE_NEW', text="Save Preset")
            row.operator("object.vc_apply_preset", icon='FILE_FOLDER', text="Apply Preset")

            # Show/Hide Preset List
            layout.separator()
            layout.operator(
                "object.vc_toggle_preset_list",
                text=("Hide Preset List" if scene.show_vc_preset_list else "Show Preset List"),
                icon='DOWNARROW_HLT' if scene.show_vc_preset_list else 'RIGHTARROW'
            )

            if scene.show_vc_preset_list:
                row = layout.row()
                row.template_list(
                    "VCGradientPresetList", "", context.scene,
                    "vc_gradient_presets", context.scene,
                    "vc_gradient_preset_index", rows=4
                )
                col = row.column(align=True)
                col.operator("object.vc_save_preset", icon='ADD', text="")
                col.operator("object.vc_delete_preset", icon='REMOVE', text="")

        # Animate Color
        layout.separator()
        layout.operator("object.vc_toggle_animate", text="Animate Color", icon='ANIM')
        if obj.show_vc_animate:
            row = layout.row(align=True)
            row.operator("object.vc_add_frame", text="Add Frame")
            row.operator("object.vc_remove_frame", text="Remove Frame")
            row = layout.row(align=True)
            row.operator("object.vc_export_animation", text="Export Anim Data")
            row.operator("object.vc_load_animated_data", text="Load Anim Data")
            layout.operator("object.vc_store_data", text="Store Data")
            row = layout.row(align=True)
            row.operator("object.vc_apply_animate", text="Apply Anim")
            row.operator("object.vc_cancel_animate", text="Cancel Anim")




# -----------------------------
# Simple Operators
# -----------------------------
class VCInvert(bpy.types.Operator):
    bl_idname = "object.vc_invert"
    bl_label = "Invert Vertex Colors"
    def execute(self, context):
        obj = context.object
        if obj and obj.type == 'MESH':
            attr = ensure_vertex_color_attribute(obj)
            for lc in attr.data:
                r, g, b, a = lc.color
                lc.color = (1-r, 1-g, 1-b, a)
            obj.data.update()
        return {'FINISHED'}

class VCSmooth(bpy.types.Operator):
    bl_idname = "object.vc_smooth"
    bl_label = "Smooth Vertex Colors"
    def execute(self, context):
        run_in_vertex_paint_mode(bpy.ops.paint.vertex_color_smooth)
        return {'FINISHED'}

class VCDirty(bpy.types.Operator):
    bl_idname = "object.vc_dirty"
    bl_label = "Dirty Vertex Colors"
    def execute(self, context):
        run_in_vertex_paint_mode(bpy.ops.paint.vertex_color_dirt)
        return {'FINISHED'}

class VCSetColor(bpy.types.Operator):
    bl_idname = "object.vc_set_color"
    bl_label = "Set Vertex Color"
    def execute(self, context):
        run_in_vertex_paint_mode(bpy.ops.paint.vertex_color_set)
        return {'FINISHED'}
    
class VCSharpColor(bpy.types.Operator):
    bl_idname = "object.vc_sharp_color"
    bl_label = "Sharp Color"
    bl_description = "Apply flat (non‑smooth) vertex coloring per face"
    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
        attr = ensure_vertex_color_attribute(obj)
        mesh = obj.data
        # For each polygon, compute average vertex‑color and apply to all its loops
        for poly in mesh.polygons:
            # collect existing colors
            cols = [attr.data[li].color[:3] for li in poly.loop_indices]
            avg = [sum(ch) / len(ch) for ch in zip(*cols)]
            for li in poly.loop_indices:
                attr.data[li].color = (*avg, attr.data[li].color[3])
        mesh.update()
        return {'FINISHED'}

class VCCleanColor(bpy.types.Operator):
    bl_idname = "object.vc_clean_color"
    bl_label = "Clean Color"
    bl_description = "Lighten colors for a cleaner look with reduced shadows"
    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
        attr = ensure_vertex_color_attribute(obj)
        # Lighten each loop's color by +0.2 (clamped to [0,1])
        for lc in attr.data:
            r, g, b, a = lc.color
            lc.color = (min(r + 0.2, 1.0),
                        min(g + 0.2, 1.0),
                        min(b + 0.2, 1.0),
                        a)
        obj.data.update()
        return {'FINISHED'}

class VCSampleColor(bpy.types.Operator):
    bl_idname = "object.vc_sample_color"
    bl_label = "Sample Vertex Color"
    def execute(self, context):
        run_in_vertex_paint_mode(bpy.ops.paint.sample_color, location=(300,100))
        return {'FINISHED'}

# -----------------------------
# Fine‑Tune Operators
# -----------------------------
class VCShowFineTune(bpy.types.Operator):
    bl_idname = "object.vc_show_fine_tune"
    bl_label = "Toggle Fine‑Tune"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                backup_vertex_colors(obj)
                obj.show_vc_fine_tune = not obj.show_vc_fine_tune
        return {'FINISHED'}

class VCAcceptChanges(bpy.types.Operator):
    bl_idname = "object.vc_accept_changes"
    bl_label = "Apply Fine‑Tune"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.show_vc_fine_tune:
                update_vertex_colors(obj, context)
                vertex_backup_store.pop(obj.name, None)
                for prop, val in (
                    ("vc_levels_offset",0.0), ("vc_levels_gain",1.0),
                    ("vc_hue",0.5), ("vc_saturation",1.0), ("vc_value",1.0),
                    ("vc_brightness",0.0), ("vc_contrast",0.0),
                    ("vc_gamma",1.0), ("vc_exposure",0.0),
                    ("vc_posterize",0.0), ("vc_vibrant",1.0),
                    ("vc_noise",0.0),
                    ("vc_shadows_balance",0.0), ("vc_midtones_balance",0.0), ("vc_highlights_balance",0.0),
                    ("vc_curve_shadows",0.0), ("vc_curve_midtones",0.5), ("vc_curve_highlights",1.0),
                    ("vc_channel_r", False), ("vc_channel_g", False), ("vc_channel_b", False),
                ):
                    setattr(obj, prop, val)
                obj.show_vc_fine_tune = False
        return {'FINISHED'}

class VCCancelChanges(bpy.types.Operator):
    bl_idname = "object.vc_cancel_changes"
    bl_label = "Cancel Fine‑Tune"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.show_vc_fine_tune:
                restore_vertex_colors(obj)
                vertex_backup_store.pop(obj.name, None)
                for prop, val in (
                    ("vc_levels_offset",0.0), ("vc_levels_gain",1.0),
                    ("vc_hue",0.5), ("vc_saturation",1.0), ("vc_value",1.0),
                    ("vc_brightness",0.0), ("vc_contrast",0.0),
                    ("vc_gamma",1.0), ("vc_exposure",0.0),
                    ("vc_posterize",0.0), ("vc_vibrant",1.0),
                    ("vc_noise",0.0),
                    ("vc_shadows_balance",0.0), ("vc_midtones_balance",0.0), ("vc_highlights_balance",0.0),
                    ("vc_curve_shadows",0.0), ("vc_curve_midtones",0.5), ("vc_curve_highlights",1.0),
                    ("vc_channel_r", False), ("vc_channel_g", False), ("vc_channel_b", False),
                ):
                    setattr(obj, prop, val)
                obj.show_vc_fine_tune = False
        return {'FINISHED'}

class VCResetValues(bpy.types.Operator):
    bl_idname = "object.vc_reset_values"
    bl_label = "Reset Fine‑Tune Sliders"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.show_vc_fine_tune:
                for prop, val in (
                    ("vc_levels_offset",0.0), ("vc_levels_gain",1.0),
                    ("vc_hue",0.5), ("vc_saturation",1.0), ("vc_value",1.0),
                    ("vc_brightness",0.0), ("vc_contrast",0.0),
                    ("vc_gamma",1.0), ("vc_exposure",0.0),
                    ("vc_posterize",0.0), ("vc_vibrant",1.0),
                    ("vc_noise",0.0),
                    ("vc_shadows_balance",0.0), ("vc_midtones_balance",0.0), ("vc_highlights_balance",0.0),
                    ("vc_curve_shadows",0.0), ("vc_curve_midtones",0.5), ("vc_curve_highlights",1.0),
                    ("vc_channel_r", False), ("vc_channel_g", False), ("vc_channel_b", False),
                ):
                    setattr(obj, prop, val)
                update_vertex_colors(obj, context)
        return {'FINISHED'}

class VCSaveValues(bpy.types.Operator):
    bl_idname = "object.vc_save_values"
    bl_label = "Save Fine‑Tune Values"
    def execute(self, context):
        obj = context.object
        if obj and obj.type == 'MESH':
            for prop in (
                "vc_levels_offset","vc_levels_gain","vc_hue",
                "vc_saturation","vc_value","vc_brightness","vc_contrast",
                "vc_gamma","vc_exposure","vc_posterize","vc_vibrant","vc_noise",
                "vc_shadows_balance","vc_midtones_balance","vc_highlights_balance",
                "vc_curve_shadows","vc_curve_midtones","vc_curve_highlights",
                "vc_channel_r","vc_channel_g","vc_channel_b"
            ):
                saved_values[prop] = getattr(obj, prop)
            self.report({'INFO'}, "Values saved")
        return {'FINISHED'}

class VCApplySavedValues(bpy.types.Operator):
    bl_idname = "object.vc_apply_saved_values"
    bl_label = "Apply Saved Values"
    def execute(self, context):
        if not saved_values:
            self.report({'WARNING'}, "No saved values")
            return {'CANCELLED'}
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                for prop, val in saved_values.items():
                    setattr(obj, prop, val)
                update_vertex_colors(obj, context)
        return {'FINISHED'}

# -----------------------------
# Animate Handlers & Ops
# -----------------------------
def update_vertex_colors_handler(scene):
    if bpy.context.screen.is_animation_playing:
        return
    for obj in scene.objects:
        if obj.vc_animate_enabled and obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            if any(int(kp.co.x) == scene.frame_current for fc in action.fcurves for kp in fc.keyframe_points if 'Attribute' in fc.data_path):
                mesh = obj.data
                attr = ensure_vertex_color_attribute(obj)
                evals = {}
                for fc in action.fcurves:
                    m = re.match(r'.*data\[(\d+)\]\.color', fc.data_path)
                    if m:
                        li, ch = int(m.group(1)), fc.array_index
                        evals.setdefault(li, {})[ch] = fc.evaluate(scene.frame_current)
                for li, chans in evals.items():
                    col = list(attr.data[li].color)
                    for ch, v in chans.items():
                        col[ch] = v
                    attr.data[li].color = tuple(col)
                mesh.update()

def auto_store_data_handler(scene):
    if bpy.context.screen.is_animation_playing:
        return
    for obj in scene.objects:
        if obj.vc_animate_enabled and obj.animation_data and obj.animation_data.action:
            if any(int(kp.co.x) == scene.frame_current for fc in obj.animation_data.action.fcurves for kp in fc.keyframe_points):
                frame = scene.frame_current
                attr = ensure_vertex_color_attribute(obj)
                key = (obj.name, frame)
                vertex_data_store[key] = [
                    {'object': obj.name, 'frame': frame, 'loop_index': i,
                     'vertex_index': obj.data.loops[i].vertex_index, 'color': tuple(lc.color)}
                    for i, lc in enumerate(attr.data)
                ]

def validate_color_keyframes_handler(scene):
    if not bpy.context.screen.is_animation_playing:
        return
    if bpy.context.mode != 'OBJECT':
        return
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        total_loops = len(mesh.loops)
        anim = mesh.animation_data
        if not anim or not anim.action:
            continue
        to_remove = []
        for fc in anim.action.fcurves:
            m = re.match(r'color_attributes\["Attribute"\]\.data\[(\d+)\]\.color', fc.data_path)
            if m and int(m.group(1)) >= total_loops:
                to_remove.append(fc)
        for fc in to_remove:
            anim.action.fcurves.remove(fc)

class VCToggleAnimate(bpy.types.Operator):
    bl_idname = "object.vc_toggle_animate"
    bl_label = "Toggle Animate Color Panel"
    def execute(self, context):
        scene = context.scene
        handlers = bpy.app.handlers.frame_change_post
        closing = any(o.show_vc_animate for o in context.selected_objects)
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj.show_vc_animate = not obj.show_vc_animate
                obj.vc_animate_enabled = obj.show_vc_animate

        if closing:
            bpy.ops.object.vc_store_data()
            scene.frame_set(0)
            for obj in context.selected_objects:
                if obj.animation_data:
                    obj.animation_data_clear()
                if obj.data.animation_data:
                    obj.data.animation_data_clear()
                if obj.data.shape_keys and obj.data.shape_keys.animation_data:
                    obj.data.shape_keys.animation_data_clear()
            for h in (update_vertex_colors_handler, auto_store_data_handler, validate_color_keyframes_handler):
                if h in handlers:
                    handlers.remove(h)
        else:
            for h in (update_vertex_colors_handler, auto_store_data_handler, validate_color_keyframes_handler):
                if h not in handlers:
                    handlers.append(h)
            orig = scene.frame_current
            for (name, frm), data in vertex_data_store.items():
                obj = bpy.data.objects.get(name)
                if obj and obj.vc_animate_enabled:
                    attr = ensure_vertex_color_attribute(obj)
                    scene.frame_set(frm)
                    for e in data:
                        i, col = e['loop_index'], e['color']
                        attr.data[i].color = col
                        for ch in range(4):
                            obj.data.keyframe_insert(f'color_attributes["Attribute"].data[{i}].color', frame=frm, index=ch)
                    obj.data.update()
            scene.frame_set(orig)
        return {'FINISHED'}

class VCStoreData(bpy.types.Operator):
    bl_idname = "object.vc_store_data"
    bl_label = "Store Data"
    def execute(self, context):
        global vertex_data_store
        names = {o.name for o in context.selected_objects if o.vc_animate_enabled}
        vertex_data_store = {k: v for k, v in vertex_data_store.items() if k[0] not in names}
        frames = set()
        for obj in context.selected_objects:
            if obj.vc_animate_enabled:
                for anim in (getattr(obj.animation_data, "action", None),
                             getattr(obj.data.animation_data, "action", None)):
                    if anim:
                        for fc in anim.fcurves:
                            for kp in fc.keyframe_points:
                                frames.add(int(kp.co.x))
        if not frames:
            frames.add(context.scene.frame_current)
        for frm in sorted(frames):
            context.scene.frame_set(frm)
            for obj in context.selected_objects:
                if obj.vc_animate_enabled:
                    attr = ensure_vertex_color_attribute(obj)
                    key = (obj.name, frm)
                    vertex_data_store[key] = [
                        {'object': obj.name, 'frame': frm, 'loop_index': i,
                         'vertex_index': obj.data.loops[i].vertex_index, 'color': tuple(lc.color)}
                        for i, lc in enumerate(attr.data)
                    ]
        self.report({'INFO'}, f"Data stored for frames: {sorted(frames)}")
        return {'FINISHED'}

class VCApplyAnimate(bpy.types.Operator):
    bl_idname = "object.vc_apply_animate"
    bl_label = "Apply Animate Color"
    def execute(self, context):
        scene, frames = context.scene, set()
        for obj in context.selected_objects:
            if obj.vc_animate_enabled and obj.animation_data and obj.animation_data.action:
                for fc in obj.animation_data.action.fcurves:
                    for kp in fc.keyframe_points:
                        frames.add(int(kp.co.x))
        if not frames:
            frames.add(scene.frame_current)
        for frm in sorted(frames):
            scene.frame_set(frm)
            for obj in context.selected_objects:
                if obj.vc_animate_enabled:
                    attr = ensure_vertex_color_attribute(obj)
                    key = (obj.name, frm)
                    vertex_data_store[key] = [
                        {'object': obj.name, 'frame': frm, 'loop_index': i,
                         'vertex_index': obj.data.loops[i].vertex_index, 'color': tuple(lc.color)}
                        for i, lc in enumerate(attr.data)
                    ]
        scene.frame_set(0)
        for obj in context.selected_objects:
            if obj.vc_animate_enabled:
                if obj.animation_data:
                    obj.animation_data_clear()
                if obj.data.animation_data:
                    obj.data.animation_data_clear()
                obj.show_vc_animate = obj.vc_animate_enabled = False
        for h in (update_vertex_colors_handler, auto_store_data_handler, validate_color_keyframes_handler):
            if h in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(h)
        self.report({'INFO'}, f"Animation applied and data stored for frames: {sorted(frames)}")
        return {'FINISHED'}

class VCCancelAnimate(bpy.types.Operator):
    bl_idname = "object.vc_cancel_animate"
    bl_label = "Cancel Animate Color"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.vc_animate_enabled:
                if obj.animation_data:
                    obj.animation_data_clear()
                if obj.data.animation_data:
                    obj.data.animation_data_clear()
                obj.show_vc_animate = obj.vc_animate_enabled = False
        for h in (update_vertex_colors_handler, auto_store_data_handler, validate_color_keyframes_handler):
            if h in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(h)
        self.report({'INFO'}, "Animation canceled")
        return {'CANCELLED'}

class VCAddFrame(bpy.types.Operator):
    bl_idname = "object.vc_add_frame"
    bl_label = "Add Frame"
    def execute(self, context):
        frame = context.scene.frame_current
        for obj in context.selected_objects:
            if obj.vc_animate_enabled:
                attr = ensure_vertex_color_attribute(obj)
                if obj.name not in vertex_backup_store:
                    backup_vertex_colors(obj)
                backup = vertex_backup_store[obj.name]
                for i, lc in enumerate(attr.data):
                    curr = tuple(lc.color)
                    if curr != backup[i]:
                        for ch in range(4):
                            obj.data.keyframe_insert(f'color_attributes["Attribute"].data[{i}].color', frame=frame, index=ch)
                        backup[i] = curr
                obj.data.update()
                for prop in (
                    "vc_levels_offset","vc_levels_gain","vc_hue","vc_saturation","vc_value",
                    "vc_brightness","vc_contrast","vc_gamma","vc_exposure","vc_posterize","vc_vibrant","vc_noise",
                    "vc_shadows_balance","vc_midtones_balance","vc_highlights_balance",
                    "vc_curve_shadows","vc_curve_midtones","vc_curve_highlights",
                    "vc_channel_r","vc_channel_g","vc_channel_b"
                ):
                    obj.keyframe_insert(prop, frame=frame)
        return {'FINISHED'}

class VCRemoveFrame(bpy.types.Operator):
    bl_idname = "object.vc_remove_frame"
    bl_label = "Remove Frame"
    def execute(self, context):
        frame = context.scene.frame_current
        for obj in context.selected_objects:
            if obj.vc_animate_enabled:
                attr = obj.data.color_attributes.get("Attribute")
                if not attr:
                    continue
                for i in range(len(attr.data)):
                    for ch in range(4):
                        try:
                            obj.data.keyframe_delete(
                                f'color_attributes["Attribute"].data[{i}].color',
                                frame=frame, index=ch
                            )
                        except RuntimeError:
                            pass
                for prop in (
                    "vc_levels_offset","vc_levels_gain","vc_hue","vc_saturation","vc_value",
                    "vc_brightness","vc_contrast","vc_gamma","vc_exposure","vc_posterize","vc_vibrant","vc_noise",
                    "vc_shadows_balance","vc_midtones_balance","vc_highlights_balance",
                    "vc_curve_shadows","vc_curve_midtones","vc_curve_highlights",
                    "vc_channel_r","vc_channel_g","vc_channel_b"
                ):
                    try:
                        obj.keyframe_delete(prop, frame=frame)
                    except RuntimeError:
                        pass
                obj.data.update()
        context.scene.frame_set(frame)
        return {'FINISHED'}

class VCExportAnimation(bpy.types.Operator, ExportHelper):
    bl_idname = "object.vc_export_animation"
    bl_label = "Export Animation Data"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})
    def execute(self, context):
        obj = context.object
        context.scene.frame_set(0)
        data = [e for (name, _), lst in vertex_data_store.items() if name == obj.name for e in lst]
        if not data:
            self.report({'WARNING'}, f"No data for {obj.name}")
            return {'CANCELLED'}
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=2)
            self.report({'INFO'}, f"Exported to {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export: {e}")
        return {'FINISHED'}

class VCLoadAnimatedData(bpy.types.Operator, ImportHelper):
    bl_idname = "object.vc_load_animated_data"
    bl_label = "Load Animated Data"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})
    def execute(self, context):
        scene = context.scene
        obj = context.object
        scene.frame_set(0)
        try:
            with open(self.filepath) as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read: {e}")
            return {'CANCELLED'}
        frames = defaultdict(list)
        for e in data:
            if e['object'] == obj.name:
                frames[e['frame']].append(e)
        orig = scene.frame_current
        for frm, lst in sorted(frames.items()):
            scene.frame_set(frm)
            attr = ensure_vertex_color_attribute(obj)
            for e in lst:
                i, col = e['loop_index'], e['color']
                attr.data[i].color = col
                for ch in range(4):
                    obj.data.keyframe_insert(f'color_attributes["Attribute"].data[{i}].color',
                                             frame=frm, index=ch)
            obj.data.update()
        scene.frame_set(orig)
        self.report({'INFO'}, "Animation loaded")
        return {'FINISHED'}
    
class VCShowGradient(bpy.types.Operator):
    bl_idname = "object.vc_show_gradient"
    bl_label = "Gradient Settings"
    bl_description = "Mostrar u ocultar controles de gradiente"

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                if obj.show_vc_gradient:
                    # Si estaba activado y ahora se desactiva, restaurar
                    backup = vertex_backup_store.get(obj.name)
                    if backup:
                        attr = ensure_vertex_color_attribute(obj)
                        for i, color in enumerate(backup):
                            attr.data[i].color = color[:]
                        obj.data.update()
                        vertex_backup_store.pop(obj.name, None)
                    obj.show_vc_gradient = False
                else:
                    # Si se va a activar, hacer respaldo
                    attr = ensure_vertex_color_attribute(obj)
                    vertex_backup_store[obj.name] = [v.color[:] for v in attr.data]
                    obj.show_vc_gradient = True
        return {'FINISHED'}


class VCGradientColor(bpy.types.Operator):
    bl_idname = "object.vc_set_gradient"
    bl_label = "Gradient Color"
    bl_description = "Aplica un gradiente multicolor según la orientación seleccionada"

    def execute(self, context):
        import mathutils
        obj = context.object
        mesh = obj.data
        attr = ensure_vertex_color_attribute(obj)

        axis = obj.vc_gradient_axis
        invert = axis.startswith('-')
        axis_key = axis[1:] if invert else axis  # 'X','Y','Z' or 'RADIAL'

        # Verificar que haya al menos dos paradas de color
        if len(obj.vc_gradient_stops) < 2:
            self.report({'WARNING'}, "Se necesitan al menos dos paradas de color para el gradiente.")
            return {'CANCELLED'}

        # Ordenar las paradas por posición (factor)
        stops = sorted(obj.vc_gradient_stops, key=lambda s: s.factor)

        def lerp_color(t):
            if invert:
                t = 1.0 - t
            for i in range(len(stops) - 1):
                f0 = stops[i].factor
                f1 = stops[i + 1].factor
                if f0 <= t <= f1:
                    local_t = (t - f0) / (f1 - f0) if f1 != f0 else 0.0
                    c0 = stops[i].color
                    c1 = stops[i + 1].color
                    return (
                        c0[0] + local_t * (c1[0] - c0[0]),
                        c0[1] + local_t * (c1[1] - c0[1]),
                        c0[2] + local_t * (c1[2] - c0[2]),
                        1.0
                    )
            # Fuera de rango
            if t < stops[0].factor:
                c = stops[0].color
            else:
                c = stops[-1].color
            return (c[0], c[1], c[2], 1.0)

        # Obtener coordenadas mundiales por vértice
        coords = [obj.matrix_world @ mesh.vertices[loop.vertex_index].co for loop in mesh.loops]

        if axis_key in {'X', 'Y', 'Z'}:
            idx = 'XYZ'.index(axis_key)
            vals = [co[idx] for co in coords]
            mn, mx = min(vals), max(vals)
            span = mx - mn if mx != mn else 1.0

            for loop in mesh.loops:
                co = obj.matrix_world @ mesh.vertices[loop.vertex_index].co
                t = (co[idx] - mn) / span
                attr.data[loop.index].color = lerp_color(t)

        else:  # RADIAL
            bbox = [obj.matrix_world @ v.co for v in mesh.vertices]
            center = sum(bbox, mathutils.Vector()) / len(bbox)
            dists = [(co - center).length for co in bbox]
            mn, mx = min(dists), max(dists)
            span = mx - mn if mx != mn else 1.0

            for loop in mesh.loops:
                co = obj.matrix_world @ mesh.vertices[loop.vertex_index].co
                d = (co - center).length
                t = (d - mn) / span
                attr.data[loop.index].color = lerp_color(t)

        mesh.update()
        return {'FINISHED'}

    
class VCGradientStop(bpy.types.PropertyGroup):
    factor: bpy.props.FloatProperty(
        name="Position",
        description="Ubicación de la parada en el gradiente (0.0 a 1.0)",
        min=0.0, max=1.0, default=0.5,
        update=vc_gradient_live_update
    )
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR', size=3,
        min=0.0, max=1.0, default=(1.0, 1.0, 1.0),
        update=vc_gradient_live_update
    )


# -----------------------------
# Operadores para añadir/quitar paradas
# -----------------------------
class VCAddGradientStop(bpy.types.Operator):
    bl_idname = "object.vc_add_gradient_stop"
    bl_label = "Add Color Stop"

    def execute(self, context):
        obj = context.object
        stops = obj.vc_gradient_stops
        # Añadimos con un color por defecto (por ej. copia de la última existente)
        default_color = stops[-1].color if stops else (1.0,1.0,1.0)
        stops.add().color = default_color

        # Recalcular factores equidistantes
        N = len(stops)
        if N > 1:
            for idx, stop in enumerate(stops):
                stop.factor = idx / (N - 1)

        # Dejar seleccionada la última
        obj.vc_gradient_stop_index = N - 1
        vc_gradient_live_update(self, context)
        return {'FINISHED'}

class VCRemoveGradientStop(bpy.types.Operator):
    bl_idname = "object.vc_remove_gradient_stop"
    bl_label = "Remove Color Stop"

    def execute(self, context):
        obj = context.object
        stops = obj.vc_gradient_stops
        idx = obj.vc_gradient_stop_index
        stops.remove(idx)

        # Recalcular factores equidistantes
        N = len(stops)
        if N > 1:
            for i, stop in enumerate(stops):
                stop.factor = i / (N - 1)

        # Ajustar índice
        obj.vc_gradient_stop_index = min(idx, N - 1)
        vc_gradient_live_update(self, context)
        return {'FINISHED'}
    
class VCApplyGradient(bpy.types.Operator):
    bl_idname = "object.vc_apply_gradient"
    bl_label = "Apply"
    bl_description = "Guardar colores de vértice y cerrar Gradient Settings"

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.show_vc_gradient:
                # Eliminar backup una vez aplicada
                vertex_backup_store.pop(obj.name, None)
                obj.show_vc_gradient = False
        return {'FINISHED'}

class VCCancelGradient(bpy.types.Operator):
    bl_idname = "object.vc_cancel_gradient"
    bl_label = "Cancel"
    bl_description = "Restaurar colores originales y cerrar Gradient Settings"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.show_vc_gradient:
                backup = vertex_backup_store.get(obj.name)
                if backup is not None:
                    attr = ensure_vertex_color_attribute(obj)
                    for i, color in enumerate(backup):
                        attr.data[i].color = color[:]
                    obj.data.update()
                obj.show_vc_gradient = False
                vertex_backup_store.pop(obj.name, None)
        return {'FINISHED'}
    
_vc_gradient_copy_data = {}

class VCCopyGradientValues(bpy.types.Operator):
    bl_idname = "object.vc_copy_values"
    bl_label = "Copy Values"
    bl_description = "Copia las paradas de gradiente y el modo actual"

    def execute(self, context):
        obj = context.object
        # Guardamos axis + stops en el dict global
        _vc_gradient_copy_data['axis'] = obj.vc_gradient_axis
        _vc_gradient_copy_data['stops'] = [
            (stop.factor, tuple(stop.color)) for stop in obj.vc_gradient_stops
        ]
        self.report({'INFO'}, "Gradient values copied")
        return {'FINISHED'}


class VCPasteGradientValues(bpy.types.Operator):
    bl_idname = "object.vc_paste_values"
    bl_label = "Paste Values"
    bl_description = "Pega las paradas de gradiente y el modo copiado"

    def execute(self, context):
        obj = context.object
        # Recuperamos del dict global
        data = _vc_gradient_copy_data
        if 'axis' not in data or 'stops' not in data:
            self.report({'WARNING'}, "No hay valores copiados")
            return {'CANCELLED'}

        # Asignamos axis
        obj.vc_gradient_axis = data['axis']

        # Reemplazamos paradas
        stops = obj.vc_gradient_stops
        stops.clear()
        for factor, color in data['stops']:
            new = stops.add()
            new.factor = factor
            new.color = color

        # Ajustamos índice y forzamos live update
        obj.vc_gradient_stop_index = len(stops) - 1
        vc_gradient_live_update(self, context)

        self.report({'INFO'}, "Gradient values pasted")
        return {'FINISHED'}
    
class VCSaveGradientPreset(bpy.types.Operator):
    bl_idname = "object.vc_save_preset"
    bl_label = "Save Preset"
    bl_description = "Guarda el preset de gradiente bajo un nombre"
    preset_name: bpy.props.StringProperty(name="Preset Name", default="Preset")

    def invoke(self, context, event):
        # Guarda valores actuales antes de mostrar diálogo
        obj = context.object
        _vc_gradient_copy_data['axis'] = obj.vc_gradient_axis
        _vc_gradient_copy_data['stops'] = [
            (stop.factor, tuple(stop.color)) for stop in obj.vc_gradient_stops
        ]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            self.report({'WARNING'}, "El nombre del preset no puede estar vacío")
            return {'CANCELLED'}
        # Guarda en el dict global
        _vc_gradient_presets[name] = {
            'axis': _vc_gradient_copy_data['axis'],
            'stops': list(_vc_gradient_copy_data['stops'])
        }
        # Añade ítem a la colección de la escena
        scene = context.scene
        item = scene.vc_gradient_presets.add()
        item.name = name
        scene.vc_gradient_preset_index = len(scene.vc_gradient_presets) - 1
        self.report({'INFO'}, f"Preset '{name}' guardado y añadido a la lista")
        return {'FINISHED'}

class VCApplyGradientPreset(bpy.types.Operator):
    bl_idname = "object.vc_apply_preset"
    bl_label = "Apply Preset"
    bl_description = "Apply the selected gradient preset from the list"

    def execute(self, context):
        scene = context.scene
        idx = scene.vc_gradient_preset_index
        if not scene.vc_gradient_presets:
            self.report({'WARNING'}, "No presets available to apply")
            return {'CANCELLED'}
        name = scene.vc_gradient_presets[idx].name
        data = _vc_gradient_presets.get(name)
        if not data:
            self.report({'WARNING'}, f"Preset '{name}' not found in internal store")
            return {'CANCELLED'}
        obj = context.object
        obj.vc_gradient_axis = data['axis']
        stops = obj.vc_gradient_stops
        stops.clear()
        for f, color in data['stops']:
            new = stops.add()
            new.factor = f
            new.color = color
        obj.vc_gradient_stop_index = len(stops) - 1
        vc_gradient_live_update(self, context)
        return {'FINISHED'}
    
# --- Data structure for presets in Scene ---
class VCGradientPresetItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Preset Name")

# --- UIList to show presets ---
class VCGradientPresetList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        # data is the owner (scene), item is the VCGradientPresetItem
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='PRESET')

# --- Panel update: include UIList ---
def draw_preset_ui(self, context):
    layout = self.layout
    scene = context.scene
    row = layout.row()
    row.template_list(
        "VCGradientPresetList",  # UIList class
        "",                     # list identifier
        scene,                   # data
        "vc_gradient_presets",  # collection
        scene,                   # data
        "vc_gradient_preset_index",  # active index
        rows=4
    )
    col = row.column(align=True)
    col.operator("object.vc_save_preset", icon='ADD', text="")
    col.operator("object.vc_delete_preset", icon='REMOVE', text="")
    if scene.vc_gradient_presets:
        layout.operator("object.vc_apply_preset", text="Apply Selected")

# --- Delete Preset Operator ---
class VCDeleteGradientPreset(bpy.types.Operator):
    bl_idname = "object.vc_delete_preset"
    bl_label = "Delete Preset"

    @classmethod
    def poll(cls, context):
        return context.scene.vc_gradient_presets

    def execute(self, context):
        scene = context.scene
        idx = scene.vc_gradient_preset_index
        name = scene.vc_gradient_presets[idx].name
        # remove from dict storing presets
        if name in _vc_gradient_presets:
            del _vc_gradient_presets[name]
        # remove from collection
        scene.vc_gradient_presets.remove(idx)
        scene.vc_gradient_preset_index = min(idx, len(scene.vc_gradient_presets)-1)
        self.report({'INFO'}, f"Preset '{name}' deleted")
        return {'FINISHED'}
    
class VCTogglePresetList(bpy.types.Operator):
    bl_idname = "object.vc_toggle_preset_list"
    bl_label = "Toggle Preset List"
    bl_description = "Show or hide the gradient preset list"

    def execute(self, context):
        scene = context.scene
        scene.show_vc_preset_list = not scene.show_vc_preset_list
        return {'FINISHED'}
    
class VCExportJson(bpy.types.Operator, ExportHelper):
    bl_idname = "object.vc_export_json"
    bl_label = "Export Gradient JSON"
    bl_description = "Exporta axis, stops y todos los presets a un .json"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        obj = context.object
        scene = context.scene

        data = {
            'axis': obj.vc_gradient_axis,
            'stops': [(s.factor, tuple(s.color)) for s in obj.vc_gradient_stops],
            'presets': {
                name: {
                    'axis': info['axis'],
                    'stops': info['stops']
                } for name, info in _vc_gradient_presets.items()
            }
        }
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=2)
            self.report({'INFO'}, f"Exported gradient data to {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Error exporting JSON: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


class VCImportJson(bpy.types.Operator, ImportHelper):
    bl_idname = "object.vc_import_json"
    bl_label = "Import Gradient JSON"
    bl_description = "Importa axis, stops y todos los presets desde un .json"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        obj = context.object
        scene = context.scene

        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Error reading JSON: {e}")
            return {'CANCELLED'}

        # Import axis & stops
        obj.vc_gradient_axis = data.get('axis', obj.vc_gradient_axis)
        obj.vc_gradient_stops.clear()
        for factor, color in data.get('stops', []):
            st = obj.vc_gradient_stops.add()
            st.factor = factor
            st.color = color

        # Import presets
        _vc_gradient_presets.clear()
        scene.vc_gradient_presets.clear()
        for name, info in data.get('presets', {}).items():
            _vc_gradient_presets[name] = {
                'axis': info['axis'],
                'stops': info['stops']
            }
            item = scene.vc_gradient_presets.add()
            item.name = name

        self.report({'INFO'}, f"Imported gradient data from {self.filepath}")
        return {'FINISHED'}
    
class VCGrayscale(bpy.types.Operator):
    bl_idname = "object.vc_grayscale"
    bl_label = "Grayscale Vertex Colors"
    def execute(self, context):
        obj = context.object
        attr = ensure_vertex_color_attribute(obj)
        for lc in attr.data:
            r, g, b, a = lc.color
            gray = (r + g + b) / 3.0
            lc.color = (gray, gray, gray, a)
        obj.data.update()
        return {'FINISHED'}

class VCSepia(bpy.types.Operator):
    bl_idname = "object.vc_sepia"
    bl_label = "Sepia Vertex Colors"
    def execute(self, context):
        obj = context.object
        attr = ensure_vertex_color_attribute(obj)
        for lc in attr.data:
            r, g, b, a = lc.color
            tr = min(0.393*r + 0.769*g + 0.189*b, 1.0)
            tg = min(0.349*r + 0.686*g + 0.168*b, 1.0)
            tb = min(0.272*r + 0.534*g + 0.131*b, 1.0)
            lc.color = (tr, tg, tb, a)
        obj.data.update()
        return {'FINISHED'}

class VCCartoon(bpy.types.Operator):
    bl_idname = "object.vc_cartoon"
    bl_label = "Cartoon Vertex Colors"
    def execute(self, context):
        obj = context.object
        attr = ensure_vertex_color_attribute(obj)
        # Posteriza en 4 niveles por canal
        levels = 4
        for lc in attr.data:
            r, g, b, a = lc.color
            lc.color = (
                round(r * (levels-1)) / (levels-1),
                round(g * (levels-1)) / (levels-1),
                round(b * (levels-1)) / (levels-1),
                a
            )
        obj.data.update()
        return {'FINISHED'}

class VCHot(bpy.types.Operator):
    bl_idname = "object.vc_hot"
    bl_label = "Hot Map Vertex Colors"
    def execute(self, context):
        import math
        obj = context.object
        attr = ensure_vertex_color_attribute(obj)
        for lc in attr.data:
            r, g, b, a = lc.color
            # Escala la luminancia a rojo–amarillo–blanco
            lum = (r + g + b) / 3.0
            if lum < 0.5:
                t = lum * 2
                color = (t, 0, 0)
            else:
                t = (lum - 0.5) * 2
                color = (1.0, t, 0)
            lc.color = (*color, a)
        obj.data.update()
        return {'FINISHED'}

class VCCold(bpy.types.Operator):
    bl_idname = "object.vc_cold"
    bl_label = "Cold Map Vertex Colors"
    def execute(self, context):
        import math
        obj = context.object
        attr = ensure_vertex_color_attribute(obj)
        for lc in attr.data:
            r, g, b, a = lc.color
            lum = (r + g + b) / 3.0
            if lum < 0.5:
                t = lum * 2
                color = (0, 0, t)
            else:
                t = (lum - 0.5) * 2
                color = (0, 1.0 - t, 1.0)
            lc.color = (*color, a)
        obj.data.update()
        return {'FINISHED'}



# -----------------------------
# Registro de clases y props
# -----------------------------
classes = [
    VCGradientStop,
    VCAddGradientStop,
    VCRemoveGradientStop,
    VCShowGradient,
    VCGradientColor,
    VertexColorPanel,
    VCInvert, VCSmooth, VCDirty,
    VCSetColor, VCSampleColor,
    VCShowFineTune, VCAcceptChanges, VCCancelChanges, VCResetValues,
    VCSaveValues, VCApplySavedValues,
    VCToggleAnimate, VCStoreData, VCApplyAnimate, VCCancelAnimate,
    VCAddFrame, VCRemoveFrame, VCExportAnimation, VCLoadAnimatedData,
    VCSharpColor, VCCleanColor,VCExportJson,VCImportJson, VCGrayscale, VCSepia,
    VCCartoon, VCHot, VCCold,
]

# ------------------------------------------------------------------
# Props existentes (con live_update genérico)
# ------------------------------------------------------------------
prop_args = {
    "vc_levels_offset":    dict(name="Offset",      min=-1.0,   max=1.0,   default=0.0, update=live_update),
    "vc_levels_gain":      dict(name="Gain",        min=0.0,    max=10.0,  default=1.0, update=live_update),
    "vc_hue":              dict(name="Hue",         min=0.0,    max=1.0,   default=0.5, update=live_update),
    "vc_saturation":       dict(name="Saturation",  min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_value":            dict(name="Value",       min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_brightness":       dict(name="Brightness",  min=-100.0, max=100.0, default=0.0, update=live_update),
    "vc_contrast":         dict(name="Contrast",    min=-100.0, max=100.0, default=0.0, update=live_update),
}

new_prop_args = {
    "vc_gamma":     dict(name="Gamma",       min=0.1,    max=5.0,   default=1.0, update=live_update),
    "vc_exposure":  dict(name="Exposure",    min=-5.0,   max=5.0,   default=0.0, update=live_update),
    "vc_posterize": dict(name="Posterize",   min=1,      max=8,     default=0.0, update=live_update),
    "vc_vibrant":   dict(name="Vibrant",     min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_noise":     dict(name="Noise",       min=0.0,    max=1.0,   default=0.0, update=live_update),
    "vc_shadows_balance":    dict(name="Shadows",      min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_midtones_balance":   dict(name="Midtones",    min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_highlights_balance": dict(name="Highlights",  min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_curve_shadows":      dict(name="Curve Shadows",   min=0.0, max=1.0, default=0.0, update=live_update),
    "vc_curve_midtones":     dict(name="Curve Midtones",  min=0.0, max=1.0, default=0.5, update=live_update),
    "vc_curve_highlights":   dict(name="Curve Highlights",min=0.0, max=1.0, default=1.0, update=live_update),
    # Channel toggles
    "vc_channel_r": dict(name="R Channel", default=False, update=live_update),
    "vc_channel_g": dict(name="G Channel", default=False, update=live_update),
    "vc_channel_b": dict(name="B Channel", default=False, update=live_update),
}

# -----------------------------
# Registro de clases y props
# -----------------------------
classes = [
    # Gradiente
    VCGradientStop,
    VCAddGradientStop,
    VCRemoveGradientStop,
    VCShowGradient,
    VCGradientColor,
    VCApplyGradient,
    VCCancelGradient,
    VCCopyGradientValues,
    VCPasteGradientValues,
    VCSaveGradientPreset,
    VCApplyGradientPreset,
    # UI Presets
    VCGradientPresetItem,
    VCGradientPresetList,
    VCDeleteGradientPreset,
    # Toggle Preset List
    VCTogglePresetList,
    # Panel y demás operadores existentes
    VertexColorPanel,
    VCInvert, VCSmooth, VCDirty,
    VCSetColor, VCSampleColor,
    VCShowFineTune, VCAcceptChanges, VCCancelChanges, VCResetValues,
    VCSaveValues, VCApplySavedValues,
    VCToggleAnimate, VCStoreData, VCApplyAnimate, VCCancelAnimate,
    VCAddFrame, VCRemoveFrame, VCExportAnimation, VCLoadAnimatedData,
    VCSharpColor, VCCleanColor,VCExportJson,VCImportJson, VCGrayscale, VCSepia,
    VCCartoon, VCHot, VCCold,
]

# ------------------------------------------------------------------
# Props existentes (con live_update genérico)
# ------------------------------------------------------------------
prop_args = {
    "vc_levels_offset":    dict(name="Offset",      min=-1.0,   max=1.0,   default=0.0, update=live_update),
    "vc_levels_gain":      dict(name="Gain",        min=0.0,    max=10.0,  default=1.0, update=live_update),
    "vc_hue":              dict(name="Hue",         min=0.0,    max=1.0,   default=0.5, update=live_update),
    "vc_saturation":       dict(name="Saturation",  min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_value":            dict(name="Value",       min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_brightness":       dict(name="Brightness",  min=-100.0, max=100.0, default=0.0, update=live_update),
    "vc_contrast":         dict(name="Contrast",    min=-100.0, max=100.0, default=0.0, update=live_update),
}

new_prop_args = {
    "vc_gamma":     dict(name="Gamma",       min=0.1,    max=5.0,   default=1.0, update=live_update),
    "vc_exposure":  dict(name="Exposure",    min=-5.0,   max=5.0,   default=0.0, update=live_update),
    "vc_posterize": dict(name="Posterize",   min=1,      max=8,     default=0.0, update=live_update),
    "vc_vibrant":   dict(name="Vibrant",     min=0.0,    max=2.0,   default=1.0, update=live_update),
    "vc_noise":     dict(name="Noise",       min=0.0,    max=1.0,   default=0.0, update=live_update),
    "vc_shadows_balance":    dict(name="Shadows",      min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_midtones_balance":   dict(name="Midtones",    min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_highlights_balance": dict(name="Highlights",  min=-1.0, max=1.0, default=0.0, update=live_update),
    "vc_curve_shadows":      dict(name="Curve Shadows",   min=0.0, max=1.0, default=0.0, update=live_update),
    "vc_curve_midtones":     dict(name="Curve Midtones",  min=0.0, max=1.0, default=0.5, update=live_update),
    "vc_curve_highlights":   dict(name="Curve Highlights",min=0.0, max=1.0, default=1.0, update=live_update),
    # Channel toggles
    "vc_channel_r": dict(name="R Channel", default=False, update=live_update),
    "vc_channel_g": dict(name="G Channel", default=False, update=live_update),
    "vc_channel_b": dict(name="B Channel", default=False, update=live_update),
}

# ------------------------------------------------------------------
# Registro / Unregistro
# ------------------------------------------------------------------
def register():
    # Clases a registrar
    for cls in classes:
        bpy.utils.register_class(cls)

    # Props genéricas
    for name, kwargs in prop_args.items():
        setattr(bpy.types.Object, name, bpy.props.FloatProperty(**kwargs))
    for name, kwargs in new_prop_args.items():
        prop = bpy.props.BoolProperty(**kwargs) if name.startswith("vc_channel_") else bpy.props.FloatProperty(**kwargs)
        setattr(bpy.types.Object, name, prop)

    # UI genérica
    setattr(bpy.types.Object, "show_vc_fine_tune", bpy.props.BoolProperty(default=False))
    setattr(bpy.types.Object, "show_vc_animate", bpy.props.BoolProperty(default=False))
    setattr(bpy.types.Object, "vc_animate_enabled", bpy.props.BoolProperty(default=False))
    setattr(bpy.types.Object, "vc_sample_color_picker",
            bpy.props.FloatVectorProperty(name="Sample Color", subtype='COLOR', size=3,
                                          min=0.0, max=1.0, default=(1.0,1.0,1.0),
                                          update=sample_update))

    # Props de gradiente
    setattr(bpy.types.Object, "show_vc_gradient",
            bpy.props.BoolProperty(name="Gradient Settings", default=False))
    setattr(bpy.types.Object, "vc_gradient_axis",
            bpy.props.EnumProperty(name="Axis",
                                   items=[('X','X-Axis',''),('-X','-X-Axis',''),
                                          ('Y','Y-Axis',''),('-Y','-Y-Axis',''),
                                          ('Z','Z-Axis',''),('-Z','-Z-Axis',''),
                                          ('RADIAL','Radial','')],
                                   default='X', update=vc_gradient_live_update))

    # Colecciones
    bpy.types.Object.vc_gradient_stops = bpy.props.CollectionProperty(type=VCGradientStop)
    bpy.types.Object.vc_gradient_stop_index = bpy.props.IntProperty(default=0)
    bpy.types.Scene.vc_gradient_presets = bpy.props.CollectionProperty(type=VCGradientPresetItem)
    bpy.types.Scene.vc_gradient_preset_index = bpy.props.IntProperty(default=0)
    bpy.types.Scene.show_vc_preset_list = bpy.props.BoolProperty(
        name="Show Preset List",
        default=False,
        description="Toggle visibility of gradient preset list"
    )

    # Handlers
    bpy.app.handlers.frame_change_post.append(update_vertex_colors_handler)
    bpy.app.handlers.frame_change_post.append(auto_store_data_handler)
    bpy.app.handlers.frame_change_post.append(validate_color_keyframes_handler)
    bpy.context.scene.sync_mode = 'FRAME_DROP'


def unregister():
    # Remove handlers
    for h in (update_vertex_colors_handler, auto_store_data_handler, validate_color_keyframes_handler):
        if h in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(h)

    # Unregister classes (orden inverso)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    # Remove props genéricas
    for name in list(prop_args.keys()) + list(new_prop_args.keys()):
        delattr(bpy.types.Object, name)
    for name in ("show_vc_fine_tune", "show_vc_animate", "vc_animate_enabled", "vc_sample_color_picker"):   
        delattr(bpy.types.Object, name)

    # Remove props de gradiente
    delattr(bpy.types.Object, "show_vc_gradient")
    delattr(bpy.types.Object, "vc_gradient_axis")

    # Remove colecciones
    del bpy.types.Object.vc_gradient_stops
    del bpy.types.Object.vc_gradient_stop_index
    del bpy.types.Scene.vc_gradient_presets
    del bpy.types.Scene.vc_gradient_preset_index
    del bpy.types.Scene.show_vc_preset_list

if __name__ == "__main__":
    register()
