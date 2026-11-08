"""waypoint.py — the contract between the planner and any simulator."""
from __future__ import annotations
from abc import ABC, abstractmethod


class WaypointSink(ABC):
    @abstractmethod
    def go_to(self, cell):
        ...

    def cell_to_metres(self, cell, cell_m):
        i, j = cell
        return ((j + 0.5) * cell_m, (i + 0.5) * cell_m)


class Grid2DSink(WaypointSink):
    def __init__(self, start):
        self.pos = start

    def go_to(self, cell):
        self.pos = cell
        return self.pos
