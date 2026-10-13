# Graphic templates and themes (HyperFrames)

Templates live in `motion/templates/*.html`, and the catalog Claude reads when planning is in `motion/templates/templates.json`. Each template describes *content*. The *look* comes from a theme in `motion/themes/`. `graphics.py` copies each `plan.json` graphic into `motion/build/`, fills in the duration, the props and the theme, and renders it with the pinned HyperFrames CLI (`motion/node_modules/hyperframes`, v0.8.150) to a VP9 WebM with alpha. `finish.py` then overlays it on the video.

## Templates

| Template | Kind | Use |
|---|---|---|
| `title-card` | full screen | Hook, chapter openers |
| `kinetic` | full screen or over the video (`backdrop`) | Hook or punchline in big popping words |
| `lower-third` | overlay, bottom-left | Name or product intro, once |
| `callout` | overlay, positionable | Key term, number or tip |
| `highlight` | overlay, anywhere | Box, circle or underline around something on screen, with optional label and spotlight. `screen: [x, y, w, h]` in recorded pixels is converted for you |
| `steps` | overlay, top or bottom | Progress through a flow (Cart → Checkout → Transfer) |
| `tool-cards` | full screen | Lists of 2–8 things, with a highlight |
| `browser-frame` | full screen | A screenshot from `research.py`, scrolled |
| `end-card` | full screen | Closing call to action |

## Themes

`motion/themes/themes.json` lists them. Each entry has a `description`, a `colors` palette (`accent`, `accent2`, `bg`, `panel`, `text`, `muted`), a `captions` style and, for brand themes, `css`, the look it reuses.

| Theme | Look |
|---|---|
| `glass` | Dark translucent cards, accent glow, rounded, smooth motion |
| `clean` | Light, white cards, soft shadows, calm motion |
| `bold` | Black and white, Anton capitals, square blocks with hard offset shadows, snappy motion |
| `neon` | Black, glowing magenta/cyan outlines, mono labels, springy motion |
| `editorial` | Cream paper, Fraunces serif, thin rules, slow motion |

**Brand themes** reuse one of the five looks with a client's palette and caption style: an entry with `"css": "bold"` (say), `colors` and `captions`. Put personal or client themes in `motion/themes/themes.local.json` (gitignored, same format, merged over `themes.json`) so they stay out of the shared repo.

Which theme applies: `plan.json` `"style"` beats `brand.json` `"style"`, which beats `glass`. `brand.json` `colors` and `captions` entries override any theme's own values.

`.\vp gallery [--themes a,b] [--templates x,y]` renders every template in every theme, on a real frame from the newest video, plus a captions sample. The sheets go to `motion/gallery/<theme>.png`. Renders are cached, so re-runs are quick. Use it to let the user choose a style, and to check a new theme or template everywhere at once.

### How a theme works
- **`themes/base.css`** defines the shared building blocks every template uses:
  - `hf-panel`, `hf-display`, `hf-body`, `hf-label`, `hf-pill`, `hf-bar` and `hf-muted`;
  - `hf-stage`, with three decoration layers: `hf-deco-grid`, `hf-deco-a` and `hf-deco-b`;
  - and every variable, with glass-like defaults.
- **`themes/<look>.css`** sets those variables, restyles the blocks and decorations, and sets the motion feel: `--ease`, `--ease-pop`, `--dur`, `--stagger`, `--enter` and `--drift`. `--drift` sets how much the decorations move: 0 keeps stripes and rules still.
- **`themes/fx.js`** (`window.HF`) applies the palette and reads the motion settings: `HF.setup()` returns `{v, dur, M}`. It also provides `HF.words()`, `HF.text()` and `HF.drift()`.

## Writing a new template: conventions (each one learned the hard way)

1. **Copy an existing template.** Keep the `<head>` order:
   - `../fonts/fonts.css`
   - `../themes/base.css`
   - the template's own `<style>`, for layout only, using theme variables for anything stylistic
   - the `<!--THEME-->` marker, where `graphics.py` inserts the theme stylesheet
   - `../vendor/gsap.min.js`
   - `../themes/fx.js`

   Overlays must not paint a background. Full-screen templates use `<div class="hf-stage">` with the three `hf-deco` layers.
2. **Declare every variable** in `data-composition-variables` on `<html>`:
   - Types: `string`, `number`, `color`, `boolean`, `enum` or `image`.
   - Palette colours are declared as **`c_accent`, `c_accent2`, `c_bg`, `c_panel`, `c_text` and `c_muted`**. The prefix keeps them from colliding with content props.
   - `graphics.py` rejects props the template doesn't declare.
   - Pass lists as JSON strings or comma lists.
3. **CSS variable names must never equal a prop id.** HyperFrames publishes every prop as a CSS variable named `--<id>`. A callout's `text` prop once overwrote `--text`, the text colour, and turned all the text black. That's why the text colour is `--ink`.
4. **Duration:** put `data-fill-duration` on the root and the main `.clip`; their `data-duration` is rewritten per use. Use `HF.setup().dur`, and schedule the exit at about `dur - 0.45`.
5. **Wrap the script in `(() => { ... })();`.** Top-level `const top`, `name`, `status` and similar names collide with browser globals and kill the script, so HyperFrames waits out a 45 s timeout and renders the default text.
6. **Use one paused GSAP timeline,** registered as `window.__timelines["<data-composition-id>"] = tl`. Use `fromTo` tweens, with the theme's `M.ease`, `M.pop`, `M.dur`, `M.stagger` and `M.enter`.
7. **Never put a CSS `transform` on an element GSAP animates,** because GSAP overwrites it. Center with flex or left/top on a parent; translating a non-animated anchor is fine (see `callout`). Theme decorations are animated by `HF.drift`, so themes mustn't transform them either.
8. **No randomness, timers or `Date.now()`.** Rendering is frame by frame and must be deterministic.
9. **Images:** `graphics.py` copies them to `motion/assets/<slug>/` and passes `/assets/<slug>/x.png`. For a template that needs the image's size, the root gets `data-img-w` and `data-img-h`.
10. **Fonts:** all fonts are OFL, vendored in `motion/fonts`, with `@font-face` in `fonts.css`. `.\vp doctor` converts them to TTF for captions. Never load from the network during a render.
11. **Register and test.** Add the template to `templates.json`:
    - `file`, `fullscreen`, `hide_captions`, `zone` (bottom* lifts captions), `default_duration`, `use`, and a description of each prop.

    Add a sample to `SAMPLES` in `scripts/gallery.py`, then run `.\vp gallery --templates <name>` and Read every theme's sheet.

For deeper HyperFrames authoring (sub-compositions, audio, shaders), the project ships official agent skills (`cd motion; npx hyperframes skills`). The docs are at https://hyperframes.heygen.com. Preview a composition interactively with `cd motion; npx hyperframes preview` (Studio on port 3002).
