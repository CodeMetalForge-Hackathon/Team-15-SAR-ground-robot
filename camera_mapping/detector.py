"""Multi-class wrapper around the existing COCO Faster R-CNN (perception/detectors.py).

Same torchvision builders and cached weights as ``TorchPersonDetector``; the
only difference is that obstacle classes are kept instead of discarded. COCO
has NO "box"/"carton" class: boxes are not claimed. ``suitcase`` and
``backpack`` are the nearest supported containers and are reported under their
own names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

# COCO class names of interest -> category used by mapping
SUPPORTED_CLASSES: Dict[str, str] = {
    "person": "PERSON",
    "chair": "OBSTACLE", "couch": "OBSTACLE", "bench": "OBSTACLE",
    "dining table": "OBSTACLE", "bed": "OBSTACLE", "toilet": "OBSTACLE",
    "potted plant": "OBSTACLE", "suitcase": "OBSTACLE", "backpack": "OBSTACLE",
    "bicycle": "OBSTACLE", "motorcycle": "OBSTACLE", "refrigerator": "OBSTACLE",
    "tv": "OBSTACLE", "dog": "OBSTACLE", "cat": "OBSTACLE",
    "fire hydrant": "OBSTACLE", "handbag": "OBSTACLE", "bottle": "OBSTACLE",
}
UNSUPPORTED_REQUESTED = {"box": "COCO-pretrained Faster R-CNN has no box/carton class"}

# Classes that normally stand on the floor, so the bottom of the box can be a
# floor contact. Everything else (tv, bottle, handbag ...) may sit on furniture.
FLOOR_CLASSES = {"person", "chair", "couch", "bench", "dining table", "bed", "toilet",
                 "potted plant", "suitcase", "backpack", "bicycle", "motorcycle",
                 "refrigerator", "dog", "cat", "fire hydrant"}

DEFAULT_THRESH = {"person": 0.6}
DEFAULT_OBSTACLE_THRESH = 0.5


@dataclass
class ObjectDetection:
    label: str
    bbox: List[float]          # [x, y, w, h] full-frame pixels
    score: float
    score_kind: str = "frcnn_class_score"
    detector: str = ""

    @property
    def category(self) -> str:
        return SUPPORTED_CLASSES.get(self.label, "OTHER")

    def xyxy(self):
        x, y, w, h = self.bbox
        return x, y, x + w, y + h


class TorchObstacleDetector:
    """COCO Faster R-CNN keeping SUPPORTED_CLASSES. Weights come from the same
    torchvision cache as the existing person detector (~/.cache/torch)."""

    def __init__(self, model: str = "frcnn_r50_fpn_v2", device: Optional[str] = None,
                 thresholds: Optional[Dict[str, float]] = None,
                 obstacle_thresh: float = DEFAULT_OBSTACLE_THRESH) -> None:
        import torch
        from torchvision.models import detection as tvd

        from perception.detectors import DNN_MODELS

        builder, weights_enum = DNN_MODELS[model]
        weights = getattr(tvd, weights_enum).COCO_V1
        self.categories = list(weights.meta["categories"])
        self.torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        floor = min([obstacle_thresh, *(thresholds or DEFAULT_THRESH).values()])
        self.model = getattr(tvd, builder)(weights=weights, box_score_thresh=floor)
        self.model.eval().to(self.device)
        self.name = f"torchvision_{model}_coco"
        self.thresholds = dict(DEFAULT_THRESH, **(thresholds or {}))
        self.obstacle_thresh = obstacle_thresh

    def detect(self, frame_bgr: np.ndarray) -> List[ObjectDetection]:
        import cv2
        if frame_bgr is None or frame_bgr.size == 0:
            return []
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        t = self.torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0)
        with self.torch.no_grad():
            res = self.model([t.to(self.device)])[0]
        return self.filter(res["boxes"].cpu().numpy(), res["labels"].cpu().numpy(),
                           res["scores"].cpu().numpy())

    def filter(self, boxes, labels, scores) -> List[ObjectDetection]:
        out = []
        for (x1, y1, x2, y2), lab, s in zip(boxes, labels, scores):
            name = self.categories[int(lab)] if int(lab) < len(self.categories) else str(lab)
            if name not in SUPPORTED_CLASSES:
                continue
            if float(s) < self.thresholds.get(name, self.obstacle_thresh):
                continue
            out.append(ObjectDetection(name, [float(x1), float(y1), float(x2 - x1), float(y2 - y1)],
                                       float(s), detector=self.name))
        return out
