# Turntable — Specification

Status: draft for review. Source material: `IDEA.md`, `docs/reference/poc.html`,
`docs/scripts/*.py`, `public/vehicles/countryman-s/`.

Contents

1. Goals and non-goals
2. What the POC actually does (baseline)
3. Vehicle config schema
4. Rendering approach (Canvas 2D vs WebGL)
5. Frame loading strategy
6. Interaction
7. Background system
8. Embedding
9. Asset pipeline
10. POC limitations to design out
11. Phased plan
12. Open questions

---

## 1. Goals and non-goals

**Goals**

- One viewer that works for any vehicle, given frames, label-map masks and a config file.
  No vehicle-specific code.
- Live recolouring of named parts that keeps the render's shading, with the same look as the POC.
- Smooth on mid-range phones: drag at 60 fps, swatch change visible on the next frame.
- Two delivery modes: a standalone page on our domain, and an embed for dealer and campaign sites.
- A repeatable asset pipeline that doesn't depend on hand-placed boxes.

**Non-goals (for now)**

- Real-time 3D (three.js and glTF). Pre-rendered frames are the product. They look better than
  real-time 3D for the same effort, and CGI studios already deliver them.
- Synthesising views between rendered angles (optical flow, NeRF). We fix sparse frames with
  more renders, not with maths (see §6.4).
- Pricing, finance or lead capture. The viewer emits events; host pages own commerce.

---

## 2. What the POC actually does (baseline)

Read this before changing any behaviour. The phase-1 parity target is defined against it.

| Area | POC behaviour |
|---|---|
| Frames | 12 angles: 0, 30, 45, 90, 135, 150, 180, 210, 225, 270, 315, 330. Each is a 1600×747 RGBA image, base64-inlined into one 1.5 MB HTML file. |
| Angle convention | 0° = head-on front. 90° = side profile, nose to the left of the frame. 180° = rear. |
| Masks | Greyscale label maps, decoded as `Math.round(red / 50)`, so the **embedded** masks store label×50. The masks in `public/vehicles/countryman-s/masks/` store **literal** labels 0–5 (verified by histogram). The two encodings aren't compatible (see §10). |
| Parts | 1 paint, 2 roof, 3 mirror caps, 4 trim, 5 wheel accents. Frame 000 has no label-5 pixels, because the wheels aren't visible from the front. |
| Prep | On load, each frame is drawn to a 2D canvas, then `getImageData` reads the RGB and mask data. The POC computes a 1024-bin luminance histogram per part and takes the median as `ref[k]`. All of this runs on the main thread, frame by frame. |
| Recolour | A per-pixel loop on the CPU, run on demand for the frame being shown. The output canvas is cached per frame. Any change to any part clears the whole cache. A `warm()` loop then re-renders the other frames in the background, one per 16 ms timeout. |
| Display | Two stacked canvases with a 110 ms CSS opacity crossfade. The viewer snaps to the nearest rendered angle by circular distance. |
| Drag | Pointer events. 360° per 1.15× stage width. Dragging right decreases the angle. No inertia. Snaps on release. `touch-action: pan-y`. |
| Keyboard | Stage is focusable. ← calls `stepFrame(+1)`, → calls `stepFrame(-1)`. The ‹ button calls `stepFrame(-1)` and › calls `stepFrame(+1)`, so **← and ‹ rotate in opposite directions**. |
| Scrubber | Invisible native `<input type=range>` over a custom track. Ticks mark the rendered angles. A knob shows the continuous angle. |
| Intro spin | 400 ms after load: 0→360° over 2.6 s, easeInOutQuad. Skipped under `prefers-reduced-motion`. Aborted by drag. |
| Swatches | A radiogroup per part with roving tabindex. Options are original (`null`), a hex value, or a match (`"@<partId>"`). Match resolves recursively. If the matched part is on "original", it uses that part's `orig` hex. Paint's resolved colour drives the CSS `--accent`. |
| Backgrounds | Three CSS presets (studio, dusk, night), plus a local image upload through an object URL with `cover` fit. The car is positioned by fixed CSS (`top:56%`, `width:min(96%,1180px)`). Ground isn't modelled. |

### 2.1 The recolour maths (exact; port this, don't "improve" it in phase 1)

For each pixel `p` whose label `k` is non-zero and whose part has a non-original target colour:

```
toLin(c8)    = sRGB 8-bit → linear (IEC 61966-2-1, 256-entry LUT)
L            = 0.2126·toLin(R) + 0.7152·toLin(G) + 0.0722·toLin(B)         // linear luminance
Lr           = ref[frame][k]      // median L over that part's pixels in this frame
                                  // = (bin + 0.5) / 1023 from a 1024-bin histogram, floor 0.004
t            = toLin(target hex)  // per channel

if L ≤ Lr:                         // shadows and midtones: scale target
    m = L / Lr
    if Lr < 0.03: m = m^0.6        // lift for very dark source parts (black roof/mirrors)
    out = t · m
else:                              // highlights: blend target toward white
    h = ((L − Lr) / (1 − Lr))^0.9
    out = t + (1 − t) · h

RGB'  = TOS[floor(out · 4095)]     // linear → sRGB via 4096-entry LUT
alpha = unchanged; unlabelled pixels and "original" parts = unchanged
```

Properties worth knowing:

- The median maps exactly to the target colour. Each frame computes its own `Lr`, which partly
  self-normalises frames with different lighting.
