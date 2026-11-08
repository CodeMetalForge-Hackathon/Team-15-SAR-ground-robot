"""Optional monocular depth cross-check (Depth Anything V2, Hugging Face).

Two checkpoints were evaluated (both small, ~25 M parameters):
  depth-anything/Depth-Anything-V2-Small-hf               RELATIVE (affine-invariant
        inverse depth). Never converted to metres here; reported as ordering only.
  depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf METRIC (metres; trained on
        the synthetic Hypersim indoor set). Its metres are UNVALIDATED on our
        camera until the tape-measured calibration run compares them.

Per detection the cross-check takes the median depth of the lower-central part
of the box (where the object is, not the background beside it). The result is
a MethodResult "MONO_DEPTH"; distance.estimate() fuses it ONLY when
config.depth_model_validated is True. Otherwise it is displayed as a
cross-check and counted as consistent / inconsistent with the geometry.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np

from .detector import ObjectDetection
from .distance import ESTIMATED, UNKNOWN, MethodResult

METRIC_INDOOR = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
RELATIVE_SMALL = "depth-anything/Depth-Anything-V2-Small-hf"
UNVALIDATED_REL_SIGMA = 0.25     # placeholder spread until calibration measures it


class MonoDepth:
    def __init__(self, model_id: str = METRIC_INDOOR, device: Optional[str] = None,
                 input_width: int = 518) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        self.torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.proc = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModelForDepthEstimation.from_pretrained(model_id).to(self.device).eval()
        self.model_id = model_id
        self.metric = "Metric" in model_id
        self.last_ms: Optional[float] = None

    def depth_map(self, frame_bgr: np.ndarray) -> np.ndarray:
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        inp = self.proc(images=rgb, return_tensors="pt").to(self.device)
        t0 = time.perf_counter()
        with self.torch.no_grad():
            pred = self.model(**inp).predicted_depth
        pred = self.torch.nn.functional.interpolate(pred.unsqueeze(1), size=rgb.shape[:2],
                                                    mode="bicubic", align_corners=False)
        out = pred.squeeze().float().cpu().numpy()
        self.last_ms = (time.perf_counter() - t0) * 1000
        return out


def box_depths(dmap: np.ndarray, dets: List[ObjectDetection], metric: bool) -> Dict[int, MethodResult]:
    out = {}
    H, W = dmap.shape[:2]
    for i, d in enumerate(dets):
        x, y, w, h = d.bbox
        x0, x1 = int(max(0, x + 0.3 * w)), int(min(W, x + 0.7 * w))
        y0, y1 = int(max(0, y + 0.55 * h)), int(min(H, y + 0.9 * h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            out[i] = MethodResult("MONO_DEPTH", UNKNOWN, reason="BOX_TOO_SMALL")
            continue
        z = float(np.median(dmap[y0:y1, x0:x1]))
        if not metric:
            out[i] = MethodResult("MONO_DEPTH", UNKNOWN, reason=f"RELATIVE_DEPTH_ONLY (value {z:.3f}, no metres)")
        elif not (0.1 < z < 20.0):
            out[i] = MethodResult("MONO_DEPTH", UNKNOWN, reason="OUT_OF_RANGE")
        else:
            out[i] = MethodResult("MONO_DEPTH", ESTIMATED, z, z * UNVALIDATED_REL_SIGMA, None,
                                  reason="METRIC_UNVALIDATED")
    return out
