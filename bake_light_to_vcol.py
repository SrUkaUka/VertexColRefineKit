import bpy

def update_soft_falloff(self, context):
    self.falloff_type = 'INVERSE_SQUARE' if self.use_soft_falloff else 'CONSTANT'

bpy.types.Light.use_soft_falloff = bpy.props.BoolProperty(
    name="Soft Falloff",
    description="Enable soft falloff using Inverse Square",
    default=True,
    update=update_soft_falloff
)

def update_soft_falloff(self, context):
    self.falloff_type = 'INVERSE_SQUARE' if self.use_soft_falloff else 'CONSTANT'

bpy.types.Light.use_soft_falloff = bpy.props.BoolProperty(
    name="Soft Falloff",
    description="Enable soft falloff by switching to Inverse Square",
    default=True,
    update=update_soft_falloff
)

def add_vertex_lighting(light_type='SUN'):
    obj = bpy.context.object
    if obj is None or obj.type != 'MESH':
        print("Select a mesh object to continue.")
        return

    if "Attribute" not in obj.data.color_attributes:
        obj.data.color_attributes.new(name="Attribute", type='BYTE_COLOR', domain='CORNER')
        print("Color attribute 'Attribute' created with 'FACE CORNER' domain.")
    else:
        print("Color attribute 'Attribute' already exists.")

    bpy.ops.object.light_add(type=light_type, align='WORLD', location=(0, 0, 10))
    print(f"Light of type '{light_type}' created.")

    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.bake_type = 'COMBINED'
    print("Rendering engine set to Cycles.")

def bake_vertex_lighting():
    obj = bpy.context.object
    if obj is None or obj.type != 'MESH':
        print("Select a mesh object to continue.")
        return

    if "Attribute" in obj.data.color_attributes:
        obj.data.color_attributes.active = obj.data.color_attributes["Attribute"]
        print("Color attribute 'Attribute' is active.")
    else:
        print("Color attribute 'Attribute' doesn't exist. Use 'Add Vertex Lighting' first.")
        return

    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.bake_type = 'COMBINED'
    bpy.context.scene.cycles.samples = 64
    bpy.context.scene.render.bake.target = 'VERTEX_COLORS'
    print("Bake target set to 'VERTEX_COLORS'.")

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.bake(type='COMBINED')
    print("Bake completed.")

def disconnect_image_texture(self, context):
    obj = bpy.context.active_object
    if not obj:
        self.report({'WARNING'}, "No active object.")
        return
    if not obj.data.materials:
        self.report({'WARNING'}, "The selected object has no materials.")
        return

    for mat in obj.data.materials:
        if mat and mat.use_nodes:
            nt = mat.node_tree
            img = nt.nodes.get("Image Texture")
            if img:
                for link in [l for l in nt.links if l.from_node == img]:
                    nt.links.remove(link)
                self.report({'INFO'}, f"Disconnected Image Texture in '{mat.name}'")
            else:
                self.report({'WARNING'}, f"No Image Texture node in '{mat.name}'")
        else:
            self.report({'WARNING'}, f"Material '{mat.name}' not using nodes.")

def connect_image_texture(self, context):
    obj = bpy.context.active_object
    if not obj:
        self.report({'WARNING'}, "No active object.")
        return
    if not obj.data.materials:
        self.report({'WARNING'}, "The selected object has no materials.")
        return

    for mat in obj.data.materials:
        if mat and mat.use_nodes:
            nt = mat.node_tree
            img = nt.nodes.get("Image Texture")
            bsdf = nt.nodes.get("Principled BSDF")
            if img and bsdf:
                for link in bsdf.inputs['Base Color'].links:
                    nt.links.remove(link)
                nt.links.new(img.outputs['Color'], bsdf.inputs['Base Color'])
                self.report({'INFO'}, f"Connected Image Texture in '{mat.name}'")
            else:
                self.report({'WARNING'}, f"Required nodes missing in '{mat.name}'")
        else:
            self.report({'WARNING'}, f"Material '{mat.name}' not using nodes.")

class BackToEeveeOperator(bpy.types.Operator):
    bl_idname = "object.back_to_eevee"
    bl_label = "Back to Eevee"
    def execute(self, context):
        try:
            context.scene.render.engine = 'BLENDER_EEVEE'
        except:
            context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
        self.report({'INFO'}, "Render engine changed to Eevee")
        return {'FINISHED'}

def update_emission_color(self, context):
    obj = context.active_object
    if obj and obj.data.materials:
        for mat in obj.data.materials:
            if mat.use_nodes:
                p = mat.node_tree.nodes.get("Principled BSDF")
                if p and len(p.inputs) > 26:
                    p.inputs[26].default_value = (*context.scene.emission_color, 1.0)

