# SPDX-FileCopyrightText: 2020-2022 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Real Snow by Marco Pavanello and Drew Perttula.
# Original project: https://gitlab.com/marcopavanello/real-snow
# Distributed under the GNU General Public License v3.0 or later.
#
# MODIFIED VERSION: this copy has been changed from the original to run on
# Blender 4.2 up to 5.2:
#   * node sockets are looked up by name instead of by index
#   * Material.use_nodes is no longer set on Blender 5.0+ (deprecated, no effect)
#   * Cycles / material properties whose location changed between versions are
#     set defensively, so a missing property can never abort snow creation

bl_info = {
    "name": "Real Snow",
    "description": "Generate snow mesh",
    "author": "Marco Pavanello, Drew Perttula",
    "version": (1, 3, 3),
    "blender": (4, 2, 0),
    "location": "View 3D > Properties Panel",
    "doc_url": "https://gitlab.com/marcopavanello/real-snow",
    "tracker_url": "https://gitlab.com/marcopavanello/real-snow/-/issues",
    "support": "COMMUNITY",
    "category": "Object",
}

# Libraries
import math
import random

import bpy
import bmesh
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector


# Panel
class REAL_PT_snow(Panel):
    bl_space_type = "VIEW_3D"
    bl_context = "objectmode"
    bl_region_type = "UI"
    bl_label = "Snow"
    bl_category = "Real Snow"

    def draw(self, context):
        scn = context.scene
        settings = scn.snow
        layout = self.layout
        col = layout.column(align=True)
        col.prop(settings, 'coverage', slider=True)
        col.prop(settings, 'height')
        layout.use_property_split = True
        layout.use_property_decorate = False
        flow = layout.grid_flow(row_major=True, columns=0, even_columns=False, even_rows=False, align=True)
        col = flow.column()
        col.prop(settings, 'vertices')
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("snow.create", text="Add Snow", icon="FREEZE")


class SNOW_OT_Create(Operator):
    bl_idname = "snow.create"
    bl_label = "Create Snow"
    bl_description = "Create snow"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context) -> bool:
        return bool(context.selected_objects)

    def execute(self, context):
        coverage = context.scene.snow.coverage
        height = context.scene.snow.height
        vertices = context.scene.snow.vertices

        # Get a list of selected objects, except non-mesh objects
        input_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not input_objects:
            self.report({'WARNING'}, "Select at least one mesh object")
            show_problems(context, [no_mesh_problem()], snow_added=False)
            return {'CANCELLED'}

        snow_list = []
        problems = []

        # Start UI progress bar
        length = len(input_objects)
        context.window_manager.progress_begin(0, 10)
        timer = 0

        for obj in input_objects:
            # Timer
            context.window_manager.progress_update(timer)
            # Duplicate mesh
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            object_eval = obj.evaluated_get(context.view_layer.depsgraph)
            mesh_eval = bpy.data.meshes.new_from_object(object_eval)
            # Read the face selection from the ORIGINAL mesh. The evaluated copy
            # does not reliably keep the selection in recent Blender versions.
            # This is only possible when modifiers did not change the face count.
            selected_idx = None
            if vertices:
                polys = obj.data.polygons
                if len(polys) == len(mesh_eval.polygons):
                    selected_idx = set(p.index for p in polys if p.select)
                    if not selected_idx:
                        problems.append(no_selection_problem(obj.name))
                        self.report({'WARNING'}, f"No faces are selected on '{obj.name}'. Select faces in Edit Mode first")
                        bpy.data.meshes.remove(mesh_eval)
                        continue
            snow_object = bpy.data.objects.new("Snow", mesh_eval)
            snow_object.matrix_world = obj.matrix_world
            context.collection.objects.link(snow_object)
            bpy.ops.object.select_all(action='DESELECT')
            context.view_layer.objects.active = snow_object
            snow_object.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')
            bm_orig = bmesh.from_edit_mesh(snow_object.data)
            bm_copy = bm_orig.copy()
            bm_copy.transform(obj.matrix_world)
            bm_copy.normal_update()
            # Get faces data
            total, considered, upward, best_nz = delete_faces(vertices, bm_copy, snow_object, selected_idx)
            if not snow_object.data.polygons:
                problems.append(no_upward_problem(obj.name, vertices, total, considered, best_nz))
                self.report({'WARNING'}, (
                    f"No upward-facing faces to cover on '{obj.name}': "
                    f"{total} faces, {considered} {'selected' if vertices else 'considered'}, "
                    f"{upward} pointing up. Highest face normal Z = {best_nz:.2f} "
                    f"(needs at least {math.sin(0.5):.2f}; negative means flipped normals)"))
                dead_mesh = snow_object.data
                bpy.data.objects.remove(snow_object)
                bpy.data.meshes.remove(dead_mesh)
                continue
            ballobj = add_metaballs(context, height, snow_object)
            context.view_layer.objects.active = snow_object
            surface_area = area(snow_object)
            snow = add_particles(context, surface_area, height, coverage, snow_object, ballobj)
            add_modifiers(snow)
            # Place inside collection
            context.view_layer.active_layer_collection = context.view_layer.layer_collection
            if "Snow" not in context.scene.collection.children:
                coll = bpy.data.collections.new("Snow")
                context.scene.collection.children.link(coll)
            else:
                coll = bpy.data.collections["Snow"]
            coll.objects.link(snow)
            context.view_layer.layer_collection.collection.objects.unlink(snow)
            add_material(snow)
            # Parent with object
            snow.parent = obj
            snow.matrix_parent_inverse = obj.matrix_world.inverted()
            # Add snow to list
            snow_list.append(snow)
            # Update progress bar
            timer += 0.1 / length

        # Select created snow meshes
        for s in snow_list:
            s.select_set(True)
        # End progress bar
        context.window_manager.progress_end()
        if problems:
            show_problems(context, problems, snow_added=bool(snow_list))
        if not snow_list:
            return {'CANCELLED'}
        return {'FINISHED'}