- Very dark source parts recolour to light colours with little texture left. With `Lr` near
  0.004, the gap between the median and the darkest pixels is only a few code values. The
  `^0.6` lift hides this, but it's the main quality ceiling (see §9.5).
- Hue and saturation of the source pixel are discarded. Only luminance survives, so reflections
  of coloured surroundings are lost on recoloured parts.

---

## 3. Vehicle config schema

### 3.1 Two files per vehicle, split by author

| File | Author | Contents |
|---|---|---|
| `public/vehicles/<id>/vehicle.json` | Human (producer/dev) | Name, parts, palettes, match options, defaults, named views, background default, intro settings. |
| `public/vehicles/<id>/manifest.json` | Asset pipeline (§9), never hand-edited | Image size, frames and angles, file paths, mask encoding, per-frame reference luminance, ground line, shadow mode, poster. |

**Why split:** the pipeline regenerates the manifest every time renders change. If palettes lived
in the same file, a re-run would clobber hand edits, or the script would need merge logic. The
split also lets us re-render a vehicle without touching its palette, and re-palette it without
re-running the pipeline.

**Why JSON, not TS:** client sites and the embed route load configs at runtime by URL. A future
CMS can produce JSON. Producers can edit JSON without a build. Types come from a Zod schema
(`src/lib/turntable/config/schema.ts`), which is the single source of truth for runtime
validation and `z.infer` types.

### 3.2 `vehicle.json`

```ts
type Hex = string; // /^#[0-9a-fA-F]{6}$/

interface VehicleConfig {
  schemaVersion: 1;
  id: string;                    // slug == folder name, e.g. "countryman-s"
  name: string;                  // "MINI Countryman S"
  manifest?: string;             // default "manifest.json"
  defaultAngle?: number;         // degrees; snapped to nearest frame. Default 0
  defaultBackground: string;     // id of a background preset (global or vehicle-local)
  backgrounds?: BackgroundPreset[];   // vehicle-local presets, merged over global ones (§7)
  views?: { angle: number; name: string }[];
    // named angles: "Front", "Front three-quarter"… Used for aria-valuetext and Shift+arrow jumps
  palettes?: Record<string, ColourOption[]>;  // shared option lists, referenced by parts
  parts: Part[];
  intro?: { enabled?: boolean; turns?: number; durationMs?: number; delayMs?: number };
    // defaults { true, 1, 2600, 400 } (POC values)
  interaction?: { degreesPerStageWidth?: number; inertia?: boolean };
    // defaults { 313 (= 360/1.15, POC), true }
}

interface Part {
  id: string;                    // stable key used in share URLs and events: "paint", "roof"
  label: number;                 // mask pixel value, 1–255, unique per vehicle
  name: string;                  // UI label: "Mirror caps"
  original: { name: string; colour: Hex };
    // what the render already shows. `colour` is used for the swatch chip and as the
    // resolved colour when another part matches this one while it's on "original".
  allowOriginal?: boolean;       // default true; adds an implicit first option id "original"
  options: (ColourOption | { palette: string })[];   // palette refs are expanded in place
  default?: string;              // option id; default "original" (or first option)
  accent?: boolean;              // this part's resolved colour drives the UI accent (POC: paint)
}

type ColourOption =
  | { id: string; name: string; colour: Hex }          // solid colour
  | { id: string; name: string; match: string };       // "match another part" — target part id
```

Countryman example (abridged):

```json
{
  "schemaVersion": 1,
  "id": "countryman-s",
  "name": "MINI Countryman S",
  "defaultBackground": "studio",
  "views": [{ "angle": 0, "name": "Front" }, { "angle": 45, "name": "Front three-quarter" },
            { "angle": 90, "name": "Side" }, { "angle": 180, "name": "Rear" }],
  "palettes": {
    "contrast": [
      { "id": "white",  "name": "White",  "colour": "#EBEBE7" },
      { "id": "silver", "name": "Silver", "colour": "#B5B9BC" },
      { "id": "red",    "name": "Red",    "colour": "#B3141B" }
    ]
  },
  "parts": [
    { "id": "paint", "label": 1, "name": "Paint", "accent": true,
      "original": { "name": "Original red", "colour": "#B3141B" },
      "options": [{ "id": "racing-green", "name": "Racing green", "colour": "#1F3D2D" }] },
    { "id": "roof", "label": 2, "name": "Roof",
      "original": { "name": "Original black", "colour": "#1A1C1E" },
      "options": [{ "palette": "contrast" },
                  { "id": "match-paint", "name": "Match paint", "match": "paint" }] },
    { "id": "mirrors", "label": 3, "name": "Mirror caps",
      "original": { "name": "Original black", "colour": "#1A1C1E" },
      "options": [{ "palette": "contrast" },
                  { "id": "match-roof",  "name": "Match roof",  "match": "roof" },
                  { "id": "match-paint", "name": "Match paint", "match": "paint" }] }
  ]
}
```

### 3.3 `manifest.json` (generated)

