"""Person / face detectors for the bench camera, each result labeled by family.

Families are kept separate on purpose so a face hit is never reported as a
person-detector hit:

  PERSON_DETECTOR  torchvision Faster R-CNN, COCO-pretrained, class "person"
  FULL_BODY_HOG    OpenCV HOG + linear SVM default people detector
  UPPER_BODY_HAAR  OpenCV Haar upper-body cascade
  FACE_ONLY        OpenCV Haar frontal-face cascade (sees a face, not a body)

None of these scores is a calibrated probability. Scores are reported with
their kind so downstream code does not treat them as confidence.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence

import cv2
import numpy as np

PERSON_DETECTOR = "PERSON_DETECTOR"
FULL_BODY_HOG = "FULL_BODY_HOG"
UPPER_BODY_HAAR = "UPPER_BODY_HAAR"
FACE_ONLY = "FACE_ONLY"
FAMILIES = (PERSON_DETECTOR, FULL_BODY_HOG, UPPER_BODY_HAAR, FACE_ONLY)

# torchvision model name -> (builder attr, weights enum attr)
DNN_MODELS = {
    "frcnn_r50_fpn_v2": ("fasterrcnn_resnet50_fpn_v2",
                         "FasterRCNN_ResNet50_FPN_V2_Weights"),
    "frcnn_mbv3_fpn": ("fasterrcnn_mobilenet_v3_large_fpn",
                       "FasterRCNN_MobileNet_V3_Large_FPN_Weights"),
}
DEFAULT_DNN_MODEL = "frcnn_r50_fpn_v2"
COCO_PERSON_LABEL = 1


@dataclass
class Detection:
    bbox: List[int]  # [x, y, w, h] in full-frame pixels
    detector: str
    score: Optional[float]
    score_kind: Optional[str]
    family: str = FACE_ONLY

    def to_json(self) -> dict:
        return {"detector": self.detector, "family": self.family,
                "bbox": [int(v) for v in self.bbox],
                "score": None if self.score is None else round(float(self.score), 4),
                "score_kind": self.score_kind}


def _cascade(name: str) -> cv2.CascadeClassifier:
    path = os.path.join(cv2.data.haarcascades, name)
    c = cv2.CascadeClassifier(path)
    if c.empty():
        raise RuntimeError(f"failed to load Haar cascade {path}")
    return c


class OpenCVDetectors:
    """The original bundled OpenCV detectors; every one runs, none short-circuits."""

    def __init__(self, families: Sequence[str] = (FULL_BODY_HOG, UPPER_BODY_HAAR,
                                                  FACE_ONLY)) -> None:
        self.families = set(families)
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.face = _cascade("haarcascade_frontalface_default.xml")
        self.upper = _cascade("haarcascade_upperbody.xml")

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        scale = 640.0 / w if w > 640 else 1.0
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale != 1.0 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        gray = cv2.equalizeHist(gray)

        def unscale(r: Sequence[int]) -> List[int]:
            return [int(round(v / scale)) for v in r]

        out: List[Detection] = []
        if FULL_BODY_HOG in self.families:
            rects, weights = self.hog.detectMultiScale(
                small, winStride=(8, 8), padding=(8, 8), scale=1.05)
            weights = np.asarray(weights).reshape(-1)
            for r, s in zip(rects, weights):
                out.append(Detection(unscale(r), "opencv_hog_default_people",
                                     float(s), "hog_svm_margin", FULL_BODY_HOG))
        for fam, name, casc, min_size in (
            (FACE_ONLY, "opencv_haar_frontalface_default", self.face, (60, 60)),
            (UPPER_BODY_HAAR, "opencv_haar_upperbody", self.upper, (80, 80)),
        ):
            if fam not in self.families:
                continue
            rects, _levels, lw = casc.detectMultiScale3(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=min_size,
                outputRejectLevels=True)
            lw = np.asarray(lw).reshape(-1)
            for i, r in enumerate(rects):
                s = float(lw[i]) if lw.size == len(rects) else None
                out.append(Detection(unscale(r), name, s,
                                     "haar_level_weight" if s is not None else None, fam))
        return out


class TorchPersonDetector:
    """COCO-pretrained torchvision Faster R-CNN, keeping only class 'person'.

    Weights are fetched once by torchvision into ~/.cache/torch (outside Git).
    """

    def __init__(self, model: str = DEFAULT_DNN_MODEL, score_thresh: float = 0.6,
                 device: Optional[str] = None) -> None:
        import torch
        from torchvision.models import detection as tvd

        if model not in DNN_MODELS:
            raise ValueError(f"unknown model {model!r}; choose from {sorted(DNN_MODELS)}")
        builder, weights_enum = DNN_MODELS[model]
        weights = getattr(tvd, weights_enum).COCO_V1
        self.torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = getattr(tvd, builder)(weights=weights,
                                           box_score_thresh=score_thresh)
        self.model.eval().to(self.device)
        self.name = f"torchvision_{model}_coco"
        self.score_thresh = score_thresh

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        t = self.torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0)
        with self.torch.no_grad():
            res = self.model([t.to(self.device)])[0]
        boxes = res["boxes"].cpu().numpy()
        labels = res["labels"].cpu().numpy()
        scores = res["scores"].cpu().numpy()
        out = []
        for (x1, y1, x2, y2), lab, s in zip(boxes, labels, scores):
            if int(lab) != COCO_PERSON_LABEL or float(s) < self.score_thresh:
                continue
            out.append(Detection([int(x1), int(y1), int(x2 - x1), int(y2 - y1)],
                                 self.name, float(s), "frcnn_class_score",
                                 PERSON_DETECTOR))
        return out


def best(dets: Sequence[Detection], family: Optional[str] = None) -> Optional[Detection]:
    pool = [d for d in dets if family is None or d.family == family]
    if not pool:
        return None
    return max(pool, key=lambda d: (d.score if d.score is not None else float("-inf")))