def update_emission_strength(self, context):
    obj = context.active_object
    if obj and obj.data.materials:
        for mat in obj.data.materials:
            if mat.use_nodes:
                p = mat.node_tree.nodes.get("Principled BSDF")
                if p and len(p.inputs) > 27:
                    p.inputs[27].default_value = context.scene.emission_strength

def update_specular_value(self, context):
    for o in context.selected_objects:
        if o.type == 'MESH' and o.data.materials:
            for mat in o.data.materials:
                if mat.use_nodes:
                    p = mat.node_tree.nodes.get("Principled BSDF")
                    if p:
                        if "Specular" in p.inputs:
                            p.inputs["Specular"].default_value = context.scene.specular_value
                        if "Specular IOR Level" in p.inputs:
                            p.inputs["Specular IOR Level"].default_value = context.scene.specular_value

def update_transmission_value(self, context):
    for o in context.selected_objects:
        if o.type == 'MESH' and o.data.materials:
            for mat in o.data.materials:
                if mat.use_nodes:
                    p = mat.node_tree.nodes.get("Principled BSDF")
                    if p and "Transmission" in p.inputs:
                        p.inputs["Transmission"].default_value = context.scene.transmission_value

class ApplyEmissionOperator(bpy.types.Operator):
    bl_idname = "object.apply_emission_settings"
    bl_label = "Apply Emission Settings"
    def execute(self, context):
        update_emission_color(self, context)
        update_emission_strength(self, context)
        update_specular_value(self, context)
        update_transmission_value(self, context)
        self.report({'INFO'}, "Emission and transmission settings applied.")
        return {'FINISHED'}

def update_light_type(self, context):
    obj = context.active_object
    if obj and obj.type == 'LIGHT':
        obj.data.type = context.scene.light_type

class VertexLightingPanel(bpy.types.Panel):
    bl_label = "Vertex Color Bake"
    bl_idname = "VIEW3D_PT_vertex_lighting_and_texture"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VertexColRefineKit'

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        obj = context.active_object

        # Vertex Lighting Main Controls
        layout.label(text="Vertex Lighting:")
        row = layout.row(align=True)
        row.prop(scn, "light_type", text="")
        row = layout.row(align=True)
        row.operator("object.add_vertex_lighting", text="Add Light")
        row.operator("object.bake_vertex_lighting", text="Bake Light")
        row = layout.row(align=True)
        row.operator("node.connect_image_texture", text="Tex On")
        row.operator("node.disconnect_image_texture", text="Tex Off")

        # Emission and Transmission
        layout.separator()
        layout.label(text="Emission & Transmission:")
        layout.prop(scn, "emission_strength", text="Strength")
        layout.prop(scn, "specular_value", text="Specular")
        layout.prop(scn, "transmission_value", text="Transmission")

        # Light Settings (only if active object is a light)
        if obj and obj.type == 'LIGHT':
            light = obj.data
            lt = light.type

            if lt == 'POINT':
                layout.separator()
                layout.label(text="Point Light:")
                layout.prop(light, "color", text="Color")
                layout.prop(light, "energy", text="Power")
                layout.prop(light, "use_soft_falloff", text="Soft Falloff")  # <- Aquí se colocó arriba de Radius
                layout.prop(light, "shadow_soft_size", text="Radius")
                layout.prop(light, "use_shadow", text="Shadow")
                layout.label(text="Influence")
                layout.prop(light, "diffuse_factor", text="Diffuse")
                layout.prop(light, "specular_factor", text="Glossy")
                layout.prop(light, "transmission_factor", text="Transmission")
                layout.prop(light, "volume_factor", text="Volume Scatter")
                layout.prop(light, "use_custom_distance", text="Custom Distance")
                if light.use_custom_distance:
                    layout.prop(light, "cutoff_distance", text="")

            elif lt == 'SUN':
                layout.separator()
                layout.label(text="Sun Light:")
                layout.prop(light, "color", text="Color")
                layout.prop(light, "energy", text="Strength")
                layout.prop(light, "angle", text="Angle")
                layout.prop(light, "use_shadow", text="Shadow")
                layout.label(text="Influence")
                layout.prop(light, "diffuse_factor", text="Diffuse")
                layout.prop(light, "specular_factor", text="Glossy")
                layout.prop(light, "transmission_factor", text="Transmission")
                layout.prop(light, "volume_factor", text="Volume Scatter")

            elif lt == 'SPOT':
                layout.separator()
                layout.label(text="Spot Light:")
                layout.prop(light, "color", text="Color")
                layout.prop(light, "energy", text="Power")
                layout.prop(light, "use_soft_falloff", text="Soft Falloff")
                layout.prop(light, "shadow_soft_size", text="Radius")
                layout.prop(light, "spot_size", text="Size")
                layout.prop(light, "spot_blend", text="Blend")
                layout.prop(light, "show_cone", text="Show Cone")
                layout.prop(light, "use_shadow", text="Shadow")
                layout.label(text="Influence")
                layout.prop(light, "diffuse_factor", text="Diffuse")
                layout.prop(light, "specular_factor", text="Glossy")
                layout.prop(light, "transmission_factor", text="Transmission")
                layout.prop(light, "volume_factor", text="Volume Scatter")
                layout.prop(light, "use_custom_distance", text="Custom Distance")
                if light.use_custom_distance:
                    layout.prop(light, "cutoff_distance", text="")

            elif lt == 'AREA':
                layout.separator()
                layout.label(text="Area Light:")
                layout.prop(light, "color", text="Color")
                layout.prop(light, "energy", text="Power")
                layout.prop(light, "shape", text="Shape")
                layout.prop(light, "size", text="Size X")
                layout.prop(light, "size_y", text="Size Y")
                layout.prop(light, "use_shadow", text="Shadow")
                layout.label(text="Influence")
                layout.prop(light, "diffuse_factor", text="Diffuse")
                layout.prop(light, "specular_factor", text="Glossy")
                layout.prop(light, "transmission_factor", text="Transmission")
                layout.prop(light, "volume_factor", text="Volume Scatter")
                layout.prop(light, "use_custom_distance", text="Custom Distance")
                if light.use_custom_distance:
                    layout.prop(light, "cutoff_distance", text="")


