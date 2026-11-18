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

## Sky shells, seams and limits
- **Build Sky Shells** (BSPs panel) seals each BSP's terrain border with `+sky` walls and a top cap
  at the shared Sky Height. Where two BSPs' terrain borders meet exactly, those walls become a
  matching seam pair automatically. Borders that almost meet are reported.
- The strip of sky cap along the top of each seam uses `+seamsealer` (BSPs > Sky & Seams > Seam Top),
  so the seam ends on real geometry instead of `+sky`. Clear the field to go back to plain `+sky`.
- Each BSP gets its own seam material, starting as `+seam`. Rename it yourself (BSPs > Sky & Seams
  > Seam name); Banana keeps your name through rebuilds and exports it as is.
- **Mirror Seam to BSP** copies a selected `+seam` object (e.g. a doorway between two BSPs)
  into the other BSP, facing the other way; the copy re-syncs on every export.
- **Limits** shows live meters per BSP (triangles, vertices, instances, materials, portals, world
  extent). Edit the budgets under Limits > Budgets and save them as your defaults.

## Terrain (Banana > Terrain)
- **New Terrain BSP** makes a new BSP with a flat terrain tile and its own sky. With a terrain
  selected, the new one can go right next to it with a matching edge.
- Select two terrains (in two BSPs): **Match Edge** snaps the other edge onto the active one and
  blends the heights across it (Blend Rows sets how wide the ramp is, in the Adjust Last Operation
  panel); **Generate Seam** does the same and turns the edge into a seam. Skies follow automatically.
- The Set Height brush paints straight across joined edges; outer edges stay locked. **Rebuild All Skies** after
  painting terrain higher than the sky.
- **Paint Height** (Set Height brush): type a height and paint toward it. Ctrl+click picks the
  height under the cursor, [ ] change the radius, right-click or Esc to finish. Borders stay locked.
- **Blend Map**: set the BSP's terrain shader name and press Set Up. Give each layer a color or a
  preview texture (viewport only). **Paint Blend** paints the chosen layer (layer 1 = base) or
  blurs, with Opacity. Ctrl+Z inside the brush undoes the last stroke. **Save Blend Map** (and every
  export) writes `bitmaps\<bsp>_blend.tif` with layers 1-4 in R/G/B/A.

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
