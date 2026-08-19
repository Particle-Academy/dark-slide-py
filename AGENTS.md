# AGENTS.md — dark-slide (Python)

This file describes **this repository's code**: its API, its invariants, and the
traps in it. Process rules — release lifecycle, publishing, version policy,
backports — live in the envelope's `AGENTS.md` and must never be copied here; a
copy on a maintenance branch would freeze a rule that has since changed, with
nothing to flag it.

## What this is

A `.pptx` writer + reader with **no runtime dependencies, permanently**. It is
one of three engines that must produce the same document from the same deck:

| | |
|---|---|
| PHP | `particle-academy/dark-slide` — **the reference** |
| Node | `@particle-academy/dark-slide` |
| Python | this repo |

The deck model is plain `dict`s and the `Validator` is the gate. `schema/types.py`
holds `TypedDict`s for editor support only; nothing enforces them at runtime, and
nothing should. Loose agent JSON is the *input format*, and
`validate_and_repair()` exists to rescue it.

## The invariant everything else serves

> **`to_bytes()` must emit byte-identical OOXML parts to the PHP engine.**

`tests/test_parity_php.py` runs the PHP writer as a subprocess and diffs every
part for every fixture. That is the definition of done for any writer change.
It follows that:

- **Never build XML with `ElementTree` on the write side.** Attribute order,
  self-closing style, and the absence of inter-element whitespace are all part
  of the output. `helpers/xml.py` is an escaper, not a serialiser, and the
  writer concatenates strings.
- **`helpers/xml.text` and `helpers/xml.attr` escape different sets**, and the
  asymmetry is load-bearing: `text` leaves the apostrophe alone, `attr` writes
  `&apos;` (the `ENT_XML1` entity — *not* `&#039;`, whatever a spec says;
  the parity suite checks it against the engine).
- **Which parts exist is contract.** No `notesMasters/`, no `presProps.xml`, no
  `tableStyles.xml`. All eight `slideLayout` parts always ship. Notes parts are
  numbered by SLIDE, so the sequence has gaps.
- **The zip container is NOT compared and never can be.** PHP writes DEFLATE
  with real mtimes through `ZipArchive`; this writes STORE with a fixed
  1980-01-01 DOS date. The comparison unzips both and diffs parts, which is the
  real contract anyway — a reader sees parts, never the compression.

## Traps

### 1. `round()` is the wrong function here. Always.

Python rounds half to **even**; PHP rounds half **away from zero**. Every
coordinate in every deck is `round(fraction * 9144000)`, so this is not a corner
case — it is a one-EMU shift in thousands of attributes.

Use `helpers.emu.php_round`. Nothing in the package may call the builtin, and
`test_no_module_in_the_package_calls_the_builtin_round` parses the AST to prove
it. The `roundingTies` fixture pins two real ties (`3/128 × 9144000` and
`3/8 × 5143500`, both exactly `.5` over an even integer) against the oracle.

The one exception is documented at its site: `_num_str`'s `"%.6f"` is safe
because **no IEEE-754 double is an exact tie at six decimal places** — that
would require `5·10⁻⁷` to be a dyadic rational, and it is not — so the rounding
mode cannot matter there.

### 2. PHP's loose types are reproduced on purpose (`util.py`)

Five of them change emitted bytes, and Python's instincts are wrong on all five:

- `php_string(True)` is `"1"`, `php_string(12.0)` is `"12"`, and
  `php_string(1/3)` is `"0.33333333333333"` (precision 14, not `repr`).
- `php_truthy("0")` is **False**. A slide whose `notes` is `"0"` gets no notes
  part; `bool("0")` would give it one.
- `is_numeric` follows PHP: `"1e5"` is numeric and worth 100000, `" 12 "` is
  numeric with whitespace on both ends.
- `php_float("12abc")` is `12.0`, not an error.
- `php_json_encode` uses compact separators and escapes `/` as `\/`.

### 3. String indexing is a THIRD scheme, and it agrees by accident

