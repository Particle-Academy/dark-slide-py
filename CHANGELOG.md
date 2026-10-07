# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Pre-1.0: breaking changes land in MINOR releases.** Until `1.0.0` a bumped
minor may change an API, so read the entry before upgrading — the version
number cannot make a promise the 0.x range does not allow it to keep.

## [Unreleased]

## [0.4.0] - 2026-10-07

### Added

- **The published schema now carries the ITEM shape of a table's ``columns`` and
  ``rows``**, mirroring PHP ``Schema::tableColumnsJsonSchema()`` /
  ``tableRowsJsonSchema()`` byte for byte. It exported ``{"type": "array"}`` and
  nothing more, so a tool vocabulary generated from ``json_schema()`` could not
  teach an author that a column's ``key`` is what every row is keyed BY. Reported as
  fancy-slides#14.

- **``validate()`` flags a table row that matches no column**, as PHP's does. A
  positional row, a partially-filled row and a row carrying only style are not
  flagged; the hint names the keys that would have worked.

### Changed

- **A table row given as a LIST is now read in COLUMN ORDER** rather than DROPPED
  FROM THE DECK. ``rows: [["Starter", "$49"]]`` means
  ``[{"plan": "Starter", "price": "$49"}]``. The grid loop tested
  ``is_plain_object(row)`` and ``continue``d, so a list row vanished -- while the
  PHP engine kept it and emitted a row of empty cells. Three engines held to
  byte-identical OOXML disagreed on the ROW COUNT of the same deck, silently.

  **Nothing a consumer did stops working**: a keyed row is unchanged, and a list row
  produced no row at all before. Pinned cross-language by ``fancy-conformance``
  0.34.0 rows 0029-0033.

- ``table_resolver.STYLE_KEYS`` and ``ROW_KEYS`` are public, so the validator reads
  the same list the resolver does rather than a second copy of it.

- Pinned ``fancy-conformance`` fixtures move 0.22.1 -> 0.34.0.

### Fixed

- **The PHP schema-parity check compared a HAND LIST of seven element properties**,
  so ``columns`` and ``rows`` sat outside it and went years undescribed in all three
  engines with the check green. It now compares every element property, and asserts
  the key sets match.

### Fixed

- **Documentation: the reader docstring no longer implies this package diffs
  decks.** It described how a clock- or RNG-derived id "turns a one-element edit
  into a whole-deck diff" without saying where the differ lives — which reads as
  a promise that something upstream handles it. ``Differ``, ``Reducer`` and the
  ``DeckOp`` vocabulary are **PHP-only**; there is no diff surface here. A
  consumer of this package writes their own comparison and nothing in this repo
  guards it. What is owed here is a pure ``read()``, and that is now what the
  docstring claims. Raised by a consumer.

## [0.3.3] - 2026-09-16

**The third attempt at one defect, and the one that changes its basis.** The
history matters if you are deciding whether to upgrade:

| | id derived from | how it failed |
|---|---|---|
| `0.3.0` | `time.time()` at READ time | intermittent — same file, two reads, ~1 in 5 |
| `0.3.1` | CRC-32 of the whole package | the package embeds a save timestamp, so it followed the WRITER's clock: every save, every time |
| `0.3.2` | CRC-32 of the package minus `docProps/core.xml` | removed the clock, kept a bytes-derived id |
| **0.3.3** | **CRC-32 of the deck `read()` returns** | — |

0.3.2 removed one source of byte variance and left the others. Two
serialisations of one deck are simply not byte-equal: re-saving a deck that
carries a shape or a code block rewrites `ppt/slides/slideN.xml` whatever the
timestamp says. **Bytes were the wrong basis** — a digest of bytes identifies a
serialisation, not a deck — and no exclusion list was going to fix that.

The guarantee now, stated precisely because the loose version is wrong:

> **Any two byte layouts that read to the same structure get the same id.**

It does **not** say a file from another producer and one of ours "of the same
deck" share an id. That holds only as far as `read()` normalises them to the
same structure, which is not promised and is not what this fixes.

Measured on the case that survived 0.3.2: a deck whose only element is a shape,
written, read, and written again. The two packages differ in
`ppt/slides/slide1.xml`; before this release the ids differed with them, and now
they do not.

All three engines ship it together: `particle-academy/dark-slide` 0.10.3 and
`@particle-academy/dark-slide` 0.8.3, and all three derive the id identically
(verified by reading one file with all three).