# --- User-facing problem messages ----------------------------------------------
# Each problem is (headline, [lines]). Lines are kept short because Blender
# popups do not wrap text.

def no_mesh_problem():
    return ("No mesh object is selected", [
        "Snow can only be added to mesh objects (not cameras,",
        "lights, curves, etc.).",
        "",
        "To fix it: select a mesh object and click Add Snow again.",
    ])


def no_selection_problem(name: str):
    return (f"'{name}': no faces are selected", [
        "'Selected Faces' is ticked, so snow is only added to the",
        "faces you select.",
        "",
        "To fix it:",
        "  1. Select the object and press Tab (Edit Mode).",
        "  2. Select the faces that should get snow.",
        "  3. Press Tab to go back to Object Mode.",
        "  4. Click Add Snow again.",
        "Or untick 'Selected Faces' to snow every upward-facing part.",
    ])


def no_upward_problem(name: str, selection_mode: bool, total: int, considered: int, best_nz: float):
    if selection_mode:
        headline = f"'{name}': none of the {considered} selected faces point up"
    else:
        headline = f"'{name}': no face of this object points up"
    lines = []
    if best_nz < -0.1:
        lines += [
            "The faces point downward (flipped normals).",
            "",
            "To fix it:",
            "  1. Turn on Overlays > Face Orientation. Red = flipped.",
            "  2. In Edit Mode choose Mesh > Normals > Recalculate Outside.",
        ]
    else:
        lines += [
            "The faces are too steep. Snow only lands on faces that",
            "point within about 60 degrees of straight up.",
            "",
            "To fix it:",
            "  1. Select faces on TOP of the object, not on its walls.",
            "  2. If the object is rotated, apply it first:",
            "     Ctrl+A > Rotation (\"up\" is measured in world space).",
        ]
    if selection_mode:
        lines.append("  Or untick 'Selected Faces' to snow all upward faces.")
    lines += ["", "Then click Add Snow again."]
    return (headline, lines)


def show_problems(context, problems, snow_added: bool):
    """Show one popup describing every object that could not get snow."""
    shown = problems[:3]
    hidden = len(problems) - len(shown)

    def draw(self, _context):
        layout = self.layout
        for index, (headline, lines) in enumerate(shown):
            if index:
                layout.separator()
            layout.label(text=headline, icon='ERROR')
            for line in lines:
                layout.label(text=line)
        if hidden > 0:
            layout.separator()
            layout.label(text=f"...and {hidden} more object(s), see the Info log.")

    title = "Real Snow: some objects were skipped" if snow_added else "Real Snow: no snow was added"
    context.window_manager.popup_menu(draw, title=title, icon='ERROR')


def _try_set(target, attr: str, value) -> bool:
    """Set target.attr = value, returning False instead of raising when the
    property or enum value does not exist in this Blender version."""
    try:
        setattr(target, attr, value)
        return True
    except (AttributeError, TypeError, ValueError, KeyError):
        return False


