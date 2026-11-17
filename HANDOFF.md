# Banana — Handoff

Read this first when picking the project up in a new chat. Update it at the end of every session.

## What Banana is
A Blender add-on (target Blender 4.1+, tested headless on 4.2) for building Halo 3 maps for the
Halo 3 Editing Kit (H3EK). Modeled on the Titamas Online Blender add-on, but its own tool with its
own settings. Each BSP is a collection; Banana validates it and exports it as a `.ass` file that
Tool imports with `tool structure`. Named after Halo's monkey-named editors.

## Status
**Phase 1 done (v0.1.1):** project settings, BSP collection template, validation, .ASS exporter,
optional Tool run. Headless tests pass (`tests/run_tests.py`). **Verified in real Tool:** a cube
exported by Banana imported with Tool and loaded in Sapien/game (2026-11-17). Next: phase 2.

**Phase 3 done (v0.4.0):** terrain tiles, height brush (Blender sculpt, X/Y locked, border mask),
Match Borders, blend-map painting + RGBA TIFF bake. Tests: `tests/test_phase3.py`. Not yet tried in
the real UI/Tool — user will test phases 2 and 3 together (sky shells haven't been tried yet).
Next: phase 4 (prop library + painting + name sync).

**Phase 2 done (v0.3.3: crash fix + per-BSP seam names):** sky shells with automatic seams, border alignment check, seam mirroring
with auto-sync, seam pair validation, live per-BSP limit meters (+ optional viewport overlay).
Tests: `tests/test_phase2.py`. Next: phase 3 (height brush + blend-map painting).

**Rig Convert added (v0.2.0)** (parked by the user for now; level editor is the focus) — see the section below. Tests: `tests/test_rig.py`. Waiting on the
user's real Reach + Halo 3 Elite node lists to tune auto-matching.

## Build plan (agreed with the user)
1. ✅ Exporter + validation (prove the .ASS writer in Tool with a sealed box room)
2. ✅ Sky shell generator, `+seam` generation/mirroring between BSPs, per-BSP limit meters
   (TODO later: calibrate meters from Tool's output)
3. ✅ Height brush (with border lock) + terrain blend-map painting
4. Prop library from a folder of GLBs (thumbnails, import once as master), prop painting into a
   sub-collection under the master's collection (link new objects straight to the target
   collection — the Titamas add-on's bug was linking to the active collection), shared mesh data,
   name sync: base name + flags stored on the master, ticking a flag renames every copy
   (e.g. `%tree` -> `%*tree`)
5. Modular kit pieces: sockets with profiles, snapping, smart merge at export on a temp copy
   (delete caps on connected sockets, weld loops, remove interior faces, fix T-junctions,
   re-validate), unconnected caps keep a configurable seal material (black/grey constant shader,
   auto planar UVs, per-socket override incl. `+sky`), optional auto `+portal` at connected
   sockets, boolean fallback for odd joins (warns + validates)
6. Add Water (controller with linked surface plane + physics volume, shoreline overlap, surface
   density, fit-to-basin raycast, flow arrow), design volume presets (soft kill, soft ceiling,
   slip surface — NOT weather polys, Halo 3 dropped them), collision blockers, player scale
   capsule + vehicle width guides, batch export, export snapshots, Remove Duplicate Materials
   button (name duplicates + optional identical node setups, preview first, also images),
   shader tag existence check, material flag checkboxes, pie menu, build-style presets
- The user does **not** want a walkable slope overlay.

## Phase 3 details (banana/terrain.py, banana/blendmap.py)
- **Tiles:** `New Terrain Tile` makes a quad grid (normals up) in the active BSP's structure with
  custom prop `banana_tile` = {size_x, size_y, spacing}. "Next to Selected Tile" places it edge to
  edge on a side, forces the shared size/spacing, and copies the neighbor's border heights, so the
  border matches exactly even across BSPs (then Build Sky Shells makes the seam).
- **Height brush:** enters Sculpt Mode, sets `tool_settings.sculpt.lock_x/lock_y` (all brushes
  only change height), writes a border mask to the `.sculpt_mask` attribute (1 on the border,
  fading over N rings), switches brush via `wm.tool_set_by_id("builtin_brush.X")` (4.1/4.2) or
  `brush.asset_activate` (4.3+) and sets `sculpt_plane = 'Z'`. Brush switching needs a real 3D
  view (untested headless). `Done Sculpting` restores the locks and clears the mask.
- **Match Borders:** border vertices with the same XY in different BSPs get the same height
  (active tile wins, else average).
- **Blend map:** per BSP, terrain = structure objects using the BSP's `terrain_material` (shader
  name). `Set Up` fits a fixed blend area once (stored on the BSP so painting never shifts when
  tiles are added; refit button moves paint), writes top-down `blend_uv` (warns if not UV 0),
  creates 3 grayscale paint images `<bsp>_layer2..4` (packed; re-packed on save via save_pre),
  and BANANA_ preview nodes inside the terrain material (layer colors, lerp chain).
  Bake (Save Blend Map, and automatically on export once set up):
  A = w4, B = w3(1-w4), G = w2(1-w3)(1-w4), R = (1-w2)(1-w3)(1-w4) -> straight-alpha RGBA TIFF at
  `<level>\bitmaps\<bsp>_blend.tif`. Channel order R/G/B/A = layers 1-4 is from a community
  write-up (blend_channel 1/2/4/8); confirm against a real shader_terrain tag.
- To verify for real: brush switching in 4.1 UI, blend map import via Tool bitmaps + a
  shader_terrain using it, terrain tiles + shells + seams through Tool.

## Phase 2 details (banana/sky.py, banana/limits.py)
- **Sky shell:** per BSP, takes the terrain = structure objects that aren't shells or mirrored
  seams, welds them, chains the open border into loops, and builds vertical walls from each border
  edge up to the scene-wide Sky Height (auto = 30 m above the highest terrain in any BSP) plus a
  triangulated top cap, as object `<bsp>_sky_shell` (custom prop `banana_shell`, replaced on
  rebuild). Only the largest loop is sealed; other loops (holes) are reported as errors.
  Orientation copies the terrain's: each wall triangle walks its border edge opposite to the
  terrain face, the cap opposite to the walls, so terrain normals must point up (into play).
- **Seam naming (confirmed by the user from c20, 2026-11-17):** the seam material name must match
  the BSP it ends up in, e.g. `+seam:030_BSP_000`. So the two halves of a pair have *different*
  names (`+seam:bsp_a` in bsp_a, `+seam:bsp_b` in bsp_b). A shared name (`+seam:hall` on both
  sides) gave "unpaired seam" in Sapien. Banana now rewrites every `+seam...` material to
  `+seam:<BSP file name>` on export, so the Blender material name doesn't matter; pairing is
  validated by geometry (identical triangles in exactly one other BSP, opposite facing).
- **Automatic seams:** a border edge that exactly matches another BSP's border edge (rounded to
  1e-4) makes `+seam` walls. Wall triangles always use the
  diagonal from the lexicographically lower vertex, so both BSPs produce identical triangles;
  each side faces into its own BSP (Microsoft docs: matching seams need the same triangulation,
  coincident vertices, opposite normals, normals pointing into the BSP).