Worth repeating from 0.3.2: this port's own writer never stamped the clock, so
the 0.3.1 failure was milder here — but the 0.3.2 failure was NOT, because byte
variance is not only the timestamp.

### Added

- **`tests/pptx/foreign-libreoffice.pptx` — the first `.pptx` fixture this
  package has ever had.** Every other fixture is generated by our own writer at
  test time, so nothing exercised a foreign serialisation: the same blind spot
  left the reader's `random.randint()` path unexercised for several releases. It is
  produced with LibreOffice (an independent producer, not PowerPoint) and the
  regeneration command is in the purity suite's docblock.

### Changed

- **Renaming a deck changes its id again.** 0.3.2 had it not change, as a side
  effect of excluding `docProps/core.xml` whole — `<dc:title>` lives in that
  part. A title is content: `read()` returns it, so it counts. If you shipped
  against 0.3.2 and relied on a rename being id-neutral, it no longer is.

- **If you PERSISTED diffs, this is a data-format change** — the same clause as
  0.3.2, now with one more scheme in the window. Read this only if you store
  diffs as rows; if you diff transiently, or do not diff at all, there is nothing
  to do.

  Ordinary edits emit targeted ops, which carry no deck id and are unaffected.
  But **a diff taken while two ids had diverged emits a whole-deck `replace`, and
  that payload carries the id.** Those rows are already written and we cannot
  rewrite them. Replaying one restores a deck bearing an old-scheme id, so the
  next diff against a freshly-read deck sees a mismatch and emits another full
  replace.

  **It is not corruption.** The op carries everything it needs, so a restore
  still returns the correct bytes — this degrades **storage**, not correctness.
  It is self-limiting to the window in which a diverging id was live.

  **What to do:** nothing is a legitimate choice — you keep paying full price for
  that window and nothing breaks. If you would rather reclaim it, re-baseline the
  affected chains (re-read, re-diff) and compactness returns. There is no
  migration script and there will not be one: those rows live in your store, in
  your shape, and anything generic we shipped would be guessing at both.

### Fixed

- **A deck saved and re-read keeps its id, whatever moved in the bytes.** The
  digest is over a canonical encoding of the deck itself. That encoding is a
  cross-engine contract — all three engines implement the same one and the
  reader-parity suites compare the resulting id — and it is written out in full
  in each reader: numbers as raw IEEE-754 bits (the three languages disagree
  about a number's TYPE, and PHP's float rendering depends on a `php.ini`
  setting a consumer can change), length-prefixed strings, one marker for an
  empty list or map (PHP cannot tell them apart), and sorted keys.

## [0.3.2] - 2026-09-16

**A fix to a fix: 0.3.1 moved this defect rather than removing it.** That release
made the deck id CRC-32 of the whole package — and the package embeds a
write-time stamp in `docProps/core.xml`, so the clock read moved out of the
reader and into the writer. Two reads of one buffer agreed, which is why every
test passed, but a deck saved and re-read got a **different id every single
time** instead of one time in five.

That is strictly worse than what it replaced: an intermittent flake became a
deterministic break. It took out **pptx version history in a consumer's shipped
product** — a feature, not a format unit test — because every version in the
chain was serialised at a different moment.

The id is now derived from the package's entries **excluding
`docProps/core.xml`**. Measured, not guessed: of a 43-entry package written
either side of a second boundary, that is the only entry that differs. Saving a
deck that changed nothing now yields the same id. Everything else about the id
is unchanged — CRC-32, same algorithm in all three engines, same cross-engine
agreement.

All three engines ship it together: `particle-academy/dark-slide` 0.10.2 and
`@particle-academy/dark-slide` 0.8.2.

**This port's own writer never had the write-time half.** `_build_core_props`
stamps `EPOCH_TIMESTAMP` and honours `metadata.created`, so `to_bytes()` here is
already deterministic and a Python-only round trip was never affected. The fix
still matters, and ships: a Python consumer overwhelmingly reads packages the
PHP or Node engines wrote, and those do stamp the clock.

### Changed

- **A deck's `<dc:title>` is outside the id, so renaming a deck does not change
  it.** `<dc:title>` shares `docProps/core.xml` with the save timestamp, and the
  exclusion is the whole part. The returned `title` still changes, so a differ
  still sees a rename; only the id holds still. Narrowing the exclusion to the
  two `<dcterms:*>` elements would change this, at the cost of regexing XML
  inside the digest path in three engines — measured as unnecessary and
  deliberately not done. Pinned by a test so it stays a decision.