```ts
interface VehicleManifest {
  schemaVersion: 1;
  generator: { tool: string; version: string; at: string };   // provenance
  size: { width: number; height: number };   // logical frame size; all frames and masks match
  labelEncoding: "index" | "x50";            // "index" = literal label values (production).
                                             // "x50" = legacy POC encoding, decode round(v/50)
  variants: { width: number; dir: string }[];  // responsive frame sizes, e.g.
                                               // [{800,"frames/800"},{1600,"frames/1600"}]
  poster: { src: string; width: number };    // low-res default-angle image for first paint
  contactY: number;                          // tyre-contact row in frame px (ground line)
  bounds: { x: number; y: number; w: number; h: number };  // union of car alpha across frames
  shadow: { mode: "baked" } | { mode: "separate"; dir: string };
  frames: Frame[];
}

interface Frame {
  angle: number;                 // degrees in [0, 360). Uneven spacing allowed
  file: string;                  // basename inside each variant dir, e.g. "045.webp"
  mask: string;                  // path relative to vehicle dir, e.g. "masks/045.png"
  ref: Record<string, number>;   // label → median linear luminance (0.004–1).
                                 // A missing key means the part isn't visible in this frame
  renderSet?: string;            // provenance tag; the pipeline warns when sets are mixed
  contactY?: number;             // per-frame override of the ground line
}
```

**Why `ref` lives in the manifest:** the POC builds a histogram per frame on the main thread
(about 1.2 M pixels × 12 frames). That's pure function-of-asset work. Doing it once in the
pipeline removes a full `getImageData` pass and a CPU loop per frame from the client. The
renderer then only needs RGB, labels and 5 numbers. The pipeline computes `ref` from the
**decoded shipped WebP**, not the source PNG, so lossy encoding can't shift the median. If `ref`
is missing (hand-made test assets), the client falls back to computing it in the decode worker.

### 3.4 Validation rules (unit-tested)

The config is parsed with Zod, then a semantic pass enforces:

- `schemaVersion` is supported. Unknown keys warn in dev and are stripped in prod.
- Frame angles are normalised into [0, 360) and must be unique after normalisation. At least 1 frame.
- Part `id`s are unique. `label`s are unique and in 1–255.
- Option ids are unique within a part after palette expansion. `original` is reserved.
- Every `match` target exists, isn't the part itself, and the match graph has **no cycles**.
  The POC's recursive `resolve()` would overflow the stack on a cycle.
- `default` refers to an existing option. `defaultBackground` refers to a known preset.
- Every label present in any `frame.ref` maps to a declared part (catches mask/config drift).
- `ref` values are in (0, 1].

Resolution semantics (also unit-tested, matching the POC):

`resolve(part)` returns `null` when the part is on original, so its pixels stay untouched.
For a solid option it returns that colour. For a match option it returns
`resolve(target) ?? target.original.colour`.

---

## 4. Rendering approach

### 4.1 Options

**A. Canvas 2D + CPU per-pixel loop (POC).** Decode the frame, `getImageData`, loop, then
`putImageData` into a cached canvas per frame.

**B. WebGL2 fragment shader.** Upload each frame as an RGBA8 texture and each mask as an R8
texture. Recolour at draw time in a shader with uniforms `uTarget[N]` (linear RGB plus an
enabled flag) and `uRef[N]` (per frame). Crossfade by sampling two frames in one pass.

### 4.2 Comparison

Timings are estimates for a 1600×747 frame (1.2 M px). Measure them in phase 1 (see the
acceptance criteria in §11).

| | A. Canvas 2D (POC) | B. WebGL2 shader |
|---|---|---|
| **Swatch-change latency** | One full CPU pass for the visible frame: roughly 15–30 ms on desktop and 60–150 ms on a mid-range phone. Every *other* frame is invalidated too, so rotating right after a change hits un-rendered frames and causes jank until `warm()` catches up (12 × the above; 5× worse at 72 frames). | A uniform write plus one redraw, under 2 ms even on low-end mobile GPUs. All angles are instantly correct, with nothing to invalidate. |
| **Memory** | Per frame: source `ImageData` 4.8 MB + labels 1.2 MB + cached canvas 4.8 MB ≈ 11 MB, so 12 frames ≈ 130 MB and 72 frames ≈ 790 MB of JS heap and canvas backing. That exceeds iOS Safari's canvas memory cap and crashes the tab. | Per frame: 4.8 MB RGBA8 + 1.2 MB R8 ≈ 6 MB of GPU memory, so 12 frames ≈ 72 MB, all resident. At 72 frames, a residency window (§5.4) keeps about 24 frames (≈145 MB) on the GPU. Encoded bytes (~110 KB per frame) stay in JS for re-upload. |
| **Mobile performance** | The per-pixel loop competes with input handling on the main thread. Moving it to a worker with OffscreenCanvas helps latency but not memory. | The GPU does the work and the main thread stays free for input. Fill rate isn't an issue at this resolution. |
| **Code complexity** | Low, about 60 lines. Easy to debug: open the image data and read pixels. | Higher, about 300–400 lines: context setup, texture upload flags, shader, crossfade, `webglcontextlost` and `restored` handling, residency LRU. No library needed; three.js or regl would be overkill. |
| **Correctness risks** | None new. It is the reference. | (1) Mask textures **must** use `NEAREST` filtering. Linear filtering blends label 1 and label 3 into "2" at edges. (2) Uploads need `UNPACK_PREMULTIPLY_ALPHA_WEBGL=false` and `UNPACK_COLORSPACE_CONVERSION_WEBGL=NONE`, or the browser alters RGB and mask values. (3) Exact sRGB `pow` formulas in `highp` float, not LUTs. The result can differ from the LUT path by ±1 code value. |
| **Fallback needed** | — | WebGL2 covers about 97% of browsers (Safari 15+). The 3% still need a path, plus a path for context loss. |

### 4.3 Recommendation: WebGL2, with the CPU algorithm kept as reference and fallback

