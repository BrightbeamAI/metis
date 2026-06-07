"""In-memory FragmentStore with an optional persistence backend.

The store is the system of record for fragment *state*. Each promotion, rejection, or
revocation updates the fragment here and is independently appended to the CHAP evidence
chain, so the audit trail and the live state never drift apart silently.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..taxonomy.categories import AuthorityLayer, Category, ValidationState
from .model import TacitFragment


class FragmentBackend(Protocol):
    def save_fragment(self, fragment: TacitFragment) -> None: ...
    def load_fragments(self) -> Iterable[TacitFragment]: ...


class FragmentStore:
    def __init__(self, backend: FragmentBackend | None = None) -> None:
        self._fragments: dict[str, TacitFragment] = {}
        self._backend = backend
        if backend is not None:
            for frag in backend.load_fragments():
                self._fragments[frag.fragment_id] = frag

    def put(self, fragment: TacitFragment) -> None:
        self._fragments[fragment.fragment_id] = fragment
        if self._backend is not None:
            self._backend.save_fragment(fragment)

    def get(self, fragment_id: str) -> TacitFragment | None:
        return self._fragments.get(fragment_id)

    def require(self, fragment_id: str) -> TacitFragment:
        frag = self.get(fragment_id)
        if frag is None:
            raise KeyError(f"Unknown fragment: {fragment_id}")
        return frag

    def all(self) -> list[TacitFragment]:
        return list(self._fragments.values())

    def by_state(self, state: ValidationState) -> list[TacitFragment]:
        return [f for f in self._fragments.values() if f.validation_state == ValidationState(state)]

    def by_category(self, category: Category) -> list[TacitFragment]:
        return [f for f in self._fragments.values() if f.category == Category(category)]

    def by_authority(self, layer: AuthorityLayer) -> list[TacitFragment]:
        return [f for f in self._fragments.values() if f.authority_layer == AuthorityLayer(layer)]

    def __len__(self) -> int:
        return len(self._fragments)