def add_modifiers(snow):
    bpy.ops.object.transform_apply(location=False, scale=True, rotation=False)
    # Decimate the mesh to get rid of some visual artifacts
    decimate = snow.modifiers.new("Decimate", 'DECIMATE')
    decimate.ratio = 0.5
    subdiv = snow.modifiers.new("Subdiv", "SUBSURF")
    subdiv.render_levels = 1
    subdiv.quality = 1
    # Cycles adaptive subdivision. The property has lived on the object's Cycles
    # settings; newer versions expose the option through the modifier panel, so
    # try the known locations and silently skip any that do not exist.
    cycles_settings = getattr(snow, "cycles", None)
    if cycles_settings is not None:
        _try_set(cycles_settings, "use_adaptive_subdivision", True)
    if hasattr(subdiv, "use_adaptive_subdivision"):
        _try_set(subdiv, "use_adaptive_subdivision", True)


def add_particles(context, surface_area: float, height: float, coverage: float, snow_object: bpy.types.Object, ballobj: bpy.types.Object):
    # Approximate the number of particles to be emitted
    number = int(surface_area * 50 * (height ** -2) * ((coverage / 100) ** 2))
    bpy.ops.object.particle_system_add()
    particles = snow_object.particle_systems[0]
    psettings = particles.settings
    psettings.type = 'HAIR'
    psettings.render_type = 'OBJECT'
    # Generate random number for seed
    random_seed = random.randint(0, 1000)
    particles.seed = random_seed
    # Set particles object
    psettings.particle_size = height
    psettings.instance_object = ballobj
    psettings.count = number
    # Convert particles to mesh
    bpy.ops.object.select_all(action='DESELECT')
    context.view_layer.objects.active = ballobj
    ballobj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    snow = bpy.context.active_object
    snow.scale = [0.09, 0.09, 0.09]
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
    bpy.ops.object.select_all(action='DESELECT')
    snow_object.select_set(True)
    bpy.ops.object.delete()
    snow.select_set(True)
    return snow


def add_metaballs(context, height: float, snow_object: bpy.types.Object) -> bpy.types.Object:
    ball_name = "SnowBall"
    ball = bpy.data.metaballs.new(ball_name)
    ballobj = bpy.data.objects.new(ball_name, ball)
    bpy.context.scene.collection.objects.link(ballobj)
    # These settings have proven to work on a large amount of scenarios
    ball.resolution = 0.7 * height + 0.3
    ball.threshold = 1.3
    element = ball.elements.new()
    element.radius = 1.5
    element.stiffness = 0.75
    ballobj.scale = [0.09, 0.09, 0.09]
    return ballobj


def delete_faces(vertices, bm_copy, snow_object: bpy.types.Object, selected_idx=None):
    # Faces are identified by their position in the face list instead of
    # face.index, which can be stale in edit mode.
    bm_copy.faces.ensure_lookup_table()
    # Selected faces: normally supplied from the original object, otherwise
    # fall back to the selection stored on the copy.
    if vertices and selected_idx is None:
        selected_idx = set(i for i, face in enumerate(bm_copy.faces) if face.select)
    # Based on a certain angle, find all faces not pointing up
    down_faces = set(i for i, face in enumerate(bm_copy.faces) if Vector((0, 0, -1.0)).angle(face.normal, 4.0) < (math.pi / 2.0 + 0.5))
    # Statistics for the warning shown when nothing is left to cover
    candidates = selected_idx if vertices else set(range(len(bm_copy.faces)))
    up_count = len([i for i in candidates if i not in down_faces])
    best_nz = max((bm_copy.faces[i].normal.z for i in candidates), default=0.0)
    stats = (len(bm_copy.faces), len(candidates), up_count, best_nz)
    bm_copy.free()
    bpy.ops.mesh.select_all(action='DESELECT')
    # Select the faces to delete: unselected ones (if requested) and downward ones
    mesh = bmesh.from_edit_mesh(snow_object.data)
    mesh.faces.ensure_lookup_table()
    for i, face in enumerate(mesh.faces):
        if vertices and i not in selected_idx:
            face.select = True
        if i in down_faces:
            face.select = True
    # Delete unnecessary faces
    faces_select = [face for face in mesh.faces if face.select]
    bmesh.ops.delete(mesh, geom=faces_select, context='FACES_KEEP_BOUNDARY')
    mesh.free()
    bpy.ops.object.mode_set(mode='OBJECT')
    return stats


