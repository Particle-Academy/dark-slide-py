# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Pre-1.0: breaking changes land in MINOR releases.** Until `1.0.0` a bumped
minor may change an API, so read the entry before upgrading — the version
number cannot make a promise the 0.x range does not allow it to keep.

## [Unreleased]

## [0.3.0] - 2026-09-13

**BREAKING, for how big things are, not for any API.** Pre-1.0, so this lands in a minor. Ports `particle-academy/dark-slide` 0.10 exactly; the parity suite compares every part against the PHP engine byte for byte, embedded fonts included.

### Changed

- **BREAKING: decks are drawn at the size fancy-slides draws them.** Every length in a deck is now a design pixel on a canvas `theme.slideWidth` wide (1920 by default) and converts as `points = px × 720 / slideWidth`. `fontSize: 96` is 36pt, 5% of the slide width, which is what fancy-slides shows.

  Before, `fontSize` was halved into points with an 8pt floor (96 → 48pt, a third larger than the preview) and every other length was taken as points, so one style object mixed two units. Now converted identically: `fontSize`, `strokeWidth`, `letterSpacing`, `spaceBefore`, `spaceAfter`, `padding`, `radius`, border and accent-bar widths, and table row heights. The floor is 1pt (PPTX's minimum). Built-in defaults that are PowerPoint's own (text insets, a 1pt outline, a 0.75pt table rule, minimum row heights, a 4pt accent bar) stay in points.

  **What to do:** nothing, if your decks were designed in fancy-slides; they now match it. To keep a 0.2 deck's output exactly, set `theme.slideWidth: 1440` and double every length you had written in points (the list above, minus `fontSize`). Composites (`kpiBand`, `metadataGrid`) already did this to their own defaults, so at 1440 they render as before.

- **The text default is 28 design px** (10.5pt), fancy-slides' own default, instead of 24.

- **Code blocks take `style.fontSize`**, default 32 design px (12pt, the size they were fixed at).

- **The published schema describes the design-pixel model**, including `theme.slideWidth`, `theme.aspectRatio` and element `strokeWidth`, identical to the PHP reference (`tests/test_schema_describes_style_units.py` diffs them).

- **The conformance pin moved from 0.21.2 to 0.22.0**, whose `dark-slide/table-cell-model` goldens follow the new model. All three tables were re-run first: `shared/strings` 8, `shared/decimal` 18, `dark-slide/table-cell-model` 28, nothing failed or skipped, rounding ties included.

### Fixed

- **`theme.aspectRatio` shapes the slide.** It was validated, published in the schema and ignored, so a 4:3 deck came out stretched onto 16:9. The slide stays 10in wide; 16:9, 16:10 and 4:3 get PowerPoint's named `<p:sldSz type>`, any other ratio a custom size.

- **The reader reads geometry against the file's own slide size** (`<p:sldSz>`) instead of assuming 16:9, and returns `theme.aspectRatio` for any other shape (an int when the ratio is whole, as PHP returns it). A 4:3 deck's `y` of 0.5 used to read back as 0.667.

- **Rounded corners are the radius asked for.** A roundRect corner is `min(w, h) * adj / 100000` (LibreOffice's preset table); decorated text boxes divided by half the shorter side and drew every corner twice as round. `rounded-rect` shapes now take `radius` (design px, default 8) instead of PowerPoint's default corner.

### Added

- **Embed the host's fonts in the file**, so brand typography survives machines that do not have it installed:

  ```python
  dark_slide.write(deck, "out.pptx", {"fonts": {
      "Bebas Neue": {"regular": "fonts/BebasNeue-Regular.ttf"},
      "Inter": {"regular": inter_regular_bytes, "bold": pathlib.Path("fonts/Inter-Bold.ttf")},
  }})
  ```

  Each variant (`regular`, `bold`, `italic`, `boldItalic`) is a path (`str` or `os.PathLike`) or the font's `bytes`. The deck itself never carries a font, so an agent can name a typeface but never make the writer read a file.

  Written as uncompressed Embedded OpenType in `ppt/fonts/fontN.fntdata`, with `<p:embeddedFontLst>` and `embedTrueTypeFonts="1"`, byte-identical to the PHP engine. **Verified by rendering in LibreOffice 26** (the opt-in `DARK_SLIDE_RENDER=1` test); **not verified in PowerPoint or Google Slides**.

  Refused, all at once and before anything is written, with `dark_slide.FontEmbeddingException` and the same text as PHP: fonts whose licence (`fsType`) forbids embedding or allows bitmaps only, CFF-outline `.otf` and `.ttc` collections, and a file whose family name is not the typeface it was supplied for.

  `read()` reports embedded typefaces and variants in `metadata.embeddedFonts`, never the bytes.

  **Nothing changes for a deck written without `fonts`**: same parts, same bytes.

- **Parity fixtures** for the default and 1440 canvases, a 4:3 and a custom-ratio slide, rounded rectangles, and a two-typeface font embedding compared as bytes. `scripts/php_tobytes.php` takes an optional options JSON for the last.

## [0.2.1] - 2026-09-13

### Fixed

- **The published schema says what unit every `style` field is in.** `json_schema()` exported `style` as a bare `{"type": "object"}`, so a model filling it in had only the key names, and `fontSize` reads as points. It is design pixels on the 1920px fancy-slides canvas, halved into points with an 8pt minimum. In the fancy-labs document lab an agent described its headline as 232pt, and the file it wrote carried 116pt.

  The style object also mixes units: `letterSpacing`, `spaceBefore`, `spaceAfter`, `padding`, `radius` and the border and accent-bar widths are already points, and `lineHeight` is a multiple. Every field now carries a description with a worked example, and `x`, `y`, `w` and `h` say they are fractions of the slide.

  **Upgrade and do nothing.** Descriptions and permissive types only: the validator never reads this export and the writer's bytes are unchanged.

  `tests/test_schema_describes_style_units.py` checks each worked example against this writer's XML and diffs the element position and style schema against the PHP reference (`scripts/php_jsonschema.php`).

- **`VERSION` reads the INSTALLED distribution metadata instead of a literal.** The literal was corrected by hand last release and pinned by a test, which re-syncs the copy rather than removing it. Reading the metadata means there is no second number left to drift.

- **The conformance pin moved from 0.20.0 to 0.21.2.** fancy-conformance 0.21.x shipped while this port still pinned 0.20.0, so its own guard test was red against the fixture checkout CI uses. All three tables were re-run first: `shared/strings` 8, `shared/decimal` 18, `dark-slide/table-cell-model` 26, nothing failed or skipped.


## [0.2.0] - 2026-09-10

Rich document constructs: per-cell table control, decorated text boxes,
paragraph controls, text inside shapes, and two composite elements. Pre-1.0, so
this lands in a MINOR.

### Added

- **Per-cell table control.** A `table` element resolves through a documented
  precedence chain — `cell > row > column > band (header|stripe|body) > table >
  theme > default` — and every cell now carries its own decisions:

  - **Borders**, per side, with a width in points, a colour and a
    `solid`/`dash`/`dot` style. Shorthands: a bare `{width,color}` for all four
    sides, `all`, and `outer` / `inner` which resolve by the cell's position in
    the grid. Any side can be switched off with `false`.
  - **Insets** (`style.padding`), a number for all four sides or a map naming
    the ones you want.
  - **Vertical anchor** (`style.anchor`: `top` / `middle` / `bottom`).
  - **Merging**: `colSpan` and `rowSpan` on a cell. Spans are clamped to the
    grid, and the cells a span covers are still emitted as continuations — a row
    with fewer cells than the grid declares is a corrupt file, not a narrow
    table.
  - **Column widths** (`width` on a column). Values `<= 1` are fractions of the
    table and columns without one share the remainder; any value `> 1` makes
    them all weights. Widths are accumulated and differenced so they sum to the
    table's width EXACTLY.
  - **Per-row and per-cell styling**: a row may be written as
    `{cells: {...}, fill, color, bold, align, anchor, fontSize, letterSpacing,
    caps, padding, borders, height}`, and any cell value may be an object
    carrying the same keys plus `text`.
  - **Band configuration**: `style.header` (or `false` for no header row),
    `style.body`, `style.stripe` (or `false` for no striping), `style.rowHeight`.

- **Decorated text boxes.** A `text` element's `style` takes `fill`, `border`,
  `padding`, `radius`, and `accentBar` — a coloured bar down one edge, drawn as
  a hard-stop `<a:gradFill>` so the bar and the tint are ONE shape. DrawingML
  has no per-side border on a shape, so this construct previously meant stacking
  a background rect, a thin rect and a text box in the right z-order.

- **Paragraph and run controls** on any text body: `lineHeight` (a multiple),
  `spaceBefore` / `spaceAfter` (points), `letterSpacing` (points), `caps`
  (`small` / `all`), and `bullet` — a literal character (which is all a
  check-mark list is), `none`, or `number`.

- **Text inside shapes.** A `shape` element takes `content`, `format` and
  `style`. Its text body used to be unconditionally empty.

- **Composite elements `kpiBand` and `metadataGrid`.** Authoring sugar: each
  expands into an ordinary `table` before anything is serialised, so they add no
  new OOXML and no new reader shape. A composite read back comes back as the
  table it became.

- **A reference deck fixture and its acceptance test.** A nine-slide deck built
  from the construct classes of a real paginated business document — metadata
  grid, KPI band, accent-bar callouts, tables with a highlighted total row,
  check-mark lists, a three-column comparison. It is the shared fixture for all
  three engines, compared byte-for-byte.

- **A cross-language conformance suite**, `dark-slide/table-cell-model` in
  `fancy-conformance`, pinning the resolver's decisions. Byte parity proves the
  engines agree on the inputs it runs; these rows walk the precedence chain one
  layer at a time, which byte parity on a single deck cannot.

### Changed

Six changes alter emitted bytes. Five need nothing from you; one can.

- **Table header fill and zebra derive from `theme.colors.accent`** instead of a
  hardcoded violet. `#8B5CF6` is the default accent, so a deck that sets no
  accent is unchanged. **What you must do:** nothing — unless your deck sets an
  accent and you wanted the violet, in which case set `style.header.fill`.

- **Table cells now state their borders.** Previously no line elements were
  emitted at all, which is not "no rules" — it is "unspecified", and each reader
  drew its own default table style. The default is now an explicit 0.75pt
  `#D9DEE4` grid, and "no border" is emitted as an explicit empty line rather
  than by omission. **What you must do:** nothing — unless you want no rules, in
  which case `style: {borders: false}`.

- **Cell insets and vertical anchor moved from `<a:bodyPr>` to `<a:tcPr>`**,
  which is where the schema puts them for a table cell. **What you must do:**
  nothing.

- **The table style id changed** from Medium Style 2 Accent 1 to No Style, No
  Grid. Every fill and rule is now stated per cell, so a built-in style is a
  second opinion layered on ours rather than a default to fall back on. **What
  you must do:** nothing — unless you relied on PowerPoint's own banding, which
  is now baked per cell and configurable.

- **`strokeWidth: 0` or `stroke: "none"` on a shape emits no outline.** It used
  to emit `<a:ln w="0">`, which every renderer draws as a hairline, so "no
  outline" was not sayable. **What you must do:** nothing — unless you relied on
  the hairline, in which case give `strokeWidth` a real value.

- **An object-valued table cell is now read as a cell SPEC** when it carries any
  of the spec keys (`text`, `fill`, `color`, `bold`, `italic`, `underline`,
  `align`, `anchor`, `fontSize`, `letterSpacing`, `caps`, `fontFamily`,
  `padding`, `borders`, `colSpan`, `rowSpan`). It used to be JSON-stringified
  into the cell text. **What you must do:** if you were deliberately displaying
  the JSON of an object that happens to carry one of those keys, wrap it —
  `{"text": "<the json>"}`. An object with NONE of those keys still stringifies
  exactly as before, so most callers are unaffected.

### Fixed

- **`version()` reports the version the package actually ships as.** It returned
  `0.1.0` from `0.2.0`. `test_version_is_single_sourced.py` has asserted this
  since it was written; the release preflight is what stood at it.


- **`theme.fonts.mono` now reaches the code it names.** It was accepted by the
  validator, published in the JSON Schema handed to an LLM as the tool
  definition, and described in the writer's own docblocks as the font code runs
  switch to — and applied nowhere. Both places that render code (block elements
  and inline `` `code` `` spans) hardcoded `Consolas`, so a brand deck asking for
  JetBrains Mono got Consolas, rendered perfectly, and was quietly off-brand.

  All three engines had it, identically, which is why no parity test caught it:
  **parity detects disagreement, and they agreed.**

  **What you must do: nothing.** A deck that sets no `fonts.mono` still renders
  in Consolas, byte for byte as before.

- **A code run written in a brand mono font reads BACK as code.** The reader
  identified code by looking for "consola", "mono" or "courier" in the typeface
  name — sound while the writer always emitted Consolas, and not sound once a
  deck can name its own font, since "Fira Code" and "Cascadia" contain none of
  those words. The deck's mono typeface is now recorded in `theme1.xml`'s
  `<a:extLst>` (there is no third slot in `<a:fontScheme>` for it) and matched
  exactly on read; the name sniff remains the fallback for files written by
  anything else, including earlier versions of this package.

- **A highlighted line no longer comes back shredded into one span per token.**
  A syntax highlighter emits one run per token and every one of them is code, so
  the reader emitted a marker per run: `const deck = 1;` returned with each pair
  of adjacent backticks closing one span and opening the next, meaning a
  re-parse yields the INVERSE of the emphasis it was preserving. Adjacent runs
  carrying the same decoration are now merged before anything is emitted, so the
  output no longer depends on how many runs the writer split the text into.

- **The reader dropped the first data row of a header-less table.** It assumed
  row 0 was always a header; whether it is one is declared by
  `<a:tblPr firstRow="1">`. Header-less tables only became ordinary with this
  release — every `metadataGrid` and `kpiBand` is one — so the bug is new
  surface rather than an old one, but the reader now honours the declaration.

- **Column widths declared on a column were discarded**, and every table was an
  equal split. The reader also now recovers widths as fractions.

## [0.1.0] - 2026-08-18

### Added

- **Initial release: the Python member of the `dark-slide` trio.** A
  zero-dependency `.pptx` writer and reader, mirroring PHP
  `particle-academy/dark-slide` and Node `@particle-academy/dark-slide`. The
  same deck goes in and the same document comes out, whichever backend runs it.

- **Byte-level writer parity with the PHP engine, as a test result.** The suite
  drives the PHP writer as a subprocess and diffs every OOXML part for every
  fixture. One part is excused, with the reason recorded in
  `KNOWN_DIVERGENT_PARTS`: `docProps/core.xml` carries a write-time timestamp
  PHP offers no way to pin, so this port takes the document date from
  `metadata.created` / `metadata.modified` and is byte-stable instead. Every
  other byte of that part matches.

- **Structural reader parity with the PHP engine.** The same `.pptx` handed to
  both readers recovers the same deck — compared structurally, with only the
  volatile import `id` and the PHP empty-array/empty-object ambiguity
  normalised away.

- **The Agent surface** as module-level functions: `validate`,
  `validate_and_repair`, `to_bytes`, `write`, `read`, `from_bytes`, `describe`,
  `json_schema`, `version`. `write` is synchronous (PHP's is; Node's is async
  only because browsers have no synchronous filesystem) and `read` accepts
  **both bytes and a path**, resolving a real PHP↔Node divergence rather than
  picking a side.

- **`php_round`, and a test that forbids the builtin.** Python rounds half to
  even and PHP rounds half away from zero, and every coordinate in a deck is a
  `round(fraction × 9144000)`. An AST walk over the package fails the build if
  `round()` is called anywhere, and the `roundingTies` fixture pins two real
  ties against the PHP oracle.

- **The image-header sniffer covers PNG, JPEG, GIF, WebP and BMP**, and is held
  to PHP's `getimagesizefromstring` by a cross-runtime test. That is wider than
  the Node port, which reads PNG/GIF/JPEG only — so a WebP with `fit: cover`
  gets a real centre-crop here and in PHP, and a stretched fill in Node.

- **The `imageRelIds` fixture**, pinning a defect rather than hiding it. Image
  relationship ids come from a global media counter while a slide's own rels
  start at `rId1`, so a single image on a single slide emits two
  `<Relationship Id="rId1">` entries — a malformed OPC package that every
  engine has always written. It is reproduced here deliberately: fixing one
  engine alone would break part-level parity, so the fix has to land in all
  three at once, and this fixture is what will prove it did.

### Security

- **`allow_http_images` defaults to `False`.** A document naming an `http(s)`
  image does not cause a request; the caller opts in. A fixture asserts the
  default emits a placeholder and fetches nothing.
- **The reader refuses a DOCTYPE before parsing.** A `.pptx` never legitimately
  contains one, and the input is a file someone uploaded.

[Unreleased]: https://github.com/Particle-Academy/dark-slide-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Particle-Academy/dark-slide-py/releases/tag/v0.1.0
