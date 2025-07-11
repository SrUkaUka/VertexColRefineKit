import bpy 
import numpy as np

# maps color-index → list of (object_name, loop_index)
COLOR_LOOP_MAP = {}

# list of (object_name, loop_index, original_color) for undo
ORIGINAL_COLOR_MAP = []

# list of (object_name, loop_index, saved_color) for Save/Apply Saved
SAVED_COLOR_MAP = []


def linear_to_srgb(c):
    """Convert a linear-color RGB(A) to sRGB space."""
    def convert(channel):
        if channel < 0.0031308:
            return 12.92 * channel
        else:
            return 1.055 * (channel ** (1.0 / 2.4)) - 0.055
    return [convert(x) for x in c]


def srgb_to_linear(c):
    """Convert an sRGB-color RGB(A) to linear space."""
    def convert(channel):
        if channel < 0.04045:
            return channel / 12.92
        else:
            return ((channel + 0.055) / 1.055) ** 2.4
    return [convert(x) for x in c]


def colors_equal(a, b, tol=1e-3):
    """Check if two RGBA colors are nearly equal within tolerance."""
    return all(abs(x - y) < tol for x, y in zip(a, b))


def on_pick_color(self, context):
    """Update active index when user picks a color with the eyedropper."""
    if not hasattr(context, "scene") or not hasattr(context.scene, "vcr_pick_color"):
        return

    picked = list(context.scene.vcr_pick_color)
    best_idx = None
    best_dist = float('inf')
    for i, item in enumerate(context.scene.vcr_colors):
        dist = sum((pc - ic) ** 2 for pc, ic in zip(picked, item.color))
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    if best_idx is not None:
        context.scene.vcr_active_index = best_idx


class VCR_ColorItem(bpy.types.PropertyGroup):
    """Holds one unique vertex color for UI listing."""
    index: bpy.props.IntProperty()
    color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Vertex color in sRGB",
        subtype='COLOR_GAMMA', size=4,
        min=0.0, max=1.0
    )


# UIList to display each color swatch
type(VCR_UL_color_list := type(
    'VCR_UL_color_list',
    (bpy.types.UIList,),
    {
        'draw_item': lambda self, context, layout, data, item, icon, active_data, active_propname, index:
            layout.prop(item, "color", text=str(item.index + 1))
    }
))


class MESH_OT_report_vertex_colors(bpy.types.Operator):
    """Scan selected meshes and list all unique vertex colors."""
    bl_idname = "mesh.report_vertex_colors"
    bl_label = "Report Vertex Colors"

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        scene = context.scene
        COLOR_LOOP_MAP.clear()
        scene.vcr_colors.clear()

        unique = []
        seen = []

        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            layer = obj.data.vertex_colors.active
            if not layer:
                self.report({'WARNING'}, f"{obj.name} has no vertex colors.")
                continue
            for poly in obj.data.polygons:
                for li in poly.loop_indices:
                    c = layer.data[li].color
                    key = tuple(round(v, 4) for v in c)
                    if key in seen:
                        idx = seen.index(key)
                        COLOR_LOOP_MAP[idx].append((obj.name, li))
                    else:
                        idx = len(unique)
                        seen.append(key)
                        unique.append(key)
                        COLOR_LOOP_MAP[idx] = [(obj.name, li)]

        for idx, key in enumerate(unique):
            item = scene.vcr_colors.add()
            item.index = idx
            item.color = list(key)

        self.report({'INFO'}, f"Found {len(unique)} unique colors.")
        return {'FINISHED'}


class MESH_OT_save_vertex_colors(bpy.types.Operator):
    """Save current vertex colors of selected meshes for later recall."""
    bl_idname = "mesh.save_vertex_colors"
    bl_label = "Save Data"

    def execute(self, context):
        global SAVED_COLOR_MAP
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        SAVED_COLOR_MAP.clear()
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            layer = obj.data.vertex_colors.active
            if not layer:
                continue
            for poly in obj.data.polygons:
                for li in poly.loop_indices:
                    color = list(layer.data[li].color)
                    SAVED_COLOR_MAP.append((obj.name, li, color))

        self.report({'INFO'}, f"Saved colors for {len(context.selected_objects)} object(s).")
        return {'FINISHED'}


class MESH_OT_apply_saved_vertex_colors(bpy.types.Operator):
    """Re-apply previously saved vertex colors to their meshes."""
    bl_idname = "mesh.apply_saved_vertex_colors"
    bl_label = "Apply Saved"

    def execute(self, context):
        global SAVED_COLOR_MAP
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj_name, li, color in SAVED_COLOR_MAP:
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj.type != 'MESH':
                continue
            layer = obj.data.vertex_colors.active
            if not layer:
                continue
            layer.data[li].color = color

        self.report({'INFO'}, "Re-applied saved vertex colors.")
        return {'FINISHED'}