PHP indexes the markdown tokenizer and the syntax highlighter by **byte**; the
Node port by **UTF-16 code unit**; Python by **codepoint**. All three agree, and
the reason is worth keeping in mind before any "tidy": every cut is at an ASCII
marker, and no UTF-8 continuation byte or UTF-16 surrogate half can equal an
ASCII byte. The `unicodeText` fixture and the `fancy-conformance`
`shared/strings` suite pin it. Changing either tokenizer to slice differently
would be invisible in every existing test but this one.

### 4. Read XML with a parser — but reject DOCTYPE first

`reader/pptx_reader.py` uses `xml.etree.ElementTree` and matches on LOCAL names,
ignoring namespace binding. That is fine: nothing is serialised on the read
side, so no byte contract exists to protect.

`_parse_xml` refuses any input containing `<!DOCTYPE` **before the parser sees
it**. A `.pptx` never legitimately carries one, and the input is a file someone
uploaded.

### 5. `allow_http_images` defaults to `False`, and stays that way

Fetching a URL named inside a document is an SSRF surface. `data:` URIs,
`file://` and local paths work unconditionally; `http(s)` needs
`{"allow_http_images": True}` from the caller. The `imageFallback` fixture
asserts the default emits an `[image: …]` placeholder and makes no request.

### 6. Determinism is required, so the clock is an INPUT

`test_determinism.py` asserts byte stability, and `fancy-conformance` treats a
determinism flag as a precondition for a writer suite. PHP stamps
`docProps/core.xml` with `gmdate()` at write time and offers no way to pin it,
so this port reads `metadata.created` / `metadata.modified` when the deck
supplies them and falls back to `EPOCH_TIMESTAMP` otherwise. That is the ONE
entry in `KNOWN_DIVERGENT_PARTS`, and it names the reason.

### 7. The rel-id collision is reproduced, not fixed

Image relationship ids come from a **global** media counter, while a slide's
own rels start at `rId1` = layout and `rId2` = notesSlide. So one image on one
slide already emits two `<Relationship Id="rId1">` entries. Relationship ids
must be unique within a part, so the package is malformed — and every `.pptx`
with an image that any of the three engines has ever written carries it.

**Do not fix it here.** Fixing one engine alone breaks part-level parity, which
is the only cross-runtime guarantee the trio has; the ruling is one coordinated
release across every engine. The allocation site carries a `RULING PENDING:`
comment, the `imageRelIds` fixture pins the current bytes, and
`tests/test_relationship_id_collision.py` asserts the defect is still present —
so the day the engines are fixed together, it fails and gets deleted.

### 8. Python never casts a deciding vote on an open ruling

Where the PHP and Node engines already disagree, **this port follows PHP**, so
the tally stays 2-1 in the direction already recorded rather than becoming a
three-way split. The live ones, all with tests:

| Behaviour | PHP (and this port) | Node |
|---|---|---|
| `chart.mode` default | `"png"` — a pre-rendered `data:` image wins over a translatable `option` | always tries native translation first |
| `{"id": null}` in the validator | no error (`isset()` is false for null) | flagged as a type error |
| non-base64 `data:` URIs | percent-decoded to **bytes** | re-encoded as UTF-8, corrupting binary |
| intrinsic size of a WebP / BMP | read, so `fit: cover` crops correctly | unread, so it stretches |
| `option.categories` with no `xAxis` | ignored (a shared wart, pinned) | same |

## Layout

```
src/dark_slide/
  __init__.py            the public façade
  agent.py               the Agent surface as module-level functions
  exceptions.py          SchemaException (carries the structured error list)
  util.py                PHP loose-typing semantics, written down once
  schema/                schema.py · validator.py · repairer.py · types.py
  writer/pptx_writer.py  string building; the byte contract lives here
  reader/pptx_reader.py  ElementTree; best-effort, degrades rather than raises
  helpers/               xml · color · emu (php_round) · markdown_inline
                         · syntax_highlighter · chart_translator
```

## Running the suite

```
PHP_BIN='/path/to/php' python -m pytest
```

`pythonpath = ["src"]` is set, so a bare checkout with nothing but pytest runs
it. **A missing PHP is a skip locally and a hard failure under `CI`** — a
parity suite that quietly stops comparing anything reads exactly like one that
compares everything, which is how two sibling suites reported green over zero
coverage for months.