- **Border alignment check:** border vertices within ~0.5 m of another BSP's border but not
  equal are reported (no seam is made there) — this is the "edge matching" safety net.
- **Mirror Seam to BSP:** copies a `+seam:<name>` object into another BSP as `<name>_mirror`
  (custom prop `banana_seam_source` = ID pointer to the original). Rebuilt from the original's
  evaluated loop triangles, winding flipped, world-baked, before every validate/export.
- **Seam validation:** every seam triangle needs an identical triangle in exactly one other BSP,
  facing the other way.
- Tool order for seams (Microsoft docs): run `structure-seams` *before* importing the BSPs;
  re-running it invalidates seams in already-imported BSP tags.
- Not done: Microsoft docs mention `+seam:a` (facing out) / `+seam:b` (facing in) naming for a BSP
  *inside* another BSP. Ask the user if they need nested BSPs before building it.
- **Meters:** per-object cache of evaluated tris/verts/materials/bbox; depsgraph handler marks
  changed objects dirty, a timer recounts after 0.6 s of quiet; results live in a Python dict
  (not scene props, to avoid update loops). Budgets in `scene.banana_limits`; defaults are
  placeholders (no published Halo 3 limits found), saveable to `<config>/banana/limits.json`.
  Overlay: SpaceView3D POST_PIXEL blf text, toggle in the Limits panel.