- **Primary renderer: raw WebGL2** in `src/lib/turntable/render/webgl.ts`. One full-screen quad,
  four texture units (frame A, mask A, frame B, mask B) and a `uMix` uniform for crossfades.
  The shader premultiplies alpha on output into a `premultipliedAlpha: true` canvas.
- **Reference implementation: a pure TS function** `recolourPixel()` /
  `recolourBuffer(src, labels, refs, targets)` in `src/lib/turntable/recolour/`, ported line for
  line from the POC. It is the spec for the shader, it's what the unit tests cover, and it's the
  runtime fallback (run in a worker with OffscreenCanvas when WebGL2 is unavailable or the
  context is lost twice).
- **Shader parity check:** a dev-only route (`/dev/parity`) renders N configs through both paths
  and diffs `readPixels` against the CPU output. Tolerance is ±2 per channel. We run it by hand
  when the shader changes, not in CI, because headless GPU output varies.

**Tradeoff accepted:** two implementations of the maths. This is mitigated by the CPU version
being the tested reference and the shader being small, about 25 lines of GLSL. The alternative,
CPU only, can't meet the memory budget once vehicles have 36–72 frames, and that is the point
of phase 2.

---

## 5. Frame loading strategy

### 5.1 First paint

1. The server renders a `<img>` **poster**: the default angle at about 800 px, WebP, in the
   original colours, positioned exactly where the canvas will be. This is the LCP element
   (`fetchPriority="high"`). It shows instantly while JS loads.
2. Then the full-res default frame and its mask load, upload, and draw to the canvas. The canvas
   fades in over the poster, and the poster is removed.
3. If the build URL (phase 3) or default selection isn't "all original", the poster can't show
   the right colours. In that case we keep the poster at full opacity with a subtle loading
   shimmer over the swatch panel and swap as soon as frame 1 is recoloured. Typically under
   300 ms after hydration. Pre-recolouring posters on the server isn't worth it: it multiplies
   the variants.

### 5.2 Preload order: coarse-to-fine around the circle

After the default frame, load frames so the circle fills evenly. A quick early spin then hits a
*nearby* frame instead of a missing one:

```
default (0°) → opposite (180°) → ±90° → bisect each gap recursively (45, 135, 225, 315 …)
```

For uneven sets, the general rule is to repeatedly pick the frame furthest (in angle) from any
already-loaded frame. During a drag, the frame that is next in the drag direction jumps the
queue. The intro spin waits until **all** frames are loaded (12 frames ≈ 1.2 MB), or plays
partially as a fallback: it starts once ≥ 50% are loaded and loaded frames are no more than 45°
apart.

Concurrency: 6 in flight (HTTP/2 makes more pointless). The frame and its mask are requested as
a pair, because a frame without its mask can't be recoloured.

### 5.3 Decode off the main thread

- A **decode worker** fetches the bytes, then calls `createImageBitmap(blob, { premultiplyAlpha:
  "none", colorSpaceConversion: "none" })` and transfers the `ImageBitmap` back. Masks get the
  same flags. Without `colorSpaceConversion: "none"`, a stray gAMA or iCCP chunk could remap
  label values. The pipeline also strips those chunks.
- The main thread only calls `texImage2D(bitmap)`, which is cheap. The worker keeps the encoded
  `Blob`s so textures can be re-created after context loss or eviction without a network hit
  (HTTP cache usually covers it, but this is deterministic).
- Fallback where workers can't decode (old Safari): `createImageBitmap` on the main thread. It's
  still async and decodes off-thread in all current engines.

### 5.4 Responsive sizes and GPU residency

- Choose a variant by `stageCssWidth × devicePixelRatio`, capped. Phones get 800 w (≈1.5 MB GPU
  per frame), desktop gets 1600 w. Masks follow the same variants (pipeline downsamples with
  **nearest/mode**, never averaging).
- **Residency:** at ≤ 24 frames, keep everything on the GPU. Above that, keep a window of the
  nearest ±12 frames plus every 4th frame around the circle. A fast flick then always has
  *something* close to show, and the rest are evicted LRU. The budget is a config constant, with
  a lower value on devices reporting `navigator.deviceMemory ≤ 4`.

---

## 6. Interaction

### 6.1 Drag and touch

- Pointer events with `setPointerCapture`. `touch-action: pan-y` on the stage so vertical page
  scroll still works on phones. A horizontal drag over 6 px claims the gesture.
- Sensitivity is `degreesPerStageWidth` (default 313, the POC feel). Dragging right turns the car
  so its nose swings right: angle decreases, as in the POC.
- **Inertia:** track pointer samples from the last 80 ms. On release, if |v| > 0.05°/ms, coast
  with exponential decay (time constant ≈ 325 ms, like iOS scroll) and cap at 1.5 turns/s. When
  the speed drops below the threshold, **settle** to the nearest rendered angle with a 200 ms
  ease-out. With sparse frames this settle is what makes it feel deliberate instead of stuck
  between frames.
- **Snap hysteresis:** while dragging, switch to the next frame only once the continuous angle
  passes the midpoint between two frames by 2°. This stops flicker when a finger rests near a
  boundary.

### 6.2 Keyboard

One accessible slider (the scrubber) is the canonical control. The stage also handles keys when
focused, for convenience.

