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

**v0.8.0 (user feedback):** blend painting moved to **vertex colors in Blender's own Vertex Paint
mode**, like the Titamas add-on (the image-based Banana blend brush updated slowly and only
redrew on navigation). Every terrain BSP now gets its **own terrain material** `<bsp>_terrain`
(each BSP needs its own shader_terrain/blend map; the shared "terrain" material also made the
second BSP's preview overwrite the first's). Make Unique fixes older files; Validate warns.
See "Blend map (v0.8.0)" below.

**Phase 3 done (v0.5.0, reworked after user feedback):** every terrain is its own BSP with its
own sky shell; Match Edge + Generate Seam for two selected terrain BSPs; custom Set Height brush;
custom blend brush (paint/blur/opacity) with per-layer preview textures; RGBA TIFF bake.
Tests: `tests/test_phase3.py`. Not yet tried in the real UI/Tool — the user will test phases 2 and 3
together. Next: phase 4 (prop library + painting + name sync).

User feedback that shaped v0.5.0 (keep these decisions):
- The height brush must be a **Set Height** brush (type a height, paint toward it), like the
  Titamas add-on — NOT raise/lower/smooth/flatten/clay (Blender's sculpt mode already has those;
  the sculpt-based buttons were removed).
- Blend painting needs opacity and a blur; layers show optional preview textures, export stays
  plain RGBA.
- Adding a terrain = adding a BSP, with a skybox over it. Two selected terrain BSPs get Match Edge
  and Generate Seam buttons.

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

