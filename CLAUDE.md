# Turntable

Config-driven 360° vehicle viewer for DOX dealer and campaign sites: pre-rendered frames
over a swappable background, with live per-part recolouring. `SPEC.md` is the design
reference; read the relevant section before building a feature. `IDEA.md` is the one-paragraph
brief. `docs/reference/poc.html` is the working prototype; it's the behavioural baseline.

**Prototyping phase:** `/` serves `public/poc/index.html` through a `beforeFiles` rewrite in
`next.config.ts`. It's an editable copy of the POC that loads frames and masks from
`public/vehicles/countryman-s/` (literal 0–5 labels) instead of inlined base64. Edit it freely.
Changes need a browser refresh, not HMR. Once a prototype change is agreed, reflect it in SPEC.md.
`src/app/page.tsx` is unreachable while the rewrite is active.

@AGENTS.md

## Stack

- **Next.js 16.4 App Router** (`next@16.4.3`). APIs differ from older versions; read
  `node_modules/next/dist/docs/` before using a Next API. `next.config.ts` enables
  `cacheComponents` and `partialPrefetching`, so pages prerender by default. Read URL state with
  `useSearchParams` inside `<Suspense>`, not `searchParams` in the page, unless dynamic rendering
  is intended.
- **React 19.3**, **TypeScript strict**. No `any`; no non-null `!` on data from config or the network.
- **Tailwind v4**: CSS-first config in `src/app/globals.css`, with no `tailwind.config.*`.
- **shadcn/ui, `base-nova` style**: components are built on **Base UI (`@base-ui/react`), not
  Radix**. Add components with `pnpm dlx shadcn@latest add <name>` and don't hand-copy Radix
  examples. Icons: `lucide-react`.
- **pnpm** (10.x, pinned in `packageManager`). Never use npm or yarn.
- **Vercel** for hosting.
- Planned (phase 0): **Vitest** for unit tests, **Zod** for config schemas, **sharp** for the asset
  pipeline. `sharp` is currently in `ignoredBuiltDependencies` in `pnpm-workspace.yaml` and needs
  allowing when the pipeline lands.

## Folder structure

Target layout. Folders appear as phases land.

```
src/
  app/
    page.tsx                      # vehicle index (internal)
    v/[vehicle]/page.tsx          # standalone viewer page
    embed/[vehicle]/page.tsx      # chrome-less iframe target
    dev/parity/page.tsx           # dev-only: shader vs CPU recolour diff
  components/
    ui/                           # shadcn — generated, edit sparingly
    turntable/                    # Turntable, Stage, Scrubber, SwatchPanel, BackgroundPicker
  lib/
    utils.ts                      # cn()
    turntable/
      recolour/                   # PURE maths: srgb.ts, recolour.ts, median.ts (+ *.test.ts)
      config/                     # schema.ts (Zod), validate.ts, resolve.ts (+ *.test.ts)
      render/                     # webgl.ts, shaders.ts, cpu-fallback.worker.ts
      loader/                     # decode.worker.ts, queue.ts (preload order), residency.ts
      interaction/                # drag/inertia, keyboard, intro spin
      backgrounds.ts              # global background presets
public/
  vehicles/<id>/                  # see "Asset conventions"
  embed.js                        # iframe loader for client sites (phase 2)
tools/
  vehicle-pipeline/               # Node: CGI ID passes → label maps + manifest (phase 2)
  python-masks/                   # fallback colour segmentation (moved from docs/scripts)
docs/
  reference/poc.html              # prototype — do not edit
  scripts/                        # POC Python, as-is (doesn't run without fixes; see SPEC §9.1)
```

Keep `src/lib/turntable/recolour/` and `config/` free of DOM, React and WebGL imports, so they
can be tested in Node and shared with the pipeline.

## Recolour algorithm (summary; full spec in SPEC.md §2.1)

Every frame has a label map. Pixel value = part label, with 0 meaning none. For Countryman the
labels are: 1 paint, 2 roof, 3 mirror caps, 4 trim, 5 wheel accents. For each labelled pixel whose
part has a non-original target colour:

1. `L` = linear luminance of the source pixel (sRGB → linear, then Rec. 709 weights
   0.2126 / 0.7152 / 0.0722).