| Key | Action |
|---|---|
| ← / → | Previous or next rendered frame. **Direction matches ‹ / ›** (fixes the POC inconsistency): → and › = car turns so its nose moves right. |
| Shift + ← / → | Jump to the previous or next named view (`views`), or ±90° if none are defined |
| Home | Default angle |
| Swatches | A radiogroup per part with arrows moving selection (as in the POC). Each part gets an `<output>` live region announcing the option name. |

### 6.3 Angle scrubber

- A shadcn Slider (Base UI under `base-nova`, accessible by default) with `role="slider"`,
  `aria-valuetext` such as "45 degrees, front three-quarter" (from `views`), and ticks at each
  rendered angle (uneven spacing shown truthfully).
- Dragging the scrubber moves the continuous angle. Releasing it snaps.
- Hidden in `ui=minimal` embed mode (§8).

### 6.4 Crossfade vs interpolation between sparse frames

| Approach | Verdict |
|---|---|
| Hard cut | Harsh at 30–45° gaps. |
| **Short crossfade on frame change (POC, 110 ms)** | **Keep.** Done in-shader with `uMix`. It masks the jump without ghosting because each fade is short. |
| Angle-weighted blend while dragging (show 60/40 of two frames) | Reject. At 30–45° gaps two different silhouettes overlap: a visible double image, worse than a cut. Acceptable only at ≤ 5° spacing (72+ frames), where it's barely needed. |
| Optical-flow or depth-based view synthesis | Out of scope. It needs per-pair flow fields from the pipeline, adds artefacts around wheels and glass, and is a research project. |

**Decision:** the real fix for sparse frames is more frames. Production vehicles target **36
evenly spaced frames minimum (10°), 72 preferred**. At 10° the crossfade alone looks continuous.

### 6.5 Reduced motion

When `prefers-reduced-motion: reduce` is set (read live; it can change mid-session):

- No intro spin.
- No inertia: release stops dead and snaps without the settle animation.
- No crossfade (`uMix` jumps to 1). No CSS transitions on the knob or panels.
- Keyboard and scrubber still work. Rotation is user-driven, so it isn't "motion" in the WCAG
  2.3.3 sense.

### 6.6 Intro spin

- One turn over 2.6 s with easeInOut after a 400 ms delay (POC values, configurable).
- Starts only when the frames are ready (§5.2) **and** the stage is ≥ 50% in the viewport
  (IntersectionObserver). This matters for embeds below the fold, where the spin would
  otherwise play unseen.
- Cancelled instantly by any pointer down, key press or scrubber input. Once per page load (per
  embed instance), not per vehicle switch.

---

## 7. Background system

### 7.1 Presets

```ts
type BackgroundPreset = {
  id: string;
  name: string;
  groundY: number;          // 0–1: where the floor contact line sits on the stage
  carWidth?: number;        // 0–1 of stage width the car's bounds occupy; default 0.86
  shadowOpacity?: number;   // multiplier for the shadow layer; default 1
  tone: "light" | "dark";   // drives HUD and pill contrast
} & (
  | { kind: "css"; css: string }                   // gradient(s); POC presets port as this
  | { kind: "image"; src: string; focalX?: number; focalY?: number }  // cover-fit, focal point
);
```

Global presets live in `src/lib/turntable/backgrounds.ts` (studio, dusk, night; ported from the
POC CSS). Vehicles can add or override presets by id. Image presets get responsive `srcset` from
`next/image`-style variants.

### 7.2 How the car sits on the background

The POC uses fixed CSS (`top:56%`), which only works for its own gradients. Instead:

1. The pipeline records `contactY` (the tyre-contact row) and `bounds` (the union bbox of car
   alpha) per vehicle, with optional per-frame overrides.
2. Layout scales the frame so `bounds.w` fills `carWidth × stageWidth`, then translates it so
   `contactY` lands on `groundY × stageHeight`.
3. The result: any vehicle on any preset puts its wheels on that background's floor line,
   without per-vehicle CSS.

### 7.3 Shadow

- **Countryman today: baked.** The frames carry a soft contact shadow in partial alpha (about
  46 k partially transparent, mostly dark pixels in frame 000). It reads correctly on light and
  mid backgrounds and disappears on very dark ones, which is acceptable. `shadow.mode = "baked"`
  means no extra layer.
- **Production renders: separate shadow pass.** CGI renders the car without a shadow, plus a
  shadow-catcher pass per frame, exported as a single-channel (alpha-only) image. The shader
  draws the shadow under the car multiplied by `shadowOpacity`, so dark and photographic
  backgrounds can strengthen or soften it. Cost: one more R8 texture per frame (+1.2 MB GPU at
  1600 w).

### 7.4 User upload

- `<input type=file accept="image/jpeg,image/png,image/webp">` with a 20 MB limit.
  `createImageBitmap(file, { imageOrientation: "from-image", resizeWidth })` downsizes the image
  to ≤ 2× the stage's device pixels. A 48 MP phone photo shouldn't sit in memory at full size.
- **Never uploaded to a server.** It stays an object URL, which is revoked on replace or unmount.
  It is not included in share URLs, because a user photo can't be shared without hosting it (and
  the privacy questions that brings).
- Because we can't detect the floor in an arbitrary photo, uploads show two controls: **ground
  line** (vertical drag handle or slider) and **car size**. Defaults: `groundY 0.8`,
  `carWidth 0.7`, `shadowOpacity 1`.
- An embed flag can disable upload per client site.

---

## 8. Embedding

### 8.1 Routes

