import bpy
import random
import json
from bpy_extras.io_utils import ExportHelper, ImportHelper

# ------------------------------
# Custom Color Items & Presets
# ------------------------------
class VLPColorItem(bpy.types.PropertyGroup):
    """Individual color entry for presets and custom colors."""
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0, max=1.0, size=4
    )

class VLPPresetItem(bpy.types.PropertyGroup):
    """Stores a preset: name, list of colors, seed, and mode."""
    name: bpy.props.StringProperty(name="Preset Name", default="Preset")
    colors: bpy.props.CollectionProperty(type=VLPColorItem)
    index: bpy.props.IntProperty(default=0)
    seed_custom: bpy.props.IntProperty(
        name="Seed",
        description="Seed value saved for this preset",
        default=0,
        min=0
    )
    mode: bpy.props.StringProperty(
        name="Mode",
        description="Mode in which this preset was saved",
        default='SOLID'
    )

# ------------------------------
# Callback to update when seeds change
# ------------------------------
def update_seed_callback(self, context):
    """Runs when any seed is modified: re-applies colors if needed."""
    scene = context.scene
    props = scene.vlp_scene

    if props.color_mode not in {'SOLID', 'DIFFUSE', 'CUSTOM'}:
        return
    if context.mode == 'EDIT_MESH':
        return

    selected_objs = [o for o in context.selected_objects if o.type == 'MESH']
    active_obj = context.view_layer.objects.active

    if not selected_objs:
        return

    bpy.ops.vlp.randomize_vertex_colors()

    # Restore selection and active object
    for o in context.scene.objects:
        o.select_set(False)
    for o in selected_objs:
        o.select_set(True)
    if active_obj:
        context.view_layer.objects.active = active_obj

# ------------------------------
# Main scene properties for the add-on
# ------------------------------
class VLPSceneProps(bpy.types.PropertyGroup):
    """Holds all tool properties: mode, seeds, colors, and presets."""
    color_mode: bpy.props.EnumProperty(
        name="Color Mode",
        items=[
            ('SOLID','Solid Random','One random color per face'),
            ('DIFFUSE','Diffuse Random','Random color per vertex'),
            ('UNINIT','Uninitialized','Create layer without initializing'),
            ('CUSTOM','Custom','Use user-defined colors')
        ],
        default='SOLID'
    )
    apply_to_all: bpy.props.BoolProperty(
        name="Apply to All",
        description="If unchecked, only affects selected objects",
        default=False
    )
    smooth: bpy.props.BoolProperty(
        name="Smooth",
        description="Smooth vertex colors after application",
        default=False
    )

    seed_solid: bpy.props.IntProperty(
        name="Solid Seed",
        description="Seed for Solid Random mode",
        default=0, min=0, update=update_seed_callback
    )
    seed_diffuse: bpy.props.IntProperty(
        name="Diffuse Seed",
        description="Seed for Diffuse Random mode",
        default=0, min=0, update=update_seed_callback
    )
    seed_custom: bpy.props.IntProperty(
        name="Custom Seed",
        description="Seed for selecting custom colors",
        default=0, min=0, update=update_seed_callback
    )

    custom_colors: bpy.props.CollectionProperty(type=VLPColorItem)
    custom_index: bpy.props.IntProperty(default=0)
    presets: bpy.props.CollectionProperty(type=VLPPresetItem)
    preset_index: bpy.props.IntProperty(default=0)
    show_presets: bpy.props.BoolProperty(default=False)

    attribute_name: bpy.props.StringProperty(
        name="Layer Name",
        description="Name of the color attribute layer to create",
        default="VLP_Random"
    )

