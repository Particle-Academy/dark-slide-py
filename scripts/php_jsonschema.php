<?php

declare(strict_types=1);

/**
 * Cross-runtime schema helper: print the PHP dark-slide's `Agent::jsonSchema()`
 * as JSON, so the Python port can diff its own export against the reference.
 * Same minimal PSR-4 autoloader as `php_tobytes.php`; no composer needed.
 *
 *   php php_jsonschema.php
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

echo json_encode(\DarkSlide\Agent::jsonSchema(), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
