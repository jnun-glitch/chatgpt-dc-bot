"""Import-Smoketests für alle dynamisch geladenen Cogs."""
from __future__ import annotations

import importlib
import pkgutil

import cogs


def test_every_cog_imports_successfully():
    modules = sorted(
        module.name
        for module in pkgutil.iter_modules(cogs.__path__)
        if not module.name.startswith("_")
    )
    assert modules, "Keine Cogs gefunden"

    failures = {}
    for name in modules:
        try:
            importlib.import_module(f"cogs.{name}")
        except Exception as exc:  # pragma: no cover - failure details are asserted below
            failures[name] = f"{type(exc).__name__}: {exc}"

    assert not failures, "Nicht importierbare Cogs: " + repr(failures)
