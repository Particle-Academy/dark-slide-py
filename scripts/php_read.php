<?php

declare(strict_types=1);

/**
 * Cross-runtime READER helper: parse a .pptx with the PHP dark-slide reader and
 * print the resulting deck as JSON, so the Python port's reader can be diffed
 * against it. The twin of php_tobytes.php, and it uses the same minimal PSR-4
 * autoloader — the PHP core is zero-dependency, so no composer is needed.
 *
 *   php php_read.php <in.pptx>
 *
 * `DARK_SLIDE_PHP_SRC` is checked before the sibling checkout, for the same
 * reason it is there: a hard-coded sibling path resolves only inside the .agi
 * envelope, so any other layout would silently get no comparison at all rather
 * than an error.
 */

spl_autoload_register(function (string $class): void {
    $prefix = 'DarkSlide\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $rel = substr($class, strlen($prefix));
    $root = getenv('DARK_SLIDE_PHP_SRC') ?: __DIR__.'/../../dark-slide/src';
    $file = rtrim($root, '/').'/'.str_replace('\\', '/', $rel).'.php';
    if (is_file($file)) {
        require $file;
    }
});

if ($argc < 2) {
    fwrite(STDERR, "usage: php php_read.php <in.pptx>\n");
    exit(2);
}

// Fail loudly rather than dying on "class not found" from deep inside the
// reader, which reads like a parity failure and is not one.
if (! class_exists(\DarkSlide\Agent::class)) {
    fwrite(STDERR, "DarkSlide\\Agent not found. Set DARK_SLIDE_PHP_SRC to the PHP package's src/ directory.\n");
    exit(3);
}

echo json_encode(\DarkSlide\Agent::read($argv[1]), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
