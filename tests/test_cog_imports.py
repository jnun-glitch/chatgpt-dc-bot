"""Import- und Setup-Smoketests für alle dynamisch geladenen Cogs."""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import cogs


def test_every_cog_imports_and_exposes_setup():
    modules = sorted(
        module.name
        for module in pkgutil.iter_modules(cogs.__path__)
        if not module.name.startswith("_")
    )
    assert modules, "Keine Cogs gefunden"

    failures = {}
    missing_setup = []
    for name in modules:
        try:
            module = importlib.import_module(f"cogs.{name}")
            setup = getattr(module, "setup", None)
            if setup is None or not inspect.iscoroutinefunction(setup):
                missing_setup.append(name)
        except Exception as exc:  # pragma: no cover - failure details are asserted below
            failures[name] = f"{type(exc).__name__}: {exc}"

    assert not failures, "Nicht importierbare Cogs: " + repr(failures)
    assert not missing_setup, "Cogs ohne async setup(): " + repr(missing_setup)
