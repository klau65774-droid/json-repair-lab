"""Load the unmodified parser sources from the bundled v0.64.9 release."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from functools import lru_cache
from importlib import import_module
from importlib.util import module_from_spec
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, cast
from zipimport import zipimporter

from .guard import charge_work, validate_budget, work_budget
from .syntax import meter_parser
from .validation import guard_validator, prepare_validator, schema_error_boundary

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from .utils.constants import JSONReturnType
    from .validation import Schema

BASELINE_VERSION = "0.64.9"
BASELINE_COMMIT = "36d7a6ed53e777b5a5b9017e33d35ea2af8b7c6e"
_PACKAGE = "_json_repair_upstream_v0649"
_lock = Lock()


def _load_engine() -> ModuleType:
    with _lock:
        return _load_cached_engine()


@lru_cache(maxsize=1)
def _load_cached_engine() -> ModuleType:
    filename = Path(__file__).with_name("server") / "_upstream_v0649.zip"
    spec = zipimporter(str(filename)).find_spec(_PACKAGE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Bundled upstream baseline is missing.")
    package = module_from_spec(spec)
    sys.modules[_PACKAGE] = package
    spec.loader.exec_module(package)
    engine: Any = import_module(f"{_PACKAGE}.json_repair")
    original_parser = engine.JSONParser
    original_repairer = engine.SchemaRepairer

    def budgeted_parser(*args: Any, **kwargs: Any) -> Any:
        parser = original_parser(*args, **kwargs)
        meter_parser(parser)
        return parser

    def offline_repairer(*args: Any, **kwargs: Any) -> Any:
        repairer = original_repairer(*args, **kwargs)
        original_root = repairer._get_root_validator

        def root_validator() -> Any:
            if repairer._root_validator is None:
                validator = original_root()
                repairer._root_validator = guard_validator(type(validator), validator.schema)
            return repairer._root_validator

        repairer._get_root_validator = root_validator
        return repairer

    # Reuse the release's repair decisions under the same parser budget and
    # offline resolver as the workbench.
    engine.JSONParser = budgeted_parser
    engine.SchemaRepairer = offline_repairer
    return cast("ModuleType", engine)


def baseline_repair(
    raw_text: str,
    *,
    schema: Schema | None = None,
    stream_stable: bool = False,
) -> JSONReturnType:
    validate_budget(raw_text)
    with work_budget():
        charge_work(len(raw_text))
        repair = cast("Callable[..., JSONReturnType]", _load_engine().repair_json)
        boundary = nullcontext() if schema is None else schema_error_boundary()
        if schema is not None:
            prepare_validator(schema)
        with boundary:
            return repair(raw_text, return_objects=True, stream_stable=stream_stable, schema=schema)
