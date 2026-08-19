<?php

declare(strict_types=1);

/**
 * Cross-runtime helper for the image-header sniffer.
 *
 * The writer needs a picture's intrinsic pixel size to honour `fit: cover` and
 * `fit: contain`. PHP gets it from `getimagesizefromstring()`; this port
 * hand-rolls it from the file headers, because taking an imaging dependency
 * would put a third party in charge of a byte the parity suite compares.
 *
 * "Hand-rolled to match PHP" is a claim, so this script makes it testable:
 * given a directory of raw image headers, print `{name: [width, height]}` (or
 * null) exactly as PHP sees them, and let the Python suite diff.
 *
 *   php php_imagesize.php <dir-of-.bin-files>
 *
 * No autoloader needed — this calls a PHP builtin, not the package.
 */

if ($argc < 2) {
    fwrite(STDERR, "usage: php php_imagesize.php <dir>\n");
    exit(2);
}

$dir = rtrim($argv[1], '/\\');
if (! is_dir($dir)) {
    fwrite(STDERR, "not a directory: {$dir}\n");
    exit(3);
}

$out = [];
foreach (glob($dir.'/*.bin') ?: [] as $file) {
    $name = basename($file, '.bin');
    $info = @getimagesizefromstring((string) file_get_contents($file));
    $out[$name] = $info === false ? null : [(int) $info[0], (int) $info[1]];
}

ksort($out);
echo json_encode($out);