class MESH_OT_apply_show_detail_changes(bpy.types.Operator):
    """Apply edited palette colors back onto meshes (with optional selection filter)."""
    bl_idname = "mesh.apply_show_detail_changes"
    bl_label = "Apply Changes"

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        scene = context.scene
        ORIGINAL_COLOR_MAP.clear()
        changes_by_obj = {}
        selected_names = {obj.name for obj in context.selected_objects}

        for item in scene.vcr_colors:
            idx = item.index
            new_color = list(item.color)
            for obj_name, li in COLOR_LOOP_MAP.get(idx, []):
                if scene.vcr_apply_selected and obj_name not in selected_names:
                    continue
                changes_by_obj.setdefault(obj_name, []).append((li, new_color))

        for obj_name, changes in changes_by_obj.items():
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj.type != 'MESH':
                continue
            layer = obj.data.vertex_colors.active
            if not layer:
                continue
            for li, new_color in changes:
                orig = list(layer.data[li].color)
                ORIGINAL_COLOR_MAP.append((obj_name, li, orig))
                layer.data[li].color = new_color

        self.report({'INFO'}, "Applied Show Details changes.")
        return {'FINISHED'}


class MESH_OT_undo_vertex_colors(bpy.types.Operator):
    """Undo the last palette application (with optional selection filter)."""
    bl_idname = "mesh.undo_vertex_colors"
    bl_label = "Undo Changes"

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        scene = context.scene
        selected_names = {obj.name for obj in context.selected_objects}
        remaining = []

        for obj_name, li, orig in ORIGINAL_COLOR_MAP:
            if not scene.vcr_undo_selected or obj_name in selected_names:
                obj = bpy.data.objects.get(obj_name)
                if obj and obj.type == 'MESH':
                    layer = obj.data.vertex_colors.active
                    if layer:
                        layer.data[li].color = orig
            else:
                remaining.append((obj_name, li, orig))

        ORIGINAL_COLOR_MAP.clear()
        ORIGINAL_COLOR_MAP.extend(remaining)

        self.report({'INFO'}, "Reverted vertex color changes.")
        return {'FINISHED'}


class MESH_OT_convert_vertex_colors(bpy.types.Operator):
    """Cluster-reduce the palette of selected meshes to a target number of colors."""
    bl_idname = "mesh.convert_vertex_colors"
    bl_label = "Convert Vertex Colors"

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        scene = context.scene
        target = scene.vcr_target_count
        if not scene.vcr_colors:
            self.report({'ERROR'}, "Run 'Report Vertex Colors' first.")
            return {'CANCELLED'}

        unique_colors = [tuple(item.color) for item in scene.vcr_colors]
        data = np.array(unique_colors, dtype=float)
        if len(data) < target:
            self.report({'WARNING'}, "Fewer unique colors than target clusters.")
            return {'CANCELLED'}

        centers = kmeans_numpy(data, target, iterations=10, seed=0)

        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            layer = obj.data.vertex_colors.active
            if not layer:
                continue
            for poly in obj.data.polygons:
                for li in poly.loop_indices:
                    orig = np.array(layer.data[li].color, dtype=float)
                    dists = np.sum((centers - orig) ** 2, axis=1)
                    idx = int(np.argmin(dists))
                    layer.data[li].color = centers[idx].tolist()

        bpy.ops.mesh.report_vertex_colors()
        self.report({'INFO'}, f"Converted to {target} colors.")
        return {'FINISHED'}


class MESH_OT_pick_vertex_color(bpy.types.Operator):
    """Pick the exact RGBA of the selected vertex into the UI list."""
    bl_idname = "mesh.pick_vertex_color"
    bl_label = "Pick by Vertex"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        import bmesh
        scene = context.scene
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        verts = [v for v in bm.verts if v.select]
        if len(verts) != 1:
            self.report({'ERROR'}, "Select exactly one vertex in Edit Mode.")
            return {'CANCELLED'}

        vert = verts[0]
        color_layer = bm.loops.layers.color.active
        if not color_layer:
            self.report({'ERROR'}, "No active vertex color layer found.")
            return {'CANCELLED'}

        picked = None
        for face in bm.faces:
            for loop in face.loops:
                if loop.vert == vert:
                    picked = loop[color_layer]
                    break
            if picked:
                break

        if not picked:
            self.report({'ERROR'}, "Could not retrieve vertex color.")
            return {'CANCELLED'}

        key = tuple(round(c, 4) for c in picked)
        for i, item in enumerate(scene.vcr_colors):
            if colors_equal(key, tuple(item.color)):
                scene.vcr_active_index = i
                self.report({'INFO'}, f"Color matched at index {i+1}.")
                return {'FINISHED'}

        self.report({'WARNING'}, "Vertex color not found in list.")
        return {'CANCELLED'}


