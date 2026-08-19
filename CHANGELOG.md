# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Pre-1.0: breaking changes land in MINOR releases.** Until `1.0.0` a bumped
minor may change an API, so read the entry before upgrading — the version
number cannot make a promise the 0.x range does not allow it to keep.

## [Unreleased]

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