class AddVertexLightingOperator(bpy.types.Operator):
    bl_idname = "object.add_vertex_lighting"
    bl_label = "Add Vertex Lighting"
    def execute(self, context):
        add_vertex_lighting(context.scene.light_type)
        return {'FINISHED'}

class BakeVertexLightingOperator(bpy.types.Operator):
    bl_idname = "object.bake_vertex_lighting"
    bl_label = "Bake Light"
    def execute(self, context):
        bake_vertex_lighting()
        if context.scene.return_to_eevee:
            try:
                context.scene.render.engine = 'BLENDER_EEVEE'
            except:
                context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
        return {'FINISHED'}

class DisconnectImageTextureOperator(bpy.types.Operator):
    bl_idname = "node.disconnect_image_texture"
    bl_label = "Disconnect Image"
    def execute(self, context):
        disconnect_image_texture(self, context)
        return {'FINISHED'}

class ConnectImageTextureOperator(bpy.types.Operator):
    bl_idname = "node.connect_image_texture"
    bl_label = "Connect Image"
    def execute(self, context):
        connect_image_texture(self, context)
        return {'FINISHED'}

def register():
    bpy.utils.register_class(VertexLightingPanel)
    bpy.utils.register_class(AddVertexLightingOperator)
    bpy.utils.register_class(BakeVertexLightingOperator)
    bpy.utils.register_class(DisconnectImageTextureOperator)
    bpy.utils.register_class(ConnectImageTextureOperator)
    bpy.utils.register_class(BackToEeveeOperator)
    bpy.utils.register_class(ApplyEmissionOperator)

    bpy.types.Scene.light_type = bpy.props.EnumProperty(
        name="Light Type",
        description="Choose the light type",
        items=[
            ('SUN',   "Sun",   "Sunlight"),
            ('POINT', "Point", "Point light"),
            ('SPOT',  "Spot",  "Spotlight"),
            ('AREA',  "Area",  "Area light"),
        ],
        default='SUN',
        update=update_light_type
    )
    bpy.types.Scene.return_to_eevee = bpy.props.BoolProperty(
        name="Return to Eevee",
        description="Switch render engine back to Eevee after baking",
        default=False
    )
    bpy.types.Scene.emission_color = bpy.props.FloatVectorProperty(
        name="Emission Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0,
        update=update_emission_color
    )
    bpy.types.Scene.emission_strength = bpy.props.FloatProperty(
        name="Emission Strength",
        default=1.0,
        min=0.0,
        update=update_emission_strength
    )
    bpy.types.Scene.specular_value = bpy.props.FloatProperty(
        name="Specular",
        default=0.5,
        min=0.0, max=1.0,
        update=update_specular_value
    )
    bpy.types.Scene.transmission_value = bpy.props.FloatProperty(
        name="Transmission",
        default=0.0,
        min=0.0, max=1.0,
        update=update_transmission_value
    )

def unregister():
    bpy.utils.unregister_class(VertexLightingPanel)
    bpy.utils.unregister_class(AddVertexLightingOperator)
    bpy.utils.unregister_class(BakeVertexLightingOperator)
    bpy.utils.unregister_class(DisconnectImageTextureOperator)
    bpy.utils.unregister_class(ConnectImageTextureOperator)
    bpy.utils.unregister_class(BackToEeveeOperator)
    bpy.utils.unregister_class(ApplyEmissionOperator)
    del bpy.types.Scene.light_type
    del bpy.types.Scene.return_to_eevee
    del bpy.types.Scene.emission_color
    del bpy.types.Scene.emission_strength
    del bpy.types.Scene.specular_value
    del bpy.types.Scene.transmission_value

if __name__ == "__main__":
    register()