## Phase 3 details (banana/terrain.py, banana/brush.py, banana/blendmap.py)
- **New Terrain BSP:** creates a BSP (`terrain_000`, ...), a quad grid tile (normals up, custom
  prop `banana_tile` = {size_x, size_y, spacing}, material = the BSP's terrain shader name) and a
  plain sky shell (`build_shell(..., neighbors=[])`, so no seam yet). "Next to Selected Terrain"
  places it edge to edge on a side, forces the shared size/spacing and snaps the edge to the
  neighbor (`match_edge`).
- **Match Edge (v0.7.0):** two terrains selected in two BSPs (clicking anything in a terrain BSP
  counts). (1) Seam plans for both BSPs are captured *first* (`_plan_seams`; after heights move,
  old seams can't be found). (2) Snap: the other one's border verts snap (x, y, z) to the active
  one's nearest border vertex (XY KD-tree, distance capped at 40% of spacing). (3) Blend Heights
  (default on, user asked for it because the locked edge left a valley between the BSPs):
  `blend_edge` sets each shared edge vertex to the average of the first free row on each side
  (row `rows+1`) and ramps `rows` rows on each side linearly to it; the edge's two end vertices
  stay put (they may be corners shared with other BSPs). (4) Both skies are rebuilt with their
  planned seams (`_rebuild`).
- **Generate Seam:** same as Match Edge, plus the pair is added to each side's seam partners.
- **Sky height (v0.7.0):** auto height only ever goes *up* (`raise_sky_if_needed`); when it does,
  every terrain sky is rebuilt with its seams so all tops stay level. Rebuilding one BSP's sky can
  never lower it. Rebuild Sky Shells (all) may settle on any height since it rebuilds everything.
- **Terrain brush (`banana.terrain_brush`, modal, brush.py):** raycasts only terrain objects
  (sky shells don't block it), draws a circle cursor (gpu POST_VIEW), header shows keys.
  HEIGHT: `height_dab` moves verts within the radius (XY distance) toward the target world Z with
  strength * smooth falloff * (1 - border mask); X/Y never change; Ctrl+click samples the height;
  one undo step per stroke (`bpy.ed.undo_push`); warns if terrain reaches the sky height.
  (The v0.5-0.7 image-based BLEND mode was removed in v0.8.0.) Radius with [ ], navigation
  passes through. When the brush finishes it also raises every sky if the terrain got too tall.
- **Blend map (v0.8.0):** per BSP, terrain = structure objects using the BSP's `terrain_material`
  (default `<bsp>_terrain`). Set Up fits a fixed blend area (tile bounds), writes top-down
  `blend_uv` (UV 0 = what Halo samples the blend map with), and adds a POINT FLOAT_COLOR attribute
  `blend` (linear, so partial strokes keep sums right). Paint buttons enter Vertex Paint and set
  the brush color: R = layer 1, G = layer 2, B = layer 3, black = layer 4
  (w4 = max(0, 1 - (r+g+b)); weights normalized). Blur = Blender's Blur vertex brush; strength,
  radius and falloff are Blender's. Fill sets a whole terrain to one layer. Preview nodes
  (BANANA_*) read the color attribute and weight each layer's flat color or tiled preview texture;
  with "Show Textures While Painting" the view switches to Material Preview. Bake: per tile grid
  (vertex order = make_tile row-major), bilinear interpolation to Blend Map Size over the area ->
  straight-alpha RGBA TIFF `<level>\bitmaps\<bsp>_blend.tif` (R/G/B/A = layers 1-4; channel order
  from a community write-up). Non-tile meshes are skipped by the bake. v0.5 image layers
  (`<bsp>_layer2..4`) are converted into vertex colors the first time Set Up runs.
- To verify for real: the modal brush in the 4.1 UI (cursor drawing, undo), terrain BSPs + shells
  + seams through Tool, blend map through Tool bitmaps + a shader_terrain.

## Phase 2 details (banana/sky.py, banana/limits.py)
- **Sky shell:** per BSP, takes the terrain = structure objects that aren't shells or mirrored
  seams, welds them, chains the open border into loops, and builds vertical walls from each border
  edge up to the scene-wide Sky Height (auto = 30 m above the highest terrain in any BSP) plus a
  triangulated top cap, as object `<bsp>_sky_shell` (custom prop `banana_shell`, replaced on
  rebuild). Only the largest loop is sealed; other loops (holes) are reported as errors.
  Orientation copies the terrain's: each wall triangle walks its border edge opposite to the
  terrain face, the cap opposite to the walls, so terrain normals must point up (into play).
- **Seam naming:** c20 (found by the user) says the seam material name must match the BSP name,
  e.g. `+seam:030_BSP_000`; the doorway test paired once each half was named after its own BSP.
  Since v0.6.0 the user names seams by hand (see Lessons learned); Banana no longer renames them.
- **Seams are only made on request** (Generate Seam, or `build_sky_shell(auto_seams=True)`): a
  border edge that exactly matches the partner BSP's border edge (rounded to 1e-4) gets walls with
  the BSP's own seam material (user-named). Rebuilding shells keeps existing seams only. Wall triangles always use the
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
- ✅ Verified (2026-11-17, v0.8.0): Set Height brush, vertex-paint blending with preview
  textures, per-BSP terrain materials and the baked blend map all work in Blender and in-game.
  Open item: Sapien reported "triangle #1382 was degenerate (this may cause open edges)" — likely
  long sliver triangles from the sky shell's BEAUTY-triangulated cap (many collinear border
  vertices). Proposed fix: build the cap for tile terrains as a grid of quads at sky height (same
  XY as the terrain grid), and tighten Validate's degenerate check to catch slivers.
- ✅ Verified (2026-11-17): two terrain BSPs with Generate Seam + blended edge load and connect,
  once the Tool order was right. Possible next step offered to the user: make "Run Tool After
  Export" run structure-seams first and then re-import every BSP automatically.
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
banana/terrain.py      terrain BSPs, Match Edge, Generate Seam, Terrain panel
banana/brush.py        modal Set Height brush (+ dab math, border mask, shared-edge handling)
banana/blendmap.py     vertex-color blend painting, per-BSP terrain material, preview nodes, TIFF bake
banana/rig.py          Rig Convert (bone map, weights, conform, rebind, test pose, presets, panel)
tests/run_tests.py     headless map/export tests (needs a Python with the bpy module)
tests/test_rig.py      headless Rig Convert tests
tests/test_phase2.py   headless sky shell / seam / meter tests
tests/test_phase3.py   headless terrain BSP / brush math / blend map tests
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
- **v0.7.1 — "unmatched seam" along the seam's *top* edge in Sapien** (seam walls run up to the
  sky cap, so their top edge only touched `+sky` faces). c20: a seam must fully seal the level geo
  and match the BSP's edges; `+seamsealer` seals open edges with the sky rendering through it.
  Theory being tested: +sky doesn't count as level geo, so the cap triangles along each seam's top
  edge now use `+seamsealer` (scene setting `seam_top_material`, default "+seamsealer", empty =
  old behavior). `naming.is_seam()` excludes +seamsealer from every seam check (its name starts
  with "+seam"!). **Result (2026-11-17):** the "unmatched seam" was a stale structure_seams tag; it went away with
  the right Tool order (empty structure folder -> Export All -> structure-seams -> import *both*
  BSPs). Terrain seams now work in Sapien. Whether +seamsealer at the seam top was also needed is
  unknown (it was in place when it worked; leave it on). c20 also says both halves of a pair must have the
  *same* name (contradicts the per-BSP naming that worked in the doorway test) — names are manual.
- **v0.6.0 — seams are named by the user, not by Banana.** Seams still came through unpaired for
  the user, so at their request automatic seam naming was removed entirely. Generate Seam gives
  each BSP its own seam material (`bsp.banana.seam_material`), created as `+seam` / `+seam.001`;
  the user renames it (sidebar: BSPs > Sky & Seams > Seam name). Rebuilds reuse that material, so
  the name sticks. Mirror Seam gives the mirrored side its own copy of the material, and re-syncs
  keep whatever it's been renamed to. Export writes material names as they are (only `.001`-style
  suffixes stripped). Validate warns while a seam is still called plain `+seam`. Seam pairing is
  still validated by geometry. Open question for the user: what naming finally pairs in Tool.
