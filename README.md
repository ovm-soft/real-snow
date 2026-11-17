# Real Snow (Blender 5.x port)

A Blender add-on that adds snow on top of selected objects.

This is a modified copy of [Real Snow](https://gitlab.com/marcopavanello/real-snow)
by Marco Pavanello and Drew Perttula, updated to run on Blender 4.2 up to 5.2.
All credit for the add-on itself goes to the original authors.

## Changes from the original

- Shader nodes are configured by socket name instead of index, because the
  Principled BSDF socket order differs between Blender versions.
- `Material.use_nodes` is no longer set on Blender 5.0+ (deprecated, no effect).
- Version-dependent Cycles and material properties are set defensively.
- New **Max Angle** setting: the largest angle between a face and straight up
  that still receives snow (default 61°, the original behaviour). Raise it to
  cover steep slopes or walls.
- **Selected Faces** now reads the selection from the original mesh, and a popup
  explains what to do when no snow can be added (nothing selected, faces too
  steep, flipped normals, or modifiers that change the face count).
- Small fixes: missing `()` on `bm_obj.free`, nodes removed while iterating,
  and a warning when no mesh object is selected.

## Install

Download `real_snow-1.3.6.zip` and in Blender open
Preferences → Get Extensions → Install from Disk.

## Use

Open the **Real Snow** tab in the 3D Viewport sidebar (N), select mesh
objects and click **Add Snow**.
Or go to Edit Mode, select top faces, switch back to Object Mode, check Selected Faces and click **Add Snow**

## License

GNU General Public License v3.0 or later. See `LICENSE`.
