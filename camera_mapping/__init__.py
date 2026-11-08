"""Camera-only perception and local obstacle mapping (advisory; never in the motor loop).

Pipeline: detections (existing COCO Faster R-CNN) -> per-object distance estimate
(ground plane and/or known object height, each with uncertainty, or UNKNOWN)
-> temporal tracking -> robot-relative local grid (OCCUPIED / FREE / UNKNOWN)
-> deterministic corridor assessment (CLEAR / CAUTION / BLOCKED / UNKNOWN)
-> advisory route suggestion -> optional guarded Qwen explanation.

Every distance this package produces is a camera ESTIMATE. It is never a
physical range-sensor measurement and is never labelled VERIFIED_DISTANCE.
"""

SCHEMA_PERCEPTION = "team15.camera_perception/1"
SOURCE_LABEL = "CAMERA_ESTIMATE"