- **If you PERSISTED diffs, this is a data-format change.** Read this only if
  you store diffs as rows; if you diff transiently, or do not diff at all, there
  is nothing to do.

  Ordinary edits emit targeted ops, which carry no deck id and are unaffected.
  But **a diff taken while two ids had diverged emits a whole-deck `replace`,
  and that payload carries the id.** Those rows are already written and we
  cannot rewrite them. After this fix, replaying one restores a deck bearing an
  old-scheme id, so the next diff against a freshly-read deck sees a mismatch
  and emits another full replace.

  **It is not corruption.** The op carries everything it needs, so a restore
  still returns the correct bytes — this degrades **storage**, not correctness.
  It is also self-limiting: only diffs captured while the bug was live carry an
  id, so the window bounds itself, and history written before or after stays
  compact.

  **What to do:** nothing is a legitimate choice — you keep paying full price
  for that window and nothing breaks. If you would rather reclaim it, re-baseline
  the affected chains (re-read, re-diff) and compactness returns. There is no
  migration script and there will not be one: those rows live in your store, in
  your shape, and anything generic we shipped would be guessing at both.

### Fixed

- **`read()` is a pure function of its bytes, including across a save.**
  Previously the id was CRC-32 of the whole package, so it followed
  `the writer's clock stamp` at write time. ``tests/test_reader_is_pure.py`` covers it
  with the case the earlier tests all missed: a deck serialised, read,
  re-serialised a second later and re-read must come back identical. Every test
  in that file had read ONE buffer twice, which is exactly the blind spot a
  defect one serialisation away sits in.

## [0.3.1] - 2026-09-16

**`read()` is a pure function of its bytes again.** Reading the same `.pptx`
twice returned two different structures, so a consumer diffing two reads of an
unchanged file saw the whole deck replaced — a save that changed nothing storing
the entire deck. Reported against the PHP engine as
[dark-slide#9](https://github.com/Particle-Academy/dark-slide/issues/9); this
port had it identically.

All three engines are fixed together: `particle-academy/dark-slide` 0.10.1 and
`@particle-academy/dark-slide` 0.8.1 ship the same change, and all three now
derive the deck id the same way, so any two of them read one file to the same id.

### Changed

- **Generated import ids have a new shape.** The deck id is now
  `imported-<crc32>` — eight hex digits of the file's own CRC-32, from `zlib`
  rather than any new dependency — and an element whose `<p:cNvPr>` carries no
  `name` to borrow one from is `imported-<slide>-<nth>`, its position in the
  file.

  **What to do: almost certainly nothing.** The old values came from
  `time.time()` and `random.randint()`, so no import id was ever reproducible and
  nothing could have been keyed on one. Only code that PARSES an import id —
  expecting exactly six hex digits after `imported-`, say — needs a look.

### Fixed

- **The deck id came from the clock.** `PptxReader` minted it from
  `time.time()`, so the same file read either side of a second boundary came back
  with a different id. It also COLLIDED: every deck imported in the same second
  shared one id.

- **An element with no `<p:cNvPr>` `name` got a random id** —
  `random.randint(1000, 9999)`, redrawn on EVERY read rather than only across a
  tick, and therefore the worse half. A deck DarkSlide wrote always names its
  shapes, so its own output never reached this path and no round-trip test could
  see it; files from other producers reach it constantly.

- **The reader-parity suite could catch neither**, because it DELETED the deck id
  before comparing against the PHP oracle. A comparison that drops the field it
  cannot explain asserts nothing about it, and a parity suite only ever detects
  DISAGREEMENT — three ports with the same bug agree perfectly. It now compares
  the id like every other field, and a new `tests/test_reader_is_pure.py` asserts
  the property directly, including for elements that have no name to borrow.

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

- **The reader reads geometry against the file's own slide size** (`<p:sldSz>`) instead of assuming 16:9, and returns `theme.aspectRatio` (always a float) for any other shape. A 4:3 deck's `y` of 0.5 used to read back as 0.667.

- **Rounded corners are the radius asked for.** A roundRect corner is `min(w, h) * adj / 100000` (LibreOffice's preset table); decorated text boxes divided by half the shorter side and drew every corner twice as round. `rounded-rect` shapes now take `radius` (design px, default 8, and the default again when `radius` is not a number) instead of PowerPoint's default corner; the element `radius` is described in the published schema.

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

- **The parity suite compares binary parts as bytes.** It decoded every part as UTF-8 with replacement, so two different images, or any two invalid byte sequences, could read equal. Only `.xml` and `.rels` parts are compared as text now; everything else, media included, byte for byte.

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
