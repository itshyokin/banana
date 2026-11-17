# Banana — Handoff

Read this first when picking the project up in a new chat. Update it at the end of every session.

## What Banana is
A Blender add-on (target Blender 4.1+, tested headless on 4.2) for building Halo 3 maps for the
Halo 3 Editing Kit (H3EK). Modeled on the Titamas Online Blender add-on, but its own tool with its
own settings. Each BSP is a collection; Banana validates it and exports it as a `.ass` file that
Tool imports with `tool structure`. Named after Halo's monkey-named editors.

## Status
**Phase 1 done (v0.1.1):** project settings, BSP collection template, validation, .ASS exporter,
optional Tool run. Headless tests pass (`tests/run_tests.py`). **Not yet tested in real Tool** —
first job next session is to read the user's Tool output from the box-room test.

**Rig Convert added (v0.2.0)** — see the section below. Tests: `tests/test_rig.py`. Waiting on the
user's real Reach + Halo 3 Elite node lists to tune auto-matching.

## Build plan (agreed with the user)
1. ✅ Exporter + validation (prove the .ASS writer in Tool with a sealed box room)
2. Sky shell generator, `+seam` generation/mirroring between BSPs, per-BSP limit tracker meters
   (live, incremental recount after strokes pause; editable limits file; calibrate from Tool output)
3. Height brush (with border lock for seam/sky-shell verts) + terrain blend-map painting
   (Halo 3 terrain shader blends 4 materials via an RGBA **blend map bitmap**, so paint into an
   image on 0–1 UVs; check restrictions on the 4th material)
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
banana/rig.py          Rig Convert (bone map, weights, conform, rebind, test pose, presets, panel)
tests/run_tests.py     headless map/export tests (needs a Python with the bpy module)
tests/test_rig.py      headless Rig Convert tests
tools/build_zip.py     builds dist/banana-<version>.zip for Install Add-on
```

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
- [ ] Box room imports with `tool structure` (user runs it, shares log)
- [ ] Instance names with `_001` suffixes import fine; `%*` behaves as no-collision
- [ ] Design in the same ASS works as the user expects
- [ ] Real meters scale feels right next to a Spartan

## How to test locally
`pip install bpy` only ships for specific Python versions; in the cloud workspace a Python 3.11
venv with `bpy` 4.2 works: `python tests/run_tests.py`. Build the zip with
`python tools/build_zip.py`.
