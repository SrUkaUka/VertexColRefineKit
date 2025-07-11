import bpy
import mathutils
from mathutils.kdtree import KDTree
from math import radians

# Properties
class VLPProperties(bpy.types.PropertyGroup):
    """Holds settings for the Vertex Light Painter."""
    emitter: bpy.props.PointerProperty(
        name="Emitter",
        type=bpy.types.Object,
        description="The object that emits light for vertex painting"
    )
    light_type: bpy.props.EnumProperty(
        name="Light Type",
        items=[
            ('SUN', 'Sun', 'Directional infinite light'),
            ('POINT', 'Point', 'Omnidirectional point light'),
            ('SPOT', 'Spot', 'Conical spot light'),
            ('AREA', 'Area', 'Rectangular area light')
        ]
    )
    color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0,
        description="Emission color for painting"
    )
    strength: bpy.props.FloatProperty(
        name="Strength",
        description="Overall intensity multiplier",
        default=1.0,
        min=0.0,
        max=1.0
    )
    range: bpy.props.FloatProperty(
        name="Range",
        description="Max distance for falloff (ignored for SUN)",
        default=5.0,
        min=0.1
    )
    spot_angle: bpy.props.FloatProperty(
        name="Spot Angle",
        description="Half-cone angle in degrees for spot light",
        default=30.0,
        min=1.0,
        max=90.0
    )
    area_x: bpy.props.FloatProperty(
        name="Area Width",
        description="Width of the area light",
        default=2.0,
        min=0.1
    )
    area_y: bpy.props.FloatProperty(
        name="Area Height",
        description="Height of the area light",
        default=2.0,
        min=0.1
    )
    refresh_rate: bpy.props.FloatProperty(
        name="Refresh Rate",
        description="Seconds between updates (higher reduces lag)",
        default=0.2,
        min=0.05
    )
    darken: bpy.props.BoolProperty(
        name="Mix Toward Color",
        description="Fade toward the light color instead of just adding it",
        default=False
    )
    paint_mode: bpy.props.EnumProperty(
        name="Paint Mode",
        items=[
            ('NORMAL', 'Normal', 'Standard additive blend'),
            ('SHARP', 'Sharp', 'Sharper, high-contrast blend'),
            ('DIRTY', 'Dirty', 'Rougher, smudged effect')
        ],
        default='NORMAL',
        description="Choose the painting style"
    )
    attribute_name: bpy.props.StringProperty(
        name="Attribute Name",
        default="VertexLight",
        description="Name of the color attribute to paint"
    )
    running: bpy.props.BoolProperty(
        default=False,
        description="Internal flag: is painting active?"
    )
    has_saved: bpy.props.BoolProperty(
        default=False,
        description="Internal flag: has a save layer been created?"
    )
    last_loc: bpy.props.FloatVectorProperty(
        name="Last Location",
        size=3,
        default=(0.0, 0.0, 0.0),
        description="Last recorded emitter location"
    )
    last_rot: bpy.props.FloatVectorProperty(
        name="Last Rotation",
        size=4,
        default=(1.0, 0.0, 0.0, 0.0),
        description="Last recorded emitter rotation quaternion"
    )

