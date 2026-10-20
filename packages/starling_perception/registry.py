"""starling_perception/registry.py
-----------------------------------
The company's employee registry as a camera node sees it: for each
employee, an id, a display name and a small gallery of appearance
signatures enrolled from onboarding images (scripts/enroll_employees.py).

It is deployment data, distributed to every node once (like the node keys
and the floor plan) — not a service any node queries at runtime, so it
adds no coordinator. Verification is a pure function of the registry and
the signatures a node itself measured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

import numpy as np


@dataclass(frozen=True)
class Verification:
    employee_id: Optional[str]  # None = not verified
    name: Optional[str]
    score: float  # best employee's similarity
    second_score: float  # runner-up's similarity
    best_id: Optional[str]  # best match even when not verified (for the operator's view)

    @property
    def verified(self) -> bool:
        return self.employee_id is not None


@dataclass
class Employee:
    id: str
    name: str
    role: str
    gallery: np.ndarray  # (n_views, dim), unit rows


class EmployeeRegistry:
    def __init__(self, employees: list[Employee], meta: Optional[dict] = None) -> None:
        self.employees = employees
        self.meta = meta or {}

    @classmethod
    def load(cls, path: Union[str, Path]) -> "EmployeeRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        emps = [
            Employee(
                id=e["id"],
                name=e["name"],
                role=e.get("role", ""),
                gallery=np.asarray(e["gallery"], dtype=np.float32),
            )
            for e in data["employees"]
        ]
        return cls(emps, {k: v for k, v in data.items() if k != "employees"})

    def save(self, path: Union[str, Path]) -> None:
        data = {
            **self.meta,
            "employees": [
                {
                    "id": e.id,
                    "name": e.name,
                    "role": e.role,
                    "gallery": [[round(float(x), 5) for x in row] for row in e.gallery],
                }
                for e in self.employees
            ],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")

    def scores(self, descriptors: Sequence[np.ndarray]) -> list[tuple[str, float]]:
        """Per employee, the median over `descriptors` of the best cosine
        similarity to any of that employee's gallery views; sorted best first
        (ties by id, so the result never depends on registry order)."""
        if not descriptors or not self.employees:
            return []
        d = np.stack([np.asarray(x, dtype=np.float32) for x in descriptors])
        d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        out = []
        for e in self.employees:
            sims = d @ e.gallery.T  # (n_desc, n_views)
            out.append((e.id, float(np.median(sims.max(axis=1)))))
        return sorted(out, key=lambda kv: (-kv[1], kv[0]))

    def verify(
        self, descriptors: Sequence[np.ndarray], threshold: float, margin: float
    ) -> Verification:
        ranked = self.scores(descriptors)
        if not ranked:
            return Verification(None, None, 0.0, 0.0, None)
        best_id, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        ok = best >= threshold and (best - second) >= margin
        name = next(e.name for e in self.employees if e.id == best_id)
        return Verification(best_id if ok else None, name if ok else None, best, second, best_id)