| Route | Purpose |
|---|---|
| `/` | Index of vehicles (internal, for QA and demos) |
| `/v/[vehicle]` | Standalone page: full UI (viewer, swatch panel, background picker). Shareable. |
| `/embed/[vehicle]` | Chrome-less viewer for iframes. Query flags: `ui=full|minimal|none`, `bg=<preset>`, `parts=paint,roof` (subset shown in the panel), `upload=0`, `intro=0`, `theme=light|dark` |

Both pages render the same `<Turntable>` client component. Vehicle configs are read at build
time: `generateStaticParams` over the `public/vehicles/*/vehicle.json` folders. With
`cacheComponents` enabled it must return at least one param, which it always will. URL state is
read client-side with `useSearchParams` inside a `<Suspense>` boundary, so pages stay
prerendered (see `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md`).

### 8.2 Embedding options compared

| | iframe + `embed.js` loader (**recommended**) | Web component (`<dox-turntable>` rendering in the host DOM) | npm React component |
|---|---|---|---|
| Works on any client stack | ✅ | ✅ | React only |
| CSS isolation | Total | Shadow DOM (fonts and `:root` vars leak) | None |
| Central updates | ✅ deploy once | ✅ if loaded from our CDN | ❌ each site upgrades |
| Host page perf | Separate document (≈ +50 KB runtime, lazy-loadable) | Shares host's main thread | Shares |
| Deep integration (host reads colour state) | via postMessage | DOM events | props/callbacks |
| CSP friction on client sites | `frame-src` only | `script-src` + `connect-src` + `img-src` | none |

**Decision:** an iframe is the delivery format for client sites, plus a ~2 KB
`public/embed.js` loader that:

- turns `<div data-turntable="countryman-s" data-ui="minimal"></div>` into a responsive,
  lazy-loaded (`loading="lazy"`) iframe with `allow="fullscreen"`
- keeps the aspect ratio and auto-height using a `resize` message from the frame
- exposes a small API: `Turntable.get(el).setColours({ paint: "racing-green" })`

The npm component is deferred until a React client asks for it. `<Turntable>` is already built
self-contained, so extracting it later is cheap.

### 8.3 postMessage API (versioned)

```
frame → host:  { type: "turntable:ready",  v: 1, vehicle }
               { type: "turntable:change", v: 1, angle, selection: { paint: "racing-green", … }, background }
               { type: "turntable:resize", v: 1, height }
host → frame:  { type: "turntable:set",    v: 1, angle?, selection?, background? }
```

Both sides check `event.origin` against the allowlist. Unknown message types are ignored.

### 8.4 Security headers

Set in `next.config.ts` `headers()`:

- `/embed/:path*` sends `Content-Security-Policy: frame-ancestors 'self' <client allowlist>`.
  The allowlist comes from an env var, so adding a client doesn't need a code change.
- Every other route sends `frame-ancestors 'self'`.

---

## 9. Asset pipeline

### 9.1 Current state (POC only)

`docs/scripts/` (the brief said `docs/reference/scripts/`; that folder doesn't exist):

- `01_normalize_frames.py` crops and scales to 1600 w. Four frames (30, 90, 150, 210) are
  rescaled ×0.8 and re-positioned by hand-entered centre and bottom coordinates, because they
  came from a different render.
- `02_generate_masks.py` segments by HSV thresholds tuned to red paint and champagne trim, uses
  hand-placed boxes per angle for mirrors (`mir`), lamps and rear lights, and a convex hull for
  mirror caps. It writes `.npy`, not PNG; a separate step must have exported the PNGs.
- `_hsv_helper.py`: `02` runs `exec(open('mask.py'))`, but the file is now named
  `_hsv_helper.py`, and the input paths point at `/mnt/user-data/uploads/`. **The scripts don't
  run as checked in.**

They are tied to Countryman's colours and coordinates and don't generalise. They're kept as
the fallback (§9.4).

### 9.2 Production path: CGI ID passes → label maps (Node)

**What the CGI studio delivers per vehicle**, at a fixed camera and resolution, for every angle:

| Pass | Format | Notes |
|---|---|---|
| Beauty | 16-bit PNG or EXR → we encode WebP | Transparent background. No shadow if `shadow=separate`. |
| Colour-ID | 8-bit PNG, **flat unlit material colours, no anti-aliasing, no dithering** | One flat colour per recolourable part, everything else black. Cryptomatte is the better alternative if the renderer supports it, because it carries per-pixel coverage and solves edges. |
| Shadow (optional) | 8-bit greyscale | Shadow-catcher only |
| `ids.json` | `{ "#FF0000": "paint", "#00FF00": "roof", … }` | ID colour → part id |

**`tools/vehicle-pipeline/` (Node 23, TS run via native type stripping, `sharp`):**

```
pnpm vehicle:build <id>   # reads raw/<id>/{beauty,id,shadow}/<angle>.png + ids.json + vehicle.json
```

1. **Validate inputs:** every angle has beauty and ID; dimensions match; angles parse from
   filenames (`045.png`, `007_5.png` for 7.5°). It warns when spacing is uneven and fails if
   frames < 12.
2. **ID → labels:** map each pixel's ID colour to `parts[id].label` from `vehicle.json`. Pixels
   that aren't an exact palette colour (stray AA, compression) are matched to the nearest ID
   colour within ΔE < 10 if their alpha in beauty > 0, otherwise 0. It **fails** if more than
   0.1% of car pixels are unmatched and reports which colours were found. Labels are then masked
   by beauty alpha > 0.
3. **Crop and normalise:** one common crop window for all frames, derived from the union alpha
   bbox plus a margin. Per-frame transforms aren't allowed: a camera mismatch is a render bug to
   send back, not something to patch.
4. **Encode:** frames → WebP (q≈82, alpha q 100) at each variant width (800, 1600). Masks →
   8-bit greyscale PNG with literal labels (`labelEncoding: "index"`), downsized with
   **nearest/mode**, and gAMA, iCCP and sRGB chunks stripped. Poster → 800 w WebP of the default
   angle.
5. **Measure:** decode each *encoded* frame and compute `ref[label]` (median linear luminance,
   1024-bin histogram, floor 0.004, exactly as in the POC). Also compute `contactY` (lowest row
   with car alpha > 200, excluding shadow) and `bounds`.
6. **Write `manifest.json`**, plus `qa/contact-sheet.png`: every frame with labels overlaid in
   false colour, for human sign-off before commit.

The maths in steps 2 and 5 (colour matching, median) is shared with `src/lib/turntable/recolour/`
and covered by the same unit tests.

### 9.3 Mask edges

Hard labels produce a stair-stepped edge where a recoloured part meets an unrecoloured one, most
visible on white over black. Phase 2 options, cheapest first:

- (a) Render the ID pass at 2× and downsample with mode. Better placement, still hard edges.
- (b) A **coverage** channel: ship a second 8-bit channel with the label's coverage (from AA ID
  pass or Cryptomatte) and blend `mix(original, recoloured, coverage)` in-shader. +1 channel per
  mask, which makes it a 2-channel PNG.
  **Recommended for phase 2** if the studio can deliver AA ID passes or Cryptomatte.

