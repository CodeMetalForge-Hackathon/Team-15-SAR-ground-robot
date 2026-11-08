"""Small detectors and a shared drone/rover architecture for training/inference."""
from functools import partial
from pathlib import Path

ROBOT_CLASSES = ['background', 'drone', 'rover']
DATA_DIR = Path.home() / '.local/share/team15/vision-training'
MODEL_PATH = DATA_DIR / 'robots.pt'
VISIBLE_OBJECTS = {1: 'person', 77: 'phone'}


def robot_model(pretrained=False):
    import torch
    from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
    from torchvision.models.detection.ssdlite import SSDLiteClassificationHead
    model = ssdlite320_mobilenet_v3_large(
        weights=SSDLite320_MobileNet_V3_Large_Weights.DEFAULT if pretrained else None,
        weights_backbone=None)
    channels = [block[0][0].in_channels for block in model.head.classification_head.module_list]
    model.head.classification_head = SSDLiteClassificationHead(channels,
        model.anchor_generator.num_anchors_per_location(), len(ROBOT_CLASSES),
        partial(torch.nn.BatchNorm2d, eps=.001, momentum=.03))
    return model


class RuntimeDetector:
    def __init__(self, profile='fast'):
        import torch
        self.torch, self.robots, self.robot_stamp = torch, None, None
        self.active_robot_labels = {}
        torch.set_num_threads(4)
        if profile == 'accurate':
            from .detectors import TorchPersonDetector
            self.person = TorchPersonDetector()
            self.model, self.device = self.person.model, self.person.device
            self.model_name = self.person.name
        else:
            from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.model = ssdlite320_mobilenet_v3_large(weights=SSDLite320_MobileNet_V3_Large_Weights.DEFAULT).eval().to(self.device)
            self.model_name = 'ssdlite320_mobilenet_v3_large'
        self.profile = profile
        self.robot_status = 'Not trained · collect labeled drone and rover examples'

    def _load_robots(self):
        if not MODEL_PATH.exists():
            return
        stamp = MODEL_PATH.stat().st_mtime_ns
        if stamp == self.robot_stamp:
            return
        data = self.torch.load(MODEL_PATH, map_location='cpu', weights_only=True)
        if data.get('classes') != ROBOT_CLASSES or not data.get('validated'):
            raise ValueError('Robot checkpoint has not passed held-out validation')
        model = robot_model()
        model.load_state_dict(data['state_dict'])
        self.robots = model.eval().to(self.device)
        active = data.get('active_classes', ROBOT_CLASSES[1:])
        if not active or any(name not in ROBOT_CLASSES[1:] for name in active):
            raise ValueError('Invalid trained robot classes')
        self.active_robot_labels = {ROBOT_CLASSES.index(name): name for name in active}
        names = [{'drone': 'Crazyflie', 'rover': 'RoverC'}[name] for name in active]
        self.robot_stamp, self.robot_status = stamp, 'Trained · ' + ' / '.join(names)

    def detect(self, frame):
        import cv2
        self._load_robots()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tensor = self.torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255).to(self.device)
        detections = []
        with self.torch.inference_mode():
            self._append(self.model([tensor])[0], VISIBLE_OBJECTS, detections, self.model_name)
            if self.robots:
                self._append(self.robots([tensor])[0], self.active_robot_labels, detections)
        return detections

    @staticmethod
    def _append(result, labels, detections, detector='ssdlite320_mobilenet_v3_large'):
        for box, label, score in zip(result['boxes'].cpu().tolist(), result['labels'].cpu().tolist(), result['scores'].cpu().tolist()):
            if label not in labels or score < .6:
                continue
            x1, y1, x2, y2 = box
            name = labels[label]
            detections.append(dict(label=name, family={'person': 'PERSON_DETECTOR', 'phone': 'PHONE_DETECTOR'}.get(name, 'ROBOT_DETECTOR'),
                detector=detector, bbox=[round(x1), round(y1), round(x2-x1), round(y2-y1)],
                score=round(score, 4), score_kind='class_score'))