def area(obj: bpy.types.Object) -> float:
    bm_obj = bmesh.new()
    bm_obj.from_mesh(obj.data)
    bm_obj.transform(obj.matrix_world)
    total = sum(face.calc_area() for face in bm_obj.faces)
    bm_obj.free()
    return total


# --- Shader node helpers ---------------------------------------------------
# Sockets are addressed by name because their indices differ between Blender
# versions (the Principled BSDF in particular was reshuffled in 4.0 and later).

def _socket(sockets, *names):
    for name in names:
        sock = sockets.get(name)
        if sock is not None:
            return sock
    return None


def _set_input(node, names, value):
    """Set the default value of the first input of `node` matching one of `names`."""
    if isinstance(names, str):
        names = (names,)
    sock = _socket(node.inputs, *names)
    if sock is None:
        print(f"Real Snow: input {names} not found on {node.bl_idname}, skipped")
        return
    try:
        sock.default_value = value
    except (TypeError, ValueError, AttributeError) as err:
        print(f"Real Snow: could not set {names} on {node.bl_idname}: {err}")


def _link(links, out_socket, in_socket):
    if out_socket is None or in_socket is None:
        print("Real Snow: a node link was skipped because a socket is missing")
        return
    links.new(out_socket, in_socket)


def add_material(obj: bpy.types.Object):
    mat_name = "Snow"
    # If a material with this name already exists, rename it out of the way
    if mat_name in bpy.data.materials:
        bpy.data.materials[mat_name].name = mat_name + ".001"
    mat = bpy.data.materials.new(mat_name)
    # Material.use_nodes is deprecated since Blender 5.0 (always True, setting it
    # has no effect), but it is still required on older versions.
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    # Delete all nodes
    nodes.clear()

    # Add nodes
    output = nodes.new('ShaderNodeOutputMaterial')
    principled = nodes.new('ShaderNodeBsdfPrincipled')
    vec_math = nodes.new('ShaderNodeVectorMath')
    com_xyz = nodes.new('ShaderNodeCombineXYZ')
    dis = nodes.new('ShaderNodeDisplacement')
    mul1 = nodes.new('ShaderNodeMath')
    add1 = nodes.new('ShaderNodeMath')
    add2 = nodes.new('ShaderNodeMath')
    mul2 = nodes.new('ShaderNodeMath')
    mul3 = nodes.new('ShaderNodeMath')
    range1 = nodes.new('ShaderNodeMapRange')
    range2 = nodes.new('ShaderNodeMapRange')
    range3 = nodes.new('ShaderNodeMapRange')
    vor = nodes.new('ShaderNodeTexVoronoi')
    noise1 = nodes.new('ShaderNodeTexNoise')
    noise2 = nodes.new('ShaderNodeTexNoise')
    noise3 = nodes.new('ShaderNodeTexNoise')
    mapping = nodes.new('ShaderNodeMapping')
    coord = nodes.new('ShaderNodeTexCoord')

    # Change location
    output.location = (100, 0)
    principled.location = (-200, 600)
    vec_math.location = (-400, 400)
    com_xyz.location = (-600, 400)
    dis.location = (-200, -100)
    mul1.location = (-400, -100)
    add1.location = (-600, -100)
    add2.location = (-800, -100)
    mul2.location = (-1000, -100)
    mul3.location = (-1000, -300)
    range1.location = (-400, 200)
    range2.location = (-1200, -300)
    range3.location = (-800, -300)
    vor.location = (-1500, 200)
    noise1.location = (-1500, 0)
    noise2.location = (-1500, -250)
    noise3.location = (-1500, -500)
    mapping.location = (-1700, 0)
    coord.location = (-1900, 0)

    # Change node parameters
    _try_set(principled, "distribution", "MULTI_GGX")
    # "RANDOM_WALK_SKIN" on current versions, "RANDOM_WALK" on older ones
    if not _try_set(principled, "subsurface_method", "RANDOM_WALK_SKIN"):
        _try_set(principled, "subsurface_method", "RANDOM_WALK")
    _set_input(principled, "Base Color", (0.904, 0.904, 0.904, 1.0))
    _set_input(principled, ("Subsurface Weight", "Subsurface"), 1.0)
    _set_input(principled, "Subsurface Scale", 1.0)
    _set_input(principled, "Subsurface Radius", (0.36, 0.46, 0.6))
    _set_input(principled, ("Specular IOR Level", "Specular"), 0.224)
    _set_input(principled, "Roughness", 0.1)
    _set_input(principled, "Coat Roughness", 0.1)
    _set_input(principled, "Coat IOR", 1.2)

    vec_math.operation = "MULTIPLY"
    vec_math.inputs[1].default_value = (0.5, 0.5, 0.5)

    com_xyz.inputs["X"].default_value = 0.36
    com_xyz.inputs["Y"].default_value = 0.46
    com_xyz.inputs["Z"].default_value = 0.6

    dis.inputs["Midlevel"].default_value = 0.1
    dis.inputs["Scale"].default_value = 0.3

    mul1.operation = "MULTIPLY"
    mul1.inputs[1].default_value = 0.1
    mul2.operation = "MULTIPLY"
    mul2.inputs[1].default_value = 0.6
    mul3.operation = "MULTIPLY"
    mul3.inputs[1].default_value = 0.4

    range1.inputs["From Min"].default_value = 0.525
    range1.inputs["From Max"].default_value = 0.58
    range2.inputs["From Min"].default_value = 0.069
    range2.inputs["From Max"].default_value = 0.757
    range3.inputs["From Min"].default_value = 0.069
    range3.inputs["From Max"].default_value = 0.757

    vor.feature = "N_SPHERE_RADIUS"
    vor.inputs["Scale"].default_value = 30
    noise1.inputs["Scale"].default_value = 12
    noise2.inputs["Scale"].default_value = 2
    noise2.inputs["Detail"].default_value = 4
    noise3.inputs["Scale"].default_value = 1
    noise3.inputs["Detail"].default_value = 4
    mapping.inputs["Scale"].default_value = (12, 12, 12)

    # Link nodes
    link = mat.node_tree.links
    _link(link, principled.outputs["BSDF"], output.inputs["Surface"])
    _link(link, vec_math.outputs[0], _socket(principled.inputs, "Subsurface Radius"))
    _link(link, com_xyz.outputs["Vector"], vec_math.inputs[0])
    _link(link, dis.outputs["Displacement"], output.inputs["Displacement"])
    _link(link, mul1.outputs[0], dis.inputs["Height"])
    _link(link, add1.outputs[0], mul1.inputs[0])
    _link(link, add2.outputs[0], add1.inputs[0])
    _link(link, mul2.outputs[0], add2.inputs[0])
    _link(link, mul3.outputs[0], add2.inputs[1])
    _link(link, range1.outputs["Result"], _socket(principled.inputs, "Coat Weight", "Clearcoat"))
    _link(link, range2.outputs["Result"], mul3.inputs[0])
    _link(link, range3.outputs["Result"], add1.inputs[1])
    _link(link, vor.outputs["Radius"], range1.inputs["Value"])
    _link(link, noise1.outputs["Fac"], mul2.inputs[0])
    _link(link, noise2.outputs["Fac"], range2.inputs["Value"])
    _link(link, noise3.outputs["Fac"], range3.inputs["Value"])
    _link(link, mapping.outputs["Vector"], vor.inputs["Vector"])
    _link(link, mapping.outputs["Vector"], noise1.inputs["Vector"])
    _link(link, mapping.outputs["Vector"], noise2.inputs["Vector"])
    _link(link, mapping.outputs["Vector"], noise3.inputs["Vector"])
    _link(link, coord.outputs["Object"], mapping.inputs["Vector"])

    # Set displacement and add material. Material.displacement_method moved from
    # mat.cycles in older versions to the material itself.
    if not _try_set(mat, "displacement_method", "DISPLACEMENT"):
        cycles_mat = getattr(mat, "cycles", None)
        if cycles_mat is not None:
            _try_set(cycles_mat, "displacement_method", "DISPLACEMENT")
    obj.data.materials.append(mat)


# Properties
class SnowSettings(PropertyGroup):
    coverage: IntProperty(
        name="Coverage",
        description="Percentage of the object to be covered with snow",
        default=100,
        min=0,
        max=100,
        subtype='PERCENTAGE'
    )
    height: FloatProperty(
        name="Height",
        description="Height of the snow",
        default=0.3,
        step=1,
        precision=2,
        min=0.1,
        max=1
    )
    vertices: BoolProperty(
        name="Selected Faces",
        description="Add snow only on selected faces",
        default=False
    )


#############################################################################################
classes = (
    REAL_PT_snow,
    SNOW_OT_Create,
    SnowSettings
)


# Register
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.snow = PointerProperty(type=SnowSettings)


# Unregister
def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.snow


if __name__ == "__main__":
    register()