- ✅ Verified in Tool/Sapien (2026-11-17): two rooms joined by a mirrored doorway seam pair up
  (after the per-BSP seam naming fix).
- Still to verify: a separate sky shell object seals together with the terrain (coincident
  vertices across objects); terrain seams from Build Sky Shells.

## Rig Convert (side tool inside Banana)
Purpose: put a Reach character body (e.g. Elite) onto the Halo 3 skeleton so Halo 3's existing
collision, physics and animations work, without regrouping vertices by hand.
- User's workflow: import H3 render model + rig and the Reach body + rig as **JMS with the existing
  Halo Blender toolset (general-101)**, run Rig Convert, delete the H3 body, re-add armor
  permutations and parent them themselves, export JMS with the same toolset. Only the render
  model is replaced; regions and bones must match H3. The user handles permutations.
- Meshes are edited **in place** (vertex groups, armature modifier, parent only) so the importer's
  region data survives export.
- Steps: auto bone map (prefix/side/digit-insensitive + same-side fuzzy match, editable table,
  JSON presets in Blender config `banana/rig_presets`) -> per bone mode MAP / MERGE (extra bone ->
  nearest mapped parent) / COPY (take weights from the H3 body by nearest surface) -> conform the
  shape to the H3 rest pose (joint positions, optionally limb directions) -> normalize + trim to
  max influences (default 4) -> rebind to the H3 rig, hide the Reach rig.
- Test Pose toggles bends on keyword bones (upperarm, forearm, thigh, calf, jaw, head...).
- TODO once real node lists arrive: check auto-map hits, adjust PREFIXES/SIDES in `rig.py`,
  ship a built-in "Reach Elite -> H3 Elite" preset; confirm H3's real influence limit.

## Layout
```
banana/__init__.py     bl_info + register
banana/props.py        add-on prefs (H3EK path, tool exe), scene settings, collection roles
banana/bsp.py          BSP template + role-based object gathering
banana/ass_writer.py   plain-Python ASS v7 model + writer (no bpy)
banana/export.py       bpy -> ASS (numpy), paths, Tool runner, export operators
banana/validate.py     validation + red BANANA_PROBLEMS overlay
banana/ui.py           View3D sidebar > Banana; Outliner collection menu "Banana Role"
banana/sky.py          sky shells, seams, seam mirroring + checks
banana/limits.py       live limit meters, budgets, viewport overlay
banana/terrain.py      terrain tiles, height brush, border mask, match borders
banana/blendmap.py     blend-map UVs, paint layers, preview nodes, TIFF bake
banana/rig.py          Rig Convert (bone map, weights, conform, rebind, test pose, presets, panel)
tests/run_tests.py     headless map/export tests (needs a Python with the bpy module)
tests/test_rig.py      headless Rig Convert tests
tests/test_phase2.py   headless sky shell / seam / meter tests
tests/test_phase3.py   headless terrain / blend map tests
tools/build_zip.py     builds dist/banana-<version>.zip for Install Add-on
```