def init_kmeans_pp(data, k, seed=None):
    """Initialize k-means++ centers for clustering."""
    if seed is not None:
        np.random.seed(seed)
    centers = []
    idx = np.random.randint(len(data))
    centers.append(data[idx])
    for _ in range(1, k):
        dists = np.min(
            np.stack([np.sum((data - c)**2, axis=1) for c in centers]), axis=0
        )
        probs = dists / dists.sum()
        idx = np.random.choice(len(data), p=probs)
        centers.append(data[idx])
    return np.vstack(centers)


def kmeans_numpy(data, k, iterations=10, seed=None):
    """Run k-means clustering on an Nx4 RGBA dataset."""
    centers = init_kmeans_pp(data, k, seed)
    for _ in range(iterations):
        dists = np.sum((data[:, None, :] - centers[None, :, :])**2, axis=2)
        labels = np.argmin(dists, axis=1)
        new_centers = []
        for i in range(k):
            pts = data[labels == i]
            new_centers.append(pts.mean(axis=0) if len(pts) else centers[i])
        centers = np.vstack(new_centers)
    return centers


class MESH_PT_vertex_color_reporter_panel(bpy.types.Panel):
    """UI Panel for reporting and editing vertex colors."""
    bl_label = "Vertex Color Reporter"
    bl_idname = "MESH_PT_vertex_color_reporter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VertexColRefineKit'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.operator("mesh.report_vertex_colors", icon='VIEWZOOM')
        layout.prop(scene, "vcr_show_details", text="Show Details", toggle=True)

        if scene.vcr_show_details and scene.vcr_colors:
            layout.prop(scene, "vcr_pick_color", text="Pick Color", icon='EYEDROPPER')
            layout.operator("mesh.pick_vertex_color", icon='VERTEXSEL')
            layout.template_list(
                "VCR_UL_color_list", "vcr_colors",
                scene, "vcr_colors",
                scene, "vcr_active_index",
                rows=4
            )

            # -- Apply/Undo selection checkboxes side by side --
            row = layout.row(align=True)
            row.prop(scene, "vcr_apply_selected", text="Apply Selected")
            row.prop(scene, "vcr_undo_selected", text="Undo Selected")
            layout.separator()

            # -- Apply/Undo buttons grouped --
            row = layout.row(align=True)
            row.operator("mesh.apply_show_detail_changes", text="Apply Changes", icon='FILE_TICK')
            row.operator("mesh.undo_vertex_colors", text="Undo Changes", icon='LOOP_BACK')

            layout.separator()

            # -- Save / Apply Saved buttons grouped --
            row = layout.row(align=True)
            row.operator("mesh.save_vertex_colors", text="Save Data", icon='EXPORT')
            row.operator("mesh.apply_saved_vertex_colors", text="Apply Saved", icon='IMPORT')

        layout.separator()
        layout.label(text="Smart Convert Palette:")
        layout.prop(scene, "vcr_target_count", text="Clusters")
        layout.operator("mesh.convert_vertex_colors", icon='COLOR')


# register all
classes = [
    VCR_ColorItem,
    VCR_UL_color_list,
    MESH_OT_report_vertex_colors,
    MESH_OT_save_vertex_colors,
    MESH_OT_apply_saved_vertex_colors,
    MESH_OT_apply_show_detail_changes,
    MESH_OT_undo_vertex_colors,
    MESH_OT_convert_vertex_colors,
    MESH_OT_pick_vertex_color,
    MESH_PT_vertex_color_reporter_panel,
]


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.vcr_pick_color = bpy.props.FloatVectorProperty(
        name="Pick Color",
        description="Use eyedropper to select a color",
        subtype='COLOR_GAMMA',
        size=4, min=0.0, max=1.0,
        default=(1, 1, 1, 1),
        # update=on_pick_color  ← eliminado para evitar el error
    )
    bpy.types.Scene.vcr_colors = bpy.props.CollectionProperty(type=VCR_ColorItem)
    bpy.types.Scene.vcr_active_index = bpy.props.IntProperty(default=0)
    bpy.types.Scene.vcr_show_details = bpy.props.BoolProperty(name="Show Details", default=False)
    bpy.types.Scene.vcr_target_count = bpy.props.IntProperty(name="Target Clusters", default=4, min=1)
    bpy.types.Scene.vcr_apply_selected = bpy.props.BoolProperty(
        name="Apply Selected",
        description="If checked, only apply changes to selected objects",
        default=False
    )
    bpy.types.Scene.vcr_undo_selected = bpy.props.BoolProperty(
        name="Undo Selected",
        description="If checked, only undo changes on selected objects",
        default=False
    )


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    del bpy.types.Scene.vcr_pick_color
    del bpy.types.Scene.vcr_colors
    del bpy.types.Scene.vcr_active_index
    del bpy.types.Scene.vcr_show_details
    del bpy.types.Scene.vcr_target_count
    del bpy.types.Scene.vcr_apply_selected
    del bpy.types.Scene.vcr_undo_selected


if __name__ == "__main__":
    register()
