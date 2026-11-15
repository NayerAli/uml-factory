"""Agent générateur Rust.

Modifiable à la main. Pour retirer ce langage, supprimer ce fichier :
le noyau n'a pas à changer.
"""

from __future__ import annotations

from ._declarative import CommandGenerator


class RustGenerator(CommandGenerator):
    language = "rust"
    display_name = "Rust"

    file_extensions = (".rs",)

    source_media_type = "text/rust"

    plan_rules = (
        "Place each type in its own PascalCase.rs file. "
        "Organize files using Rust modules matching UML packages."
    )

    style_rules = (
        "Rust rules:\n"
        "- Target Rust 2021 edition.\n"
        "- Map UML classes to structs.\n"
        "- Map UML interfaces to traits.\n"
        "- Map UML enums to enums.\n"
        "- Use snake_case for fields and methods.\n"
        "- Use PascalCase for structs, traits and enums.\n"
        "- Use Option<T> for optional values.\n"
        "- Use Vec<T> for multiplicities greater than one.\n"
        "- Represent operations in impl blocks.\n"
        "- Use ownership and borrowing idioms.\n"
        "- Prefer derives when appropriate (Debug, Clone, Default).\n"
        "- Use only Rust standard library.\n"
        "- Generated code must compile with stable rustc.\n"
    )

    tools = ("rustc",)

    build = (
        "rustc",
        "--edition",
        "2021",
        "{file}",
    )

    scaffold = {}

    sensitive_calls = (
        "std::process::Command",
        "Command::new(",
        "unsafe",
        "std::env::var",
        "std::env::vars",
        "std::fs::remove_file",
        "std::fs::remove_dir",
        "std::fs::remove_dir_all",
        "std::net::TcpStream",
        "std::net::UdpSocket",
        "libloading",
        "dlopen",
    )

    conformity_rules = (
        "Rust conformity:\n"
        "- A UML class is a struct with the same name.\n"
        "- A UML interface is a trait with the same name.\n"
        "- A UML enum is an enum with the same name.\n"
        "- Attributes are struct fields.\n"
        "- Operations are methods in impl blocks.\n"
        "- Inheritance is represented through traits and composition.\n"
        "- Optional relations use Option<T>.\n"
        "- Multi-valued relations use Vec<T>.\n"
        "- Names are compared ignoring case and underscores.\n"
        "- Every class, attribute, relation and operation from the UML model must exist.\n"
    )

    status = "validated"
    score = 100