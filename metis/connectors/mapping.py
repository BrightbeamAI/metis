"""Turning records from workplace systems into observations of work.

A source mapping says where, in a record from a maintenance system, a production log, or a
ticketing tool, to find what the worker did, what the procedure expected, who the worker is,
and the situation. A record that passes the mapping's filter becomes one observation, whose id
is the source's own record id, so the same record is never captured twice.

Value specs in a mapping:

- ``$.work_order.action`` reads a field (``$['Action taken']`` for names with spaces, ``[0]``
  for list items);
- ``Work order {work_order.id}`` fills fields into text;
- anything else is a literal.

A filter (``when``) is a field, ``not`` a field, or a comparison: ``$.deviation == true``,
``$.status != closed``.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..integrations.chap.participants import URI_RE

_TOKEN = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]|\[['\"]([^'\"]+)['\"]\]")
_TEMPLATE = re.compile(r"\{([^{}]+)\}")
_PATH = r"\$(?:\.[^.\[\]\s=!]+|\[\d+\]|\[['\"][^'\"]+['\"]\])*"
_FILTER = re.compile(rf"^\s*(not\s+)?({_PATH})\s*(?:(==|!=)\s*(.+?))?\s*$")
_MISSING = object()


def get_path(record: Any, path: str) -> Any:
    """The value at ``path`` (``$.a.b[0]``), or ``None`` when any step is absent."""
    if not path.startswith("$"):
        raise ValueError(f"A field path starts with $: {path!r}")
    rest, value = path[1:], record
    position = 0
    while position < len(rest):
        match = _TOKEN.match(rest, position)
        if match is None:
            raise ValueError(f"Cannot read field path {path!r} at {rest[position:]!r}")
        name, index, quoted = match.groups()
        key: Any = int(index) if index is not None else (quoted if quoted is not None else name)
        if isinstance(key, int):
            value = value[key] if isinstance(value, list) and -len(value) <= key < len(value) else _MISSING
        else:
            value = value.get(key, _MISSING) if isinstance(value, Mapping) else _MISSING
        if value is _MISSING:
            return None
        position = match.end()
    return value


def resolve(spec: Any, record: Any) -> Any:
    """A field path, a template, or a literal, resolved against ``record``."""
    if not isinstance(spec, str):
        return spec
    if spec.startswith("$"):
        return get_path(record, spec)
    if _TEMPLATE.search(spec):
        def fill(match: re.Match) -> str:
            value = get_path(record, "$." + match.group(1).strip())
            return "" if value is None else str(value)
        return _TEMPLATE.sub(fill, spec)
    return spec


def passes(expression: str | None, record: Any) -> bool:
    """Whether ``record`` passes a mapping's filter."""
    if not expression:
        return True
    match = _FILTER.match(expression)
    if match is None:
        raise ValueError(f"Cannot read the filter {expression!r}")
    negate, path, operator, literal = match.groups()
    value = get_path(record, path)
    if operator is None:
        result = bool(value) and value not in ("false", "False", "0", "no")
    else:
        import yaml

        expected = yaml.safe_load(literal)
        equal = value == expected or (value is not None and str(value) == str(expected))
        result = equal if operator == "==" else not equal
    return not result if negate else result


@dataclass
class MappedObservation:
    """One observation, ready to submit for a worker."""

    observation_id: str
    worker: str
    work_as_done: str
    work_as_imagined: str | None = None
    title: str | None = None
    category: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def as_request(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id, "worker": self.worker,
                "work_as_done": self.work_as_done, "work_as_imagined": self.work_as_imagined,
                "title": self.title, "category": self.category, "context": self.context}


class SourceMapping(BaseModel):
    """How records from one source become observations."""

    model_config = ConfigDict(extra="forbid")

    name: str
    id: str = Field(description="The record's unique id in the source")
    worker: str = Field(description="The worker: a participant URI, an email, or an id in worker_map")
    work_as_done: str
    work_as_imagined: str | None = None
    title: str | None = None
    category: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    worker_map: dict[str, str] = Field(default_factory=dict)
    when: str | None = None
    records: str | None = Field(None, description="Where the list of records sits in a payload")

    def worker_uri(self, value: Any) -> str:
        """The worker's participant URI. People are named by email, compared without case, as
        sign-in names them."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("The record names no worker.")
        if text in self.worker_map:
            text = self.worker_map[text].strip()
        if text.lower().startswith("human:"):
            person = "human:" + text.split(":", 1)[1].lower()
            if URI_RE.match(person):
                return person
        elif ":" in text and URI_RE.match(text):
            return text
        if "@" in text and " " not in text:
            return f"human:{text.lower()}"
        raise ValueError(f"Unknown worker {text!r}: add it to worker_map, or map an email field.")

    def map(self, record: Mapping[str, Any]) -> MappedObservation | None:
        """The observation for ``record``, or ``None`` when the filter excludes it."""
        if not passes(self.when, record):
            return None
        source_id = resolve(self.id, record)
        if source_id in (None, ""):
            raise ValueError("The record has no id.")
        done = resolve(self.work_as_done, record)
        if not done:
            raise ValueError(f"Record {source_id} says nothing about what was done.")
        context = {}
        for key, spec in self.context.items():
            value = resolve(spec, record)
            if value not in (None, "", []):
                context[key] = [str(v) for v in value] if isinstance(value, list) else str(value)
        imagined, title, category = (resolve(s, record) for s in
                                     (self.work_as_imagined, self.title, self.category))
        return MappedObservation(
            observation_id=f"{self.name}:{source_id}",
            worker=self.worker_uri(resolve(self.worker, record)),
            work_as_done=str(done), work_as_imagined=str(imagined) if imagined else None,
            title=str(title) if title else None, category=str(category) if category else None,
            context=context)

    def records_in(self, payload: Any) -> list[Any]:
        """The records in a payload: a list of records as it is; in an object, the list at
        ``records``, or the object itself when the mapping names no ``records`` path."""
        if isinstance(payload, list):
            return payload
        found = get_path(payload, self.records) if self.records else payload
        if found is None:
            return []
        return list(found) if isinstance(found, list) else [found]


def load_mappings(path: str | Path) -> dict[str, SourceMapping]:
    """Source mappings from a YAML file with a top-level ``sources`` table."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or {}
    return {name: SourceMapping(name=name, **spec) for name, spec in sources.items()}


def read_payload(path: str | Path) -> Any:
    """A file's contents as a payload: a JSON document as it is, or a list of records from a
    JSON Lines or CSV file."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        body = path.read_text(encoding="utf-8-sig")
        return json.loads(body) if body.strip() else []
    return read_records(path)


def read_records(path: str | Path, *, text: str | None = None) -> list[dict[str, Any]]:
    """Records from a JSON, JSON Lines, or CSV file."""
    path = Path(path)
    body = text if text is not None else path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(body))]
    if suffix in (".jsonl", ".ndjson"):
        return [json.loads(line) for line in body.splitlines() if line.strip()]
    data = json.loads(body) if body.strip() else []
    return data if isinstance(data, list) else [data]


def map_records(mapping: SourceMapping, records: Iterable[Mapping[str, Any]]) -> tuple[
        list[MappedObservation], list[dict[str, Any]]]:
    """Mapped observations, and the records that could not be mapped, with the reason."""
    mapped, failed = [], []
    for position, record in enumerate(records):
        try:
            observation = mapping.map(record)
        except ValueError as exc:
            failed.append({"record": position, "error": str(exc)})
            continue
        if observation is not None:
            mapped.append(observation)
    return mapped, failed