# ------------------------------
# UIList to display custom color swatches
# ------------------------------
class VLP_UL_custom_colors(bpy.types.UIList):
    """UIList that shows swatches of custom colors."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "color", text="", emboss=True)

# ------------------------------
# Operators for custom color management
# ------------------------------
class VLP_OT_add_custom_color(bpy.types.Operator):
    """Add a new color to the custom palette."""
    bl_idname = "vlp.add_custom_color"
    bl_label = "Add Color"
    def execute(self, context):
        props = context.scene.vlp_scene
        props.custom_colors.add()
        props.custom_index = len(props.custom_colors) - 1
        return {'FINISHED'}

class VLP_OT_remove_custom_color(bpy.types.Operator):
    """Remove the selected color from the custom palette."""
    bl_idname = "vlp.remove_custom_color"
    bl_label = "Remove Color"
    def execute(self, context):
        props = context.scene.vlp_scene
        if props.custom_colors:
            props.custom_colors.remove(props.custom_index)
            props.custom_index = max(0, props.custom_index - 1)
        return {'FINISHED'}

class VLP_OT_reset_custom_colors(bpy.types.Operator):
    """Reset the custom palette by clearing all colors."""
    bl_idname = "vlp.reset_custom_colors"
    bl_label = "Reset Colors"
    def execute(self, context):
        props = context.scene.vlp_scene
        props.custom_colors.clear()
        props.custom_index = 0
        return {'FINISHED'}

# ------------------------------
# Operators for presets
# ------------------------------
class VLP_OT_save_preset(bpy.types.Operator):
    """Save the current state (mode and colors/seed) as a new preset."""
    bl_idname = "vlp.save_preset"
    bl_label = "Save Preset"
    def execute(self, context):
        props = context.scene.vlp_scene
        mode = props.color_mode

        preset = props.presets.add()
        preset.name = f"Preset {len(props.presets)}"
        preset.mode = mode

        if mode == 'CUSTOM':
            for col in props.custom_colors:
                item = preset.colors.add()
                item.color = col.color
            preset.seed_custom = props.seed_custom
        else:
            preset.seed_custom = props.seed_solid if mode == 'SOLID' else props.seed_diffuse

        return {'FINISHED'}

class VLP_OT_toggle_presets(bpy.types.Operator):
    """Toggle display of saved preset details."""
    bl_idname = "vlp.toggle_presets"
    bl_label = "Show Details"
    def execute(self, context):
        props = context.scene.vlp_scene
        props.show_presets = not props.show_presets
        return {'FINISHED'}

class VLP_OT_apply_preset(bpy.types.Operator):
    """Apply the selected preset to the mesh object(s)."""
    bl_idname = "vlp.apply_preset"
    bl_label = "Apply Preset"

    def execute(self, context):
        props = context.scene.vlp_scene
        preset = props.presets[props.preset_index]
        saved_mode = preset.mode

        props.color_mode = saved_mode

        if saved_mode == 'CUSTOM':
            props.custom_colors.clear()
            for col in preset.colors:
                item = props.custom_colors.add()
                item.color = col.color
            props.seed_custom = preset.seed_custom
        elif saved_mode == 'SOLID':
            props.seed_solid = preset.seed_custom
        elif saved_mode == 'DIFFUSE':
            props.seed_diffuse = preset.seed_custom

        sel_prev = [o for o in context.selected_objects if o.type == 'MESH']
        if props.apply_to_all:
            targets = [o for o in context.scene.objects if o.type == 'MESH']
        else:
            targets = sel_prev
        if not targets:
            self.report({'WARNING'}, "No mesh objects selected to apply the preset")
            return {'CANCELLED'}
        for o in context.scene.objects:
            o.select_set(False)
        for o in targets:
            o.select_set(True)
        context.view_layer.objects.active = targets[0]

        bpy.ops.vlp.randomize_vertex_colors()
        return {'FINISHED'}

class VLP_OT_delete_preset(bpy.types.Operator):
    """Delete the currently selected preset."""
    bl_idname = "vlp.delete_preset"
    bl_label = "Delete Preset"
    def execute(self, context):
        props = context.scene.vlp_scene
        idx = props.preset_index
        if props.presets:
            props.presets.remove(idx)
            props.preset_index = max(0, idx - 1)
        return {'FINISHED'}

# ------------------------------
# Export Presets to JSON
# ------------------------------
class VLP_OT_export_presets(bpy.types.Operator, ExportHelper):
    """Export all saved presets to a JSON file"""
    bl_idname = "vlp.export_presets"
    bl_label = "Export Presets"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={'HIDDEN'},
    )

    def execute(self, context):
        props = context.scene.vlp_scene
        data = []
        for preset in props.presets:
            entry = {
                "name": preset.name,
                "mode": preset.mode,
                "seed": preset.seed_custom,
                "colors": [list(ci.color) for ci in preset.colors]
            }
            data.append(entry)
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.report({'INFO'}, f"Exported {len(data)} presets to {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export presets: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

# ------------------------------
# Import Presets from JSON
# ------------------------------
class VLP_OT_import_presets(bpy.types.Operator, ImportHelper):
    """Import presets from a JSON file"""
    bl_idname = "vlp.import_presets"
    bl_label = "Import Presets"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={'HIDDEN'},
    )

    def execute(self, context):
        props = context.scene.vlp_scene
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read file: {e}")
            return {'CANCELLED'}

        # Clear existing presets
        props.presets.clear()
        for entry in data:
            preset = props.presets.add()
            preset.name = entry.get("name", "Preset")
            preset.mode = entry.get("mode", 'SOLID')
            preset.seed_custom = entry.get("seed", 0)
            preset.colors.clear()
            for col in entry.get("colors", []):
                ci = preset.colors.add()
                ci.color = col if len(col) == 4 else (*col[:3], 1.0)
        props.preset_index = 0
        self.report({'INFO'}, f"Imported {len(props.presets)} presets from {self.filepath}")
        return {'FINISHED'}

# ------------------------------
# Operator to convert color attributes to vertex colors
# ------------------------------
class ConvertToVertexColorOperator(bpy.types.Operator):
    """Convert all color attributes of the active mesh to POINT domain vertex colors."""
    bl_idname = "object.convert_to_vertex_color"
    bl_label = "Convert to Vertex Color"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object first")
            return {'CANCELLED'}

        mesh = obj.data
        color_attrs = mesh.color_attributes

        if not color_attrs:
            self.report({'INFO'}, "No color attributes to convert")
            return {'FINISHED'}

        for idx, attr in enumerate(color_attrs):
            mesh.color_attributes.active_color_index = idx
            try:
                bpy.ops.geometry.color_attribute_convert(
                    domain='POINT',
                    data_type='FLOAT_COLOR'
                )
                self.report({'INFO'},
                            f"Attribute '{attr.name}' converted to POINT, FLOAT_COLOR")
            except Exception as e:
                self.report({'WARNING'},
                            f"Error converting '{attr.name}': {e}")

        return {'FINISHED'}

def menu_convert(self, context):
    """Add the conversion operator to the Object menu."""
    self.layout.operator(ConvertToVertexColorOperator.bl_idname)

# ------------------------------
# Main operator: apply random/custom colors
# ------------------------------
class VLP_OT_randomize_vertex_colors(bpy.types.Operator):
    """Apply random colors (solid, diffuse, or custom) or reset the layer."""
    bl_idname = "vlp.randomize_vertex_colors"
    bl_label = "Apply Random / Custom"

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.scene.objects)

    def execute(self, context):
        props = context.scene.vlp_scene
        mode = props.color_mode
        prev_mode = context.mode

        # Ensure OBJECT mode before editing data
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        target_objs = (
            [o for o in context.scene.objects if o.type == 'MESH']
            if props.apply_to_all
            else [o for o in context.selected_objects if o.type == 'MESH']
        )
        if not target_objs:
            self.report({'WARNING'}, "No mesh objects to process")
            return {'CANCELLED'}

        # Before any mode, delete any existing attribute or layer with the same name
        for obj in target_objs:
            mesh = obj.data
            name = props.attribute_name
            existing_attr = mesh.color_attributes.get(name)
            if existing_attr:
                mesh.color_attributes.remove(existing_attr)
            idx_vc_old = mesh.vertex_colors.find(name)
            if idx_vc_old != -1:
                mesh.vertex_colors.remove(mesh.vertex_colors[idx_vc_old])

        # --- UNINITIALIZED mode: only create the layer without painting ---
        if mode == 'UNINIT':
            for obj in target_objs:
                context.view_layer.objects.active = obj
                obj.select_set(True)
                mesh = obj.data
                name = props.attribute_name
                mesh.vertex_colors.new(name=name)
                idx_vc_new = mesh.vertex_colors.find(name)
                mesh.vertex_colors.active_index = idx_vc_new
                mesh.color_attributes.active_color_index = next(
                    i for i, a in enumerate(mesh.color_attributes) if a.name == name
                )
                try:
                    bpy.ops.geometry.color_attribute_convert(
                        domain='POINT',
                        data_type='FLOAT_COLOR'
                    )
                except Exception as e:
                    self.report({'WARNING'}, f"Could not convert '{name}': {e}")
                obj.select_set(False)
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return {'FINISHED'}

        # --- SOLID, DIFFUSE, or CUSTOM mode: paint vertices ---
        for obj in target_objs:
            if mode == 'SOLID':
                random.seed(props.seed_solid)
            elif mode == 'DIFFUSE':
                random.seed(props.seed_diffuse)
            else:
                random.seed(props.seed_custom)

            context.view_layer.objects.active = obj
            obj.select_set(True)
            mesh = obj.data
            layer_name = props.attribute_name
            idx_vc = mesh.vertex_colors.find(layer_name)
            if idx_vc == -1:
                mesh.vertex_colors.new(name=layer_name)
                idx_vc = mesh.vertex_colors.find(layer_name)
            mesh.vertex_colors.active_index = idx_vc
            vcol = mesh.vertex_colors[idx_vc]

            if mode == 'SOLID':
                for poly in mesh.polygons:
                    color = [random.random() for _ in range(3)] + [1.0]
                    for li in poly.loop_indices:
                        vcol.data[li].color = color

            elif mode == 'DIFFUSE':
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vcol.data[li].color = [random.random() for _ in range(3)] + [1.0]

            else:  # CUSTOM
                if not props.custom_colors:
                    self.report({'WARNING'}, "No custom colors defined")
                    break
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        cc = random.choice(props.custom_colors).color
                        vcol.data[li].color = (*cc[:3], 1.0)

            if props.smooth:
                bpy.ops.object.mode_set(mode='VERTEX_PAINT')
                mesh.vertex_colors.active_index = idx_vc
                bpy.ops.paint.vertex_color_smooth()
                bpy.ops.object.mode_set(mode=prev_mode)

            obj.select_set(False)

        if prev_mode not in {'OBJECT', 'VERTEX_PAINT'}:
            bpy.ops.object.mode_set(mode=prev_mode)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}

# ------------------------------
# UI Panel
# ------------------------------
class VLP_PT_random_panel(bpy.types.Panel):
    bl_label = "Vertex Color Randomizer"
    bl_idname = "VLP_PT_random_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VertexColRefineKit'

    def draw(self, context):
        layout = self.layout
        props = context.scene.vlp_scene

        # Top row: Apply to All, Smooth
        row = layout.row(align=True)
        row.prop(props, 'apply_to_all', text='Apply to All')
        row = layout.row(align=True)
        row.prop(props, 'smooth', text='Smooth')

        # Mode & Layer Name
        layout.prop(props, 'color_mode', text='Mode')
        layout.prop(props, 'attribute_name', text='Layer Name')

        # Seed field
        if props.color_mode == 'SOLID':
            layout.prop(props, 'seed_solid', text='Seed')
        elif props.color_mode == 'DIFFUSE':
            layout.prop(props, 'seed_diffuse', text='Seed')
        elif props.color_mode == 'CUSTOM':
            layout.prop(props, 'seed_custom', text='Seed')

        # Custom mode: show custom palette
        if props.color_mode == 'CUSTOM':
            layout.template_list(
                "VLP_UL_custom_colors", "custom_colors",
                props, "custom_colors",
                props, "custom_index",
                rows=3
            )
            row = layout.row(align=True)
            row.operator('vlp.add_custom_color', icon='ADD', text='Add')
            row.operator('vlp.remove_custom_color', icon='REMOVE', text='Remove')
            layout.operator('vlp.reset_custom_colors', icon='FILE_REFRESH', text='Reset')

        # Preset buttons
        row = layout.row(align=True)
        layout.separator()
        row.operator('vlp.save_preset', text='Save Preset', icon='FILE_TICK')
        row.operator('vlp.delete_preset', text='Delete Preset', icon='TRASH')

        # Show presets details
        layout.operator('vlp.toggle_presets', icon='COLLAPSEMENU', text='Show Details')
        if props.show_presets:
            layout.template_list(
                "UI_UL_list", "presets",
                props, "presets",
                props, "preset_index",
                rows=3
            )
            row = layout.row(align=True)
            row.operator('vlp.apply_preset', text='Apply Preset', icon='PLAY')
            row.operator('vlp.randomize_vertex_colors', text='Apply Random', icon='SHADERFX')
        else:
            layout.operator('vlp.randomize_vertex_colors', text='Apply Random', icon='SHADERFX')

        # Export/Import
        row = layout.row(align=True)
        row.operator('vlp.export_presets', text='Export Preset', icon='EXPORT')
        row.operator('vlp.import_presets', text='Import Preset', icon='IMPORT')


# ------------------------------
# Registration
# ------------------------------
classes = [
    VLPColorItem, VLPPresetItem, VLPSceneProps,
    VLP_UL_custom_colors,
    VLP_OT_add_custom_color, VLP_OT_remove_custom_color, VLP_OT_reset_custom_colors,
    VLP_OT_save_preset, VLP_OT_toggle_presets, VLP_OT_apply_preset, VLP_OT_delete_preset,
    VLP_OT_export_presets, VLP_OT_import_presets,
    ConvertToVertexColorOperator, VLP_OT_randomize_vertex_colors,
    VLP_PT_random_panel
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vlp_scene = bpy.props.PointerProperty(type=VLPSceneProps)
    bpy.types.VIEW3D_MT_object.append(menu_convert)

def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_convert)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.vlp_scene

if __name__ == "__main__":
    register()