2. `Lr` = that part's **median** `L` in this frame. It comes from `manifest.json` `frames[].ref`,
   computed from a 1024-bin histogram as `(bin + 0.5) / 1023` with a floor of 0.004.
3. `t` = target colour in linear RGB.
4. If `L ≤ Lr`, then `m = L/Lr`, raised to the power 0.6 when `Lr < 0.03`, and `out = t·m`.
   Otherwise `h = ((L−Lr)/(1−Lr))^0.9` and `out = t + (1−t)·h`.
5. Convert linear → sRGB. Alpha is unchanged. Unlabelled and "original" pixels are untouched.

"Match" options resolve to the target part's resolved colour, or to its `original.colour` when
that part is on original. Cycles are a validation error.

Rules for this code:

- The pure TS implementation is the **reference**. The WebGL shader must match it within ±2 per
  channel, checked on `/dev/parity`. Change the reference first, with tests, then the shader.
- Don't tweak the constants (0.004, 0.03, 0.6, 0.9, 1024 bins) without a visual comparison
  signed off by the user. They define the look.
- Mask textures use `NEAREST` filtering, always. Upload with premultiply off and colour-space
  conversion off, for both `createImageBitmap` and the WebGL unpack flags.

## Asset conventions

```
public/vehicles/<id>/
  vehicle.json        # hand-authored: parts, labels, palettes, match options, defaults
  manifest.json       # GENERATED by tools/vehicle-pipeline — never hand-edit (phase 1 excepted)
  poster.webp         # ~800 w default angle, original colours (LCP image)
  frames/<w>/<angle>.webp
  masks/<angle>.png   # 8-bit greyscale, literal label values (labelEncoding "index")
  shadow/<angle>.png  # only when manifest.shadow.mode = "separate"
```

- Angle filenames are zero-padded integer degrees (`000`, `045`, `330`), with `_` for decimals
  (`007_5`). Paths in code come from the manifest; never build them from angles.
- Angle convention: 0° = head-on front, 90° = side profile with the nose to the left of the
  frame, 180° = rear.
- Frames and masks for a vehicle all share the manifest's `size`.
- **Gotcha:** the POC's embedded masks store label×50 (decoded as `round(v/50)`), while the files
  in `public/vehicles/countryman-s/masks/` store literal 0–5. Honour `manifest.labelEncoding`.
- When re-saving masks, never use antialiasing, resampling other than nearest/mode, or colour
  profiles. Any of these corrupts the labels.
- Raw source renders don't go in git.

## Commands

```bash
pnpm install
pnpm dev                     # next dev
pnpm build                   # next build
pnpm lint                    # eslint
pnpm test                    # vitest run         (added in phase 0)
pnpm test:watch              # vitest             (added in phase 0)
pnpm vehicle:build <id>      # asset pipeline     (added in phase 2)
```

Run `pnpm lint`, `pnpm test` and `pnpm build` before saying work is done.

## Testing policy

- **Write tests for:** recolour maths (sRGB conversions, the per-pixel function, median and
  histogram, the CPU buffer path against POC golden values), config parsing and semantic
  validation (Zod schema, palette expansion, match resolution, cycle detection, label/manifest
  consistency, `labelEncoding` decode), and pure pipeline helpers (ID-colour matching).
- **Don't write tests for:** UI components, layout, animation feel, or interaction tuning. Iterate
  on those in the browser.
- Golden values come from the POC's own functions. Never regenerate goldens to make a failing
  test pass without saying so.

## Rules

- **Ask before every commit.** Show the proposed message and the files to be committed, then wait
  for approval. Approval covers that one commit only.
- **Never push** (or open a PR, or force anything) without explicit approval for that push.
- Don't edit `docs/reference/poc.html`. It's the baseline.
- Don't add dependencies beyond the stack above without asking. No three.js, regl or other
  graphics libraries; the renderer is raw WebGL2 (SPEC §4.3).
- Keep vehicle-specific values (colours, labels, angles, coordinates) in `public/vehicles/<id>/`,
  never in `src/`.
- Respect `prefers-reduced-motion` in anything that animates (SPEC §6.5).
- When a SPEC decision turns out wrong in practice, raise it instead of silently diverging, then
  update SPEC.md.
