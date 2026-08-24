# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Pre-1.0: breaking changes land in MINOR releases.** Until `1.0.0` a bumped
minor may change an API, so read the entry before upgrading — the version
number cannot make a promise the 0.x range does not allow it to keep.

## [Unreleased]

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