class VLP_OT_paint_modal(bpy.types.Operator):
    """Start the modal vertex-light painting session."""
    bl_idname = "vlp.paint_modal"
    bl_label = "Start Painting"

    _timer = None

    def execute(self, context):
        props = context.scene.vlp_props
        name = props.attribute_name

        if not props.emitter:
            self.report({'ERROR'}, "Select an emitter object first")
            return {'CANCELLED'}

        self.targets = []

        for obj in context.scene.objects:
            if obj.type != 'MESH' or obj == props.emitter:
                continue
            mesh = obj.data

            # Determine live and saved attributes
            if mesh.vertex_colors:
                live = mesh.vertex_colors.get(name) or mesh.vertex_colors.new(name=name)
                saved = (mesh.vertex_colors.get(name + "Save")
                         or mesh.vertex_colors.new(name=name + "Save")) if props.has_saved else None
                use_point = False
            else:
                ca = mesh.color_attributes
                live = ca.get(name) or ca.new(name=name, type='BYTE_COLOR', domain='POINT')
                saved = (ca.get(name + "Save")
                         or ca.new(name=name + "Save", type='BYTE_COLOR', domain='POINT')) if props.has_saved else None
                use_point = True

            # Build KDTree for distance queries
            size = len(mesh.vertices)
            kd = KDTree(size)
            coords = []
            for i, v in enumerate(mesh.vertices):
                co = obj.matrix_world @ v.co
                coords.append(co)
                kd.insert(co, i)
            kd.balance()

            # Map vertex to loop indices
            loop_map = {}
            for poly in mesh.polygons:
                for li in poly.loop_indices:
                    vidx = mesh.loops[li].vertex_index
                    loop_map.setdefault(vidx, []).append(li)

            self.targets.append((mesh, live, saved, kd, coords, loop_map, obj, use_point))

        # Initialize
        props.running = True
        props.last_loc = tuple(props.emitter.matrix_world.translation)
        props.last_rot = tuple(props.emitter.matrix_world.to_quaternion())

        wm = context.window_manager
        self._timer = wm.event_timer_add(props.refresh_rate, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        props = context.scene.vlp_props
        if not props.running:
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            loc = props.emitter.matrix_world.translation
            rot = props.emitter.matrix_world.to_quaternion()
            if (loc - mathutils.Vector(props.last_loc)).length > 1e-4 or rot != mathutils.Quaternion(props.last_rot):
                props.last_loc = tuple(loc)
                props.last_rot = tuple(rot)
                self.paint_vertices(context, props)
        return {'PASS_THROUGH'}

    def cancel(self, context):
        """Stop and clean up the timer."""
        context.window_manager.event_timer_remove(self._timer)

    def paint_vertices(self, context, props):
        """Apply color to target meshes based on emitter settings."""
        emit_loc = props.emitter.matrix_world.translation
        emit_col = props.color
        forward = props.emitter.matrix_world.to_quaternion() @ mathutils.Vector((0, 1, 0))
        lt = props.light_type
        r = props.range

        for mesh, live, saved, kd, coords, loop_map, obj, use_point in self.targets:
            # Reset to saved or black
            if not use_point:
                default = [l.color for l in (saved.data if saved else [])]
                for i, loop in enumerate(live.data):
                    loop.color = default[i] if default else (0, 0, 0, 1)
            else:
                default = [c.color for c in (saved.data if saved else [])]
                for i, vc in enumerate(live.data):
                    vc.color = default[i] if default else (0, 0, 0, 1)

            # SUN mode
            if lt == 'SUN':
                for vidx, co in enumerate(coords):
                    base = max(0.0, forward.dot((co - emit_loc).normalized()))
                    factor = (base * props.strength) ** (2 if props.paint_mode == 'SHARP' else 1) \
                             * (0.5 if props.paint_mode == 'DIRTY' else 1)
                    if not use_point:
                        for li in loop_map.get(vidx, []):
                            old = live.data[li].color
                            new = [
                                min(1, old[i] + (emit_col[i] - old[i]) * factor)
                                if not props.darken else
                                min(1, old[i] + (emit_col[i] - old[i]) * factor * 0.5)
                                for i in range(3)
                            ]
                            live.data[li].color = (*new, 1)
                    else:
                        old = live.data[vidx].color
                        new = [
                            min(1, old[i] + (emit_col[i] - old[i]) * factor)
                            for i in range(3)
                        ]
                        live.data[vidx].color = (*new, 1)
                continue

            # Other modes: POINT, SPOT, AREA
            for co, vidx, dist in kd.find_range(emit_loc, r):
                if lt == 'POINT':
                    base = max(0.0, 1 - dist / r)
                elif lt == 'SPOT':
                    angle = forward.angle((co - emit_loc).normalized())
                    base = max(0.0, 1 - dist / r) if angle <= radians(props.spot_angle) else 0.0
                elif lt == 'AREA':
                    locl = props.emitter.matrix_world.inverted() @ co
                    x, y, z = locl
                    base = max(0.0, 1 - (-z) / r) if abs(x) <= props.area_x/2 and abs(y) <= props.area_y/2 and 0 <= -z <= r else 0.0
                else:
                    base = 0.0

                factor = (base * props.strength) ** (2 if props.paint_mode == 'SHARP' else 1) \
                         * (0.5 if props.paint_mode == 'DIRTY' else 1)

                if not use_point:
                    for li in loop_map.get(vidx, []):
                        old = live.data[li].color
                        new = [
                            min(1, old[i] + (emit_col[i] - old[i]) * factor)
                            for i in range(3)
                        ]
                        live.data[li].color = (*new, 1)
                else:
                    old = live.data[vidx].color
                    new = [
                        min(1, old[i] + (emit_col[i] - old[i]) * factor)
                        for i in range(3)
                    ]
                    live.data[vidx].color = (*new, 1)

        # Redraw 3D view
        if context.area and context.area.type == 'VIEW_3D':
            context.area.tag_redraw()

class VLP_OT_stop_paint(bpy.types.Operator):
    """Stop the modal vertex-light painting session."""
    bl_idname = "vlp.stop_paint"
    bl_label = "Stop Painting"

    def execute(self, context):
        context.scene.vlp_props.running = False
        return {'FINISHED'}

class VLP_OT_save_layer(bpy.types.Operator):
    """Save current painted layer into a separate attribute."""
    bl_idname = "vlp.save_layer"
    bl_label = "Save Layer"

    def execute(self, context):
        props = context.scene.vlp_props
        name = props.attribute_name
        save_name = name + "Save"

        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            mesh = obj.data

            if mesh.vertex_colors and name in mesh.vertex_colors:
                live = mesh.vertex_colors[name]
                saved = mesh.vertex_colors.get(save_name) or mesh.vertex_colors.new(name=save_name)
                for i, loop in enumerate(live.data):
                    saved.data[i].color = loop.color
            elif mesh.color_attributes and name in mesh.color_attributes:
                ca = mesh.color_attributes
                live = ca[name]
                saved = ca.get(save_name) or ca.new(name=save_name, type='BYTE_COLOR', domain='POINT')
                for i, vc in enumerate(live.data):
                    saved.data[i].color = vc.color

        props.has_saved = True
        self.report({'INFO'}, f"Layer saved as '{save_name}'")
        return {'FINISHED'}

class ConvertToFaceCornerOperator(bpy.types.Operator):
    """Convert all color attributes of the active mesh to face‑corner byte color."""
    bl_idname = "object.convert_to_face_corner"
    bl_label = "Convert to Face‑Corner Color"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first")
            return {'CANCELLED'}

        mesh = obj.data
        if not mesh.color_attributes:
            self.report({'INFO'}, "No color attributes to convert")
            return {'FINISHED'}

        for idx, attr in enumerate(mesh.color_attributes):
            mesh.color_attributes.active_color_index = idx
            try:
                bpy.ops.geometry.color_attribute_convert(
                    domain='CORNER',
                    data_type='BYTE_COLOR'
                )
                self.report({'INFO'}, f"Converted '{attr.name}' to CORNER BYTE_COLOR")
            except Exception as e:
                self.report({'WARNING'}, f"Failed to convert '{attr.name}': {e}")
        return {'FINISHED'}

class VLP_PT_panel(bpy.types.Panel):
    """UI panel for the Vertex Light Painter."""
    bl_label = "Dynamic Vertex Color"
    bl_idname = "VLP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VertexColRefineKit'

    def draw(self, context):
        layout = self.layout
        props = context.scene.vlp_props

        layout.prop(props, 'emitter')
        layout.prop(props, 'light_type', text='Type')
        layout.prop(props, 'color')
        layout.prop(props, 'strength')
        if props.light_type in {'POINT', 'SPOT'}:
            layout.prop(props, 'range')
        if props.light_type == 'SPOT':
            layout.prop(props, 'spot_angle')
        if props.light_type == 'AREA':
            layout.prop(props, 'area_x')
            layout.prop(props, 'area_y')
        layout.prop(props, 'refresh_rate')
        layout.prop(props, 'darken')

        row = layout.row(align=True)
        row.operator(ConvertToFaceCornerOperator.bl_idname, text="", icon='COLOR')

        layout.prop(props, 'paint_mode', text='Mode')
        layout.prop(props, 'attribute_name')

        layout.operator('vlp.save_layer', text='Save Layer', icon='BOOKMARKS')
        if not props.running:
            layout.operator('vlp.paint_modal', text='Start Painting', icon='PLAY')
        else:
            layout.operator('vlp.stop_paint', text='Stop Painting', icon='PAUSE')

classes = [
    VLPProperties,
    VLP_OT_paint_modal,
    VLP_OT_stop_paint,
    VLP_OT_save_layer,
    ConvertToFaceCornerOperator,
    VLP_PT_panel
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vlp_props = bpy.props.PointerProperty(type=VLPProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.vlp_props

if __name__ == "__main__":
    register()
