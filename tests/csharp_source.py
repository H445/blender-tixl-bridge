"""Small standard-library helpers for compiling extracted production C# code."""
from __future__ import annotations

import re
from pathlib import Path


def extract_declaration(source: str, pattern: str, label: str = "C# declaration") -> str:
    """Return the complete brace-delimited declaration matched by ``pattern``.

    The scanner skips normal strings, chars, and comments so braces in JSON
    literals or comments do not truncate the extracted production source.
    ``pattern`` should include the desired declaration's opening signature.
    """
    match = re.search(pattern, source)
    if not match:
        raise RuntimeError(f"Could not find production {label}")
    opening = source.find("{", match.end())
    if opening < 0:
        raise RuntimeError(f"Could not find the opening brace for production {label}")
    depth, index, state = 0, opening, "code"
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "/" and next_char == "/":
                state, index = "line-comment", index + 1
            elif char == "/" and next_char == "*":
                state, index = "block-comment", index + 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[match.start():index + 1]
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif state == "line-comment" and char == "\n":
            state = "code"
        elif state == "block-comment" and char == "*" and next_char == "/":
            state, index = "code", index + 1
        index += 1
    raise RuntimeError(f"Could not find the closing brace for production {label}")


def extract_class(source: str, name: str) -> str:
    declaration = extract_declaration(source,
        rf"\bprivate\s+sealed\s+class\s+{re.escape(name)}\b", f"nested class {name}")
    return declaration.replace("private sealed class", "internal sealed class", 1)


def extract_static_class(source: str, name: str) -> str:
    declaration = extract_declaration(source,
        rf"\bprivate\s+static\s+class\s+{re.escape(name)}\b", f"nested static class {name}")
    return declaration.replace("private static class", "internal static class", 1)


def extract_method(source: str, pattern: str, label: str) -> str:
    return extract_declaration(source, pattern, label)


def write_net8_project(project: Path, name: str, program: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / f"{name}.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
        "  <PropertyGroup>\n"
        "    <OutputType>Exe</OutputType>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <ImplicitUsings>enable</ImplicitUsings>\n"
        "    <Nullable>enable</Nullable>\n"
        "    <LangVersion>latest</LangVersion>\n"
        "  </PropertyGroup>\n"
        "</Project>\n", encoding="utf-8")
    (project / "Program.cs").write_text(program, encoding="utf-8")