## Lessons learned (bugs that reached the user)
- **v0.3.0 crash:** Mirror Seam stored materials taken from an *evaluated* object
  (`eval_obj.material_slots[i].material` is the depsgraph's temporary copy). The next evaluation
  (Validate) freed it -> Blender crashed. Rule: never store evaluated IDs on real data; use
  `.original`. Headless tests don't redraw, so they didn't catch it — there's now a regression
  check (`is_evaluated`) in `tests/test_phase2.py`.
- Also avoid creating/removing datablocks while holding evaluated objects (append with
  `bm.from_mesh` + `bmesh.ops.transform` instead of `mesh.copy()`), and read evaluated meshes via
  `to_mesh()`/`to_mesh_clear()` rather than `eval_obj.data` (Edit Mode safety).
- Installing a new zip over a running Blender kept old submodules (the user's Sky & Seams box was
  missing). `__init__.py` now reloads all submodules when Blender reloads the package.

## Conventions in the code
- A BSP is a collection with `collection.banana.role == 'BSP'`; children carry roles
  STRUCTURE / INSTANCES / DESIGN / PORTALS. Nested collections with role NONE inherit their
  parent's role (painted-prop sub-collections rely on this).
- Structure, design and portal objects are **baked** (world transform x scale into vertices,
  identity instance) so any transform works. Mirrored transforms flip winding.
- Instance objects that share mesh data, materials and have no modifiers share **one ASS object**
  (one instance definition); each placement is an ASS instance with quaternion (x,y,z,w),
  translation x scale, and a single uniform scale (Halo keeps X only).
- Instance names: `%` prefix added if missing; Blender `.001` becomes `_001`.
- Material names: `.001` suffix stripped; plain `+sky` becomes `+sky<BSP sky index>`;
  everything in a PORTALS collection exports as `+portal`.
- Unique ids live in the object's `banana_uid` custom property; duplicates get re-rolled.
- Scale: default Real Meters (1 m = 100/3.048 = 32.81 ASS units, since 1 world unit = 10 ft and
  = 100 ASS units). Also JMS units 1:1 and Custom.
- Output: `<H3EK>\data\levels\<multi|solo>\<level>\structure\<bsp>.ass`, design pieces in
  `structure_design\<bsp>.ass` (folder name confirmed by the user; or the same file if Design
  Export = Same File).
- Tool: `tool structure <path relative to data>` / `structure-design`, cwd = H3EK root; output
  goes to the "Banana Tool Log" text block. Blocking call for now.

## Format facts (sources: general-101 MIT toolset reading, c20 wiki, Microsoft H3EK docs)
- ASS v7 layout: HEADER, MATERIALS (name, variant "", lighting-string count), OBJECTS (MESH:
  verts = pos, normal, color, node count, uv count + u v w; tris = material + 3 indices),
  INSTANCES (instance 0 = "Scene Root", object -1, uid -1, parent -1; others parent 0).
- Special materials: `+sky`/`+skyN`, `+portal`, `+seamsealer`, `+seam:<name>` (identical
  geometry incl. triangulation on both BSPs), `+soft_ceiling:<name>`, `+soft_kill:<name>`,
  `+slip_surface:<name>` (faces > 35°), `+weatherpoly` deprecated.
- Material symbols go at the **end** of the name (`%` two-sided, `!` render only, `@` collision
  only, `'` water surface, ...). Lowercase, max 32 chars, avoid trailing digits.
- Instance prefixes after `%` (Microsoft docs): `>` single probe, `!` per-pixel, `?` per-vertex,
  `(n)` lightmap res, `@a-b` fade pixels. The user uses `%*` for "no collision" — confirm in Tool.
- Water (c20): surface in structure ASS with `'` material + 4 UV channels; physics in
  structure_design folder as `~water_physics00` with `#water_direction00` empty child (X = flow).
  The user says the same ASS can now hold both — Design Export = Same File supports that.
- One sky index per cluster; MP scenarios shouldn't use multiple BSPs.

## To verify in real Tool (next session)
- [x] Box room imports with `tool structure` and loads in Sapien (2026-11-17, via Osoyoos + Tool)
- [ ] Instance names with `_001` suffixes import fine; `%*` behaves as no-collision
- [ ] Design in the same ASS works as the user expects
- [ ] Real meters scale feels right next to a Spartan

## How to test locally
`pip install bpy` only ships for specific Python versions; in the cloud workspace a Python 3.11
venv with `bpy` 4.2 works: `python tests/run_tests.py`. Build the zip with
`python tools/build_zip.py`.