- **v0.5.4 (root cause of the extra unpaired seam):** the sky shell was often what got clicked,
  so New Terrain didn't see a terrain selected, silently unticked "Next to Selected" and put the
  new tile at the origin *under* the first one. Generate Seam then rebuilt shells against *every*
  touching BSP, so the hidden duplicate turned the first terrain's whole outer wall into a seam
  with no partner. Fixes: any object in a terrain BSP stands for its terrain (`terrain_for`);
  shells are `hide_select`; the New Terrain dialog shows which terrain it's next to; Generate Seam
  seams only the selected pair + BSPs it's already seamed to (`existing_seam_partners`); Rebuild
  Sky Shells keeps exactly the existing seams (`auto_seams` off by default); overlapping terrains
  are refused by Generate Seam and reported by Validate (`check_overlaps`).
- **v0.5.2:** user saw an extra "unpaired seam" next to a working terrain seam. A simulated
  workflow (hills near the edge, Generate Seam, Export All) gives byte-identical seam triangles in
  both .ass files, one seam material per side, no duplicates — so suspect leftover .ass files in
  the structure folder or old BSPs still in the scene (waiting on the user's file list +
  structure-seams log). Changes: each BSP's shell now uses its own `+seam:<bsp>` material in
  Blender (was one shared `+seam` material, which the user renamed by hand), and Match Edge /
  Generate Seam snap distance is capped at 40% of the vertex spacing.
- **v0.5.0:** the brush called `bpy.ed.undo_push` (doesn't exist) -> error popup on every stroke.
  Correct call is `bpy.ops.ed.undo_push(message=...)`. The modal now catches any error and ends
  cleanly (removes its draw handler) instead of leaving a stuck cursor. UI-only code paths
  (modal operators) aren't exercised by the headless tests — read them extra carefully.
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
