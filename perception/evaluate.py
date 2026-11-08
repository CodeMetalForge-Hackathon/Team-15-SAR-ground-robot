"""Check a saved candidate on new capture sessions without retraining it."""
import argparse
import json
from pathlib import Path

from .robots import DATA_DIR, ROBOT_CLASSES, robot_model
from .train import evaluate, write_json


def run(directory, activate=False):
    import torch
    from PIL import Image
    from torchvision.transforms.functional import to_tensor
    torch.set_num_threads(4)
    root = Path(directory)
    checkpoint = torch.load(root/'robots.candidate.pt', map_location='cpu', weights_only=True)
    classes = checkpoint['active_classes']
    training_sessions = checkpoint.get('training_sessions')
    if training_sessions is None:
        training_sessions = json.loads((root/'candidate-training.json').read_text())['training_sessions']
    rows = [json.loads(path.read_text()) for path in sorted((root/'samples').glob('*.json'))]
    rows = [row for row in rows if row['session'] not in training_sessions]
    if not rows:
        raise ValueError('No independent capture session is available for validation')

    class Samples:
        def __len__(self):
            return len(rows)

        def __getitem__(self, index):
            row = rows[index]
            image = Image.open(root/'samples'/row['image']).convert('RGB')
            width, height = image.size
            boxes, labels = [], []
            for box in row['boxes']:
                if box['label'] not in classes:
                    continue
                x, y, w, h = box['bbox']
                boxes.append([x*width, y*height, (x+w)*width, (y+h)*height])
                labels.append(ROBOT_CLASSES.index(box['label']))
            return to_tensor(image), dict(boxes=torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
                                          labels=torch.tensor(labels, dtype=torch.int64))

    model = robot_model()
    model.load_state_dict(checkpoint['state_dict'])
    metrics = evaluate(model, Samples(), 'cpu', classes)
    passed = all(m['examples'] >= 5 and m['precision'] >= .8 and m['recall'] >= .8 for m in metrics.values())
    checkpoint.update(validated=passed, metrics=metrics, training_sessions=training_sessions)
    if passed and activate:
        temporary = root/'robots.tmp'
        torch.save(checkpoint, temporary)
        temporary.replace(root/'robots.pt')
    report = dict(status='Trained and validated' if passed else 'Needs more varied examples',
                  metrics=metrics, active_classes=classes, activated=passed and activate,
                  validation_images=len(rows), training_sessions=training_sessions)
    write_json(root/'progress.json', report)
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default=str(DATA_DIR))
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    run(args.dataset, args.activate)
