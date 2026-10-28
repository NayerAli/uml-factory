"""Agent générateur PHP. Fichier créé par « Autre langage… » le 2026-10-28 (score 100/100, statut validated).

Modifiable à la main. Pour retirer ce langage, supprimer ce fichier : le noyau n'a pas à changer.
"""

from __future__ import annotations

from ._declarative import CommandGenerator


class PhpGenerator(CommandGenerator):
    language = 'php'
    display_name = 'PHP'
    file_extensions = ('.php',)
    source_media_type = 'text/x-php'
    plan_rules = 'Place each type in its own PascalCase.php file, with files organized into folders matching their namespaces.'
    style_rules = (
        'PHP rules:\n'
        '- Target PHP 8.1 or later and include `<?php` in every file.\n'
        '- Map concrete classes to classes, abstract classes to `abstract class`, interfaces to `interface`, and enums to backed enums when values are specified or pure enums otherwise.\n'
        '- Use `public`, `protected`, or `private` visibility explicitly; use typed properties and method signatures where types are known.\n'
        '- Represent attributes as typed properties, using nullable types for optional values and idiomatic getter/setter methods when properties are non-public.\n'
        '- Map inheritance with `extends` and interface realisation with `implements`.\n'
        '- Represent relations with the related type for a maximum of one, nullable related types for optional relations, and arrays documented as `list<Type>` when the maximum cardinality is above 1.\n'
        '- Use namespaces and imports with `namespace` and `use` as needed.\n'
        '- Use ONLY the PHP standard library so the generated code compiles without third-party dependencies.\n'
    )
    tools = ('php',)
    build = ('php', '-l', '{file}')
    scaffold = {}
    sensitive_calls = ('exec(', 'shell_exec(', 'system(', 'passthru(', 'proc_open(', 'popen(', 'curl_init(', 'fsockopen(', 'pfsockopen(', 'stream_socket_client(', 'socket_create(', 'gethostbyname(', 'unlink(', 'rmdir(', 'getenv(', 'putenv(', '$_ENV')
    conformity_rules = (
        'PHP conformity:\n'
        '- A class, abstract class, interface or enum of the diagram is a `class`, `abstract class`, `interface` or `enum` declaration with the same name.\n'
        '- An attribute is a property declared with `$` (for example `private string $nom`); its name is compared without the `$`.\n'
        '- An operation is a `function name(` declaration (a getter or setter counts only if the diagram lists it).\n'
        '- Inheritance is `extends Parent` and interface realisation is `implements Interface`.\n'
        '- A relation is a property (or constructor parameter) typed with the other class, or an array documented as `list<Other>` when the maximum cardinality is above 1.\n'
        '- Names are compared ignoring case and underscores; every class, attribute, operation, inheritance and relation of the diagram must be found.\n'
    )
    status = 'validated'
    score = 100
