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
- **Blend Map**: each terrain BSP has its own terrain shader material (`<bsp>_terrain`; **Make
  Unique** fixes terrains that share one). Press a **Paint** button to paint that layer in Blender's
  Vertex Paint mode: red = layer 1, green = 2, blue = 3, black = 4. **Blur** softens; radius and
  strength are Blender's brush settings (F / Shift+F). Give each layer a color or a preview texture
  (shown in Material Preview while painting). **Save Blend Map** (and every export) writes
  `bitmaps\<bsp>_blend.tif` with layers 1-4 in R/G/B/A.

## Props (Banana > Props)
- Pick a folder of `.glb`/`.gltf` models and press refresh: each becomes a prop. A `.png`/`.jpg`
  with the same name next to a model is used as its thumbnail.
- Set the prop's name and flags (`*` no collision, `!` per-pixel, `?` per-vertex, `>` single probe,
  plus any other flags and a suffix like `(4)` or `@30-20`); the panel shows the exact Halo name.
  Changing them renames the main object, every copy and the collections.
- **Add to BSP** puts the main object at the 3D cursor, inside `instances/<name>`.
- **Paint Props** scatters copies on terrain and structure (per dab count, minimum spacing, scale
  range, random rotation, align to slope, sink). Ctrl+click erases. Copies always go into the
  `<name>_painted` collection of the BSP they land on and share one mesh, so each BSP exports them
  as one instance definition.

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
