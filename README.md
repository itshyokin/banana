# Banana

A Blender add-on for building Halo 3 maps for the Halo 3 Editing Kit (H3EK): organize each BSP as a
collection, validate it, and export it as a `.ass` file ready for `tool structure`.

## Install
1. Download `banana-<version>.zip` (or build it with `python tools/build_zip.py`).
2. Blender > Edit > Preferences > Add-ons > Install..., pick the zip, tick **Banana**.
3. In the add-on preferences, set your **H3EK Folder**.

## Quick start
1. View3D sidebar (N) > **Banana** > Project: set the level name and type.
2. BSPs > **+** to create a BSP. It comes with `structure`, `instances`, `design` and `portals`
   collections.
3. Model sealed level geometry in `structure` (use `+sky` on faces that should show the sky — it
   exports as `+sky<Sky Index>`), props in `instances` (linked duplicates share one instance
   definition), soft ceilings/kill zones in `design`, portal planes in `portals`.
4. **Validate** — problems are listed and drawn in red in the viewport.
5. **Export BSP** (optionally tick *Run Tool After Export*; Tool output lands in the
   "Banana Tool Log" text).

You can also give any collection a role from the Outliner: right-click > Banana Role.

## Rig Convert
Banana > **Rig Convert** moves a body skinned to one Halo skeleton (e.g. a Reach Elite) onto
another (e.g. the Halo 3 Elite):
1. Import both models with your JMS importer.
2. Pick the **Reach Rig**, the **Halo 3 Rig**, and optionally the **Halo 3 Body**.
3. **Auto Map**, fix any rows in the table (Map / Merge into parent / Copy weights from the Halo 3 body),
   and save it as a preset for next time.
4. Select the Reach body meshes (or select nothing to use every mesh on the Reach rig) and press
   **Match to Halo 3**. Use the pose button to bend the limbs and check deformation.

See `HANDOFF.md` for the roadmap and technical notes.
