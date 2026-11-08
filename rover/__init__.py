"""RoverC-Pro ground-robot navigation: safety supervisor, simulator, hardware adapter, navigator.

Status (see docs/rover/SAFETY_AND_LIMITATIONS.md):
- Simulation: implemented and tested (Gates 2-4).
- Hardware: the adapter refuses to send anything until the wiring, wheel mapping,
  power and link are independently verified (Gate 5 is not passed).
- Distances come from the SYNTHETIC trail graph. They are not measured RoverC travel.
"""
