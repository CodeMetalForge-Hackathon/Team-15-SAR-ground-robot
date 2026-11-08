"""Labeled robot storage, session separation and honest activation criteria."""
import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from mission_control.training import Training
from perception.train import split_sessions


class RobotTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.training = Training(directory=self.temporary.name)
        from PIL import Image
        out = BytesIO()
        Image.new('RGB', (100, 80), 'gray').save(out, format='JPEG')
        self.sample = dict(session='test-session-01', jpeg=base64.b64encode(out.getvalue()).decode(),
                           boxes=[dict(label='drone', bbox=[.1, .2, .3, .4])])

    def test_explicit_sample_preserves_jpeg_and_specific_robot_label(self):
        result = self.training.save(self.sample)
        self.assertEqual(result['counts'], {'drone': 1, 'rover': 0})
        self.assertFalse(result['trained'])
        self.assertFalse(result['ready'])
        files = list((Path(self.temporary.name)/'samples').glob('*.json'))
        row = json.loads(files[0].read_text())
        self.assertEqual(row['boxes'], self.sample['boxes'])
        image = files[0].with_suffix('.jpg')
        self.assertEqual(image.read_bytes(), base64.b64decode(self.sample['jpeg']))
        self.assertEqual(image.stat().st_mode & 0o077, 0)

    def test_invalid_or_out_of_frame_boxes_do_not_save_anything(self):
        for box in (dict(label='car', bbox=[0, 0, .2, .2]), dict(label='drone', bbox=[.9, .1, .2, .2]),
                    dict(label='rover', bbox=[0, 0, float('nan'), .2]), 15):
            with self.assertRaises(ValueError):
                self.training.save(dict(self.sample, boxes=[box]))
        self.assertEqual(self.training.snapshot()['total'], 0)

    def test_empty_scene_requires_explicit_background_label(self):
        with self.assertRaises(ValueError):
            self.training.save(dict(self.sample, boxes=[]))
        result = self.training.save(dict(self.sample, boxes=[], background=True))
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['counts'], {'drone': 0, 'rover': 0})

    def test_training_is_not_started_without_both_robots_and_independent_sessions(self):
        with self.assertRaises(ValueError):
            self.training.start()
        self.assertIsNone(self.training.process)

    def test_split_keeps_capture_sessions_out_of_both_partitions(self):
        rows = [dict(session=session, boxes=[{'label': label}]) for session in ('day-a', 'day-b', 'day-c') for label in ('drone', 'rover')]
        train, validation = split_sessions(rows)
        self.assertFalse({r['session'] for r in train} & {r['session'] for r in validation})
        for part in (train, validation):
            self.assertEqual({b['label'] for r in part for b in r['boxes']}, {'drone', 'rover'})

    def test_one_capture_session_cannot_be_reported_as_validation(self):
        with self.assertRaises(ValueError):
            split_sessions([dict(session='same', boxes=[{'label': 'drone'}, {'label': 'rover'}])])


class VisibleObjectTests(unittest.TestCase):
    def test_cellphone_class_and_robot_classes_are_not_confused(self):
        import torch
        from torchvision.models.detection import SSDLite320_MobileNet_V3_Large_Weights
        from perception.robots import RuntimeDetector, VISIBLE_OBJECTS
        self.assertEqual(SSDLite320_MobileNet_V3_Large_Weights.DEFAULT.meta['categories'][77], 'cell phone')
        result = dict(boxes=torch.tensor([[10, 20, 30, 40], [0, 0, 5, 5], [1, 1, 10, 10]], dtype=torch.float32),
                      labels=torch.tensor([77, 1, 3]), scores=torch.tensor([.92, .8, .95]))
        detections = []
        RuntimeDetector._append(result, VISIBLE_OBJECTS, detections)
        self.assertEqual([d['label'] for d in detections], ['phone', 'person'])
        self.assertEqual(detections[0]['family'], 'PHONE_DETECTOR')
        self.assertEqual(detections[0]['bbox'], [10, 20, 20, 20])

    def test_custom_robot_class_ids_keep_their_separate_names(self):
        import torch
        from perception.robots import RuntimeDetector
        result = dict(boxes=torch.tensor([[1, 2, 10, 20], [4, 5, 12, 16]], dtype=torch.float32),
                      labels=torch.tensor([1, 2]), scores=torch.tensor([.95, .9]))
        detections = []
        RuntimeDetector._append(result, {1: 'drone', 2: 'rover'}, detections)
        self.assertEqual([d['label'] for d in detections], ['drone', 'rover'])
        self.assertTrue(all(d['family'] == 'ROBOT_DETECTOR' for d in detections))