### 9.4 Fallback: Python colour segmentation

For vehicles where only beauty frames exist (photography, a supplier that won't do ID passes):

- Move `docs/scripts/` → `tools/python-masks/`, fix the `mask.py` import and the paths, take CLI
  args, and **emit label PNGs plus a manifest stub** in the same format as §3.3, so the viewer
  can't tell the difference.
- Hue thresholds and hand boxes become a per-vehicle `segment.yaml`. That still means manual
  tuning and per-angle fix-ups, so expect several hours per vehicle plus QA.
- Masks from this path are marked `"provenance": "segmented"` in the manifest so QA knows to look
  harder.

### 9.5 Render recommendation: neutral base for recolourable parts

The recolour maps luminance to the target, so the source material sets the ceiling. A **black**
roof recolouring to white has almost no tonal range to work with, as shown in §2.1. If the studio
can render the recolourable parts in a **neutral mid-grey version of the real material** (same
gloss, flake and clearcoat, around 40–50% albedo), every target colour gets usable shadows and
highlights. "Original" then becomes an ordinary palette entry that recolours to the factory
colour. This is an open question (§12) because it changes what "Original" means.

### 9.6 Asset conventions

```
public/vehicles/<id>/
  vehicle.json               # hand-authored
  manifest.json              # generated
  poster.webp
  frames/800/<angle>.webp
  frames/1600/<angle>.webp
  masks/<angle>.png          # 1600 w labels; 800 w variant in masks/800/ if needed
  shadow/<angle>.png         # only when shadow.mode = "separate"
  qa/contact-sheet.png       # not deployed (excluded by .vercelignore)
raw/<id>/…                   # source renders — NOT in git (see open questions)
```

Angles are zero-padded integer degrees (`045`), with `_` for decimals (`007_5`).

**Phase-1 note:** the existing `public/vehicles/countryman-s/frames/*.webp` and `masks/*.png` are
used as-is. They move under `frames/1600/` when the pipeline first runs, and phase 1 writes their
manifest by hand.

---

## 10. POC limitations to design out

| Limitation | Root cause | Design-out |
|---|---|---|
| **12 frames, unevenly spaced** (15–45° gaps) | Assembled from what renders existed | Config supports uneven angles (§3.3). Viewer uses circular nearest with hysteresis (§6.1). Pipeline enforces ≥ 12 and warns below 36 (§9.2). Production spec: 36–72 even frames. |
| **4 frames (30, 90, 150, 210) from a different render set**: different lighting, trim tone, scale | Mixed sources, hand-normalised (×0.8 plus manual offsets) | `renderSet` provenance per frame, and the pipeline warns when sets are mixed. The common crop with no per-frame transforms forces fixes upstream. Per-frame `ref` already self-normalises *recoloured* parts. "Original" still shows the mismatch, so re-render these 4 (or all 12 at 36) for Countryman. |
| **Imperfect mirror masks** | Hand-placed boxes + convex hull of dark pixels | CGI ID pass (§9.2). Until then, hand-correct the 12 mirror regions in an image editor using an indexed palette that preserves label values. |
| **Mask encoding mismatch** (POC ×50 vs files 0–5) | Two export paths | `labelEncoding` field. Production is `"index"`, and the decoder is unit-tested for both. |
| **Hard mask edges** (stair-stepping at part boundaries) | Binary labels | Coverage channel (§9.3). |
| **Per-pixel CPU work on the main thread; whole cache cleared on any change** | Canvas 2D architecture | WebGL shader (§4). |
| **1.5 MB base64 HTML; all frames block first paint** | Single-file prototype | Separate cacheable assets, a poster, progressive load (§5). |
| **Memory grows ~11 MB per frame** | ImageData + cached canvases | GPU textures + residency window (§5.4). |
| **Opposite directions for ← key and ‹ button** | Bug | Unified direction (§6.2). |
| **Car position hard-coded in CSS** | No ground model | `contactY` + `groundY` (§7.2). |
| **Dark source parts recolour flat** | Luminance mapping from a near-black median | Neutral-base renders (§9.5). Keep the `^0.6` lift for legacy assets. |
| **Match cycles would hang** | Unchecked recursion | Validation (§3.4). |
| **Python scripts don't run as checked in** | Renamed helper, absolute paths | Fix when moving to `tools/python-masks/` (§9.4). |

---

## 11. Phased plan

### Phase 0: Foundations (small)

- Add Vitest, Zod. Folder skeleton per `CLAUDE.md`.
- Port the recolour maths to pure TS, with golden tests. Golden values come from running the
  POC's own functions in Node on sample pixels and a cropped real frame.
- Config schema, semantic validation and match resolution, with tests. Hand-write
  `countryman-s/vehicle.json` and `manifest.json` (`labelEncoding: "index"`, `ref` computed by
  a one-off script using the shared median function).

### Phase 1: Countryman parity with the POC

The scope is everything the POC does, built on the production architecture. Re-building it on
Canvas 2D first would mean rewriting it in phase 2.

- WebGL2 renderer with crossfade, CPU fallback in a worker, context-loss recovery.
- Loader: poster, coarse-to-fine order, worker decode.
- Drag (with inertia and hysteresis), keyboard (direction fixed), scrubber with uneven ticks,
  intro spin, reduced-motion behaviour.
- Swatch panel with original, solid and match options. Reset. Accent colour follows paint.
- Backgrounds: studio, dusk and night presets, plus upload with ground and size controls.
  `contactY` layout.
- Route `/v/countryman-s`.

**Acceptance:**

- For 10 sampled configs × 12 frames, the shader output matches the CPU reference within ±2 per
  channel (parity page).
- Swatch-to-pixels under 50 ms on an iPhone 12-class device.
- Drag holds 60 fps.
- LCP under 1.5 s on fast 4G (poster).
- No layout shift.
- Keyboard-only and VoiceOver walkthrough pass.

### Phase 2: Config-driven multi-vehicle

- Node asset pipeline (§9.2) and QA contact sheet. Python fallback moved and fixed (§9.4).
- Responsive variants and GPU residency for 36–72 frames.
- Separate shadow pass support. Coverage-channel edges (if ID passes allow).
- `/embed/[vehicle]`, `embed.js`, postMessage API, `frame-ancestors` allowlist.
- A second vehicle end-to-end to prove there's no Countryman-specific code. Re-render
  Countryman if CGI is available.

### Phase 3: Hotspots and share-a-build

- **Share-a-build URL state:** `?v=1&a=45&bg=dusk&paint=racing-green&roof=match-paint`.
  Readable option ids, versioned, and invalid values fall back to defaults silently.
  `history.replaceState` (debounced) on change, never `push`. "Copy link" button. OG image per
  build is a stretch: server-render the recolour with the CPU reference in a route handler.
- **Hotspots:** per-vehicle `hotspots[]` with 3D anchor points from CGI, which the pipeline
  projects to 2D per frame using the exported camera. Each hotspot is visible only within an
  angle range and positioned by interpolating between neighbouring frames. Content (title,
  body, image) comes from config, or later a CMS. Keyboard reachable, as a list of hotspots
  alongside the stage.

### Later (not committed)

Finish options (matte or gloss via a roughness tweak in-shader), interior views, analytics
events, an npm package, CMS-managed palettes.

---

## 12. Open questions

1. **CGI access:** can we get the Countryman scene, or the studio that rendered it, to produce
   ID passes and more frames? Which renderer (VRED, KeyShot, Blender, Unreal)? Does it support
   Cryptomatte?
2. **Frame count:** what is the production target for new vehicles, 36 or 72 frames? 72 roughly
   doubles bandwidth (about 7 MB at 1600 w) and render cost.
3. **"Original" option:** must every part offer the factory render as an untouched option, or can
   recolourable parts be rendered in a neutral base (§9.5) for better recolour quality?
4. **Palettes:** are colour names, hex values and allowed combinations defined by the
   manufacturer? Are there combination rules (e.g. a roof colour only with certain paints) or
   per-market palettes? The schema has no constraints yet.
5. **Client sites:** which domains need embedding first? Is an iframe acceptable to their dev
   teams, or does anyone require an in-DOM component?
6. **Raw render storage:** where do source renders live? They're too big for git. Options are
   Git LFS, S3/R2 or a shared drive.
7. **Asset hosting:** serve frames from Vercel static (simple, counts toward bandwidth) or a
   separate CDN or Vercel Blob? Is there an expected traffic level?
8. **Browser floor:** is iOS 15 / Safari 15 (WebGL2) acceptable as the full-experience floor,
   with older browsers getting the CPU fallback?
9. **Theming:** does the embed UI take on the client's brand (fonts, accent), or always look like
   DOX/Turntable?
10. **Drag direction:** keep the POC's "drag right = nose swings right"? And should → match it
    (my proposal)?
11. **Design:** is the POC layout the visual reference for phase 1, or are designs coming?
12. **Hotspot content:** where does it come from (config JSON, a CMS, the client)? Who authors the
    3D anchor points?
13. **Analytics:** which events matter (swatch changes, time on viewer, shares), and into which
    tool?
