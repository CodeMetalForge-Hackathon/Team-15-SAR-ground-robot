"""Fine-tune Crazyflie/RoverC SSDLite; evaluate a separate capture session."""
import argparse
from collections import Counter
import json
from pathlib import Path
import random

from .robots import DATA_DIR, ROBOT_CLASSES


def split_sessions(records, seed=15, labels=('drone', 'rover')):
    sessions = sorted({row['session'] for row in records})
    if len(sessions) < 2:
        raise ValueError('Capture a second session for held-out validation')
    rng = random.Random(seed)
    best, best_error = None, float('inf')
    for _ in range(100):
        rng.shuffle(sessions)
        held = set(sessions[:max(1, round(len(sessions)*.2))])
        train = [row for row in records if row['session'] not in held]
        val = [row for row in records if row['session'] in held]
        if all(any(any(b['label'] == label for b in row['boxes']) for row in part) for part in (train, val) for label in labels):
            error = abs(len(val)-len(records)*.2)
            if error < best_error:
                best, best_error = (train, val), error
    if best:
        return best
    raise ValueError('Each selected robot must appear in training and held-out capture sessions')


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def evaluate(model, dataset, device, active_classes=('drone', 'rover')):
    import torch
    from torchvision.ops import box_iou
    counts = {name: Counter() for name in active_classes}
    model.eval()
    with torch.inference_mode():
        for image, target in dataset:
            result = model([image.to(device)])[0]
            for label, name in enumerate(ROBOT_CLASSES[1:], 1):
                if name not in active_classes:
                    continue
                truth = target['boxes'][target['labels'] == label]
                pred = result['boxes'][(result['labels'] == label) & (result['scores'] >= .6)].cpu()
                scores = result['scores'][(result['labels'] == label) & (result['scores'] >= .6)].cpu()
                matched = set()
                for box in pred[scores.argsort(descending=True)]:
                    overlaps = box_iou(box.unsqueeze(0), truth).flatten() if len(truth) else []
                    available = [(float(v), i) for i, v in enumerate(overlaps) if i not in matched]
                    overlap, i = max(available, default=(0, -1))
                    if overlap >= .5:
                        matched.add(i)
                        counts[name]['tp'] += 1
                    else:
                        counts[name]['fp'] += 1
                counts[name]['fn'] += len(truth)-len(matched)
                counts[name]['examples'] += len(truth)
    return {name: dict(values, precision=values['tp']/max(1, values['tp']+values['fp']),
        recall=values['tp']/max(1, values['tp']+values['fn'])) for name, values in counts.items()}


def run(args):
    import torch
    from PIL import Image
    from torchvision.transforms import ColorJitter
    from torchvision.transforms.functional import to_tensor, hflip
    from .robots import robot_model
    torch.manual_seed(15)
    random.seed(15)
    torch.set_num_threads(4)
    root = Path(args.dataset)
    records = [json.loads(path.read_text()) for path in sorted((root/'samples').glob('*.json'))]
    train_rows, val_rows = split_sessions(records, labels=args.classes)
    write_json(root/'candidate-training.json', dict(classes=args.classes,
        training_sessions=sorted({row['session'] for row in train_rows}),
        training_ids=[row['id'] for row in train_rows]))

    class Samples(torch.utils.data.Dataset):
        def __init__(self, rows, augment=False):
            self.rows, self.augment = rows, augment
            self.jitter = ColorJitter(brightness=.2, contrast=.2, saturation=.15, hue=.03)

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            row = self.rows[index]
            image = Image.open(root/'samples'/row['image']).convert('RGB')
            width, height = image.size
            boxes, labels = [], []
            for box in row['boxes']:
                if box['label'] not in args.classes:
                    continue
                x, y, w, h = box['bbox']
                boxes.append([x*width, y*height, (x+w)*width, (y+h)*height])
                labels.append(ROBOT_CLASSES.index(box['label']))
            bounds = torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4)
            if self.augment:
                image = self.jitter(image)
                if random.random() < .5:
                    image = hflip(image)
                    bounds[:, [0, 2]] = width - bounds[:, [2, 0]]
            return to_tensor(image), dict(boxes=bounds, labels=torch.tensor(labels, dtype=torch.int64))

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = robot_model(pretrained=True).to(device)
    loader = torch.utils.data.DataLoader(Samples(train_rows, augment=True), batch_size=2, shuffle=True,
                                        collate_fn=lambda batch: tuple(zip(*batch)))
    optimizer = torch.optim.SGD(model.parameters(), lr=.002, momentum=.9, weight_decay=.0005)
    for epoch in range(args.epochs):
        model.train()
        # A final batch of one must not update 1×1-feature BatchNorm statistics.
        for module in model.modules():
            if isinstance(module, torch.nn.BatchNorm2d):
                module.eval()
        losses = []
        for images, targets in loader:
            loss = sum(model([image.to(device) for image in images],
                             [{k: v.to(device) for k, v in target.items()} for target in targets]).values())
            if not torch.isfinite(loss):
                raise ValueError('Non-finite training loss; check image labels')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10)
            optimizer.step()
            losses.append(float(loss.detach()))
        write_json(root/'progress.json', dict(status='Training', epoch=epoch+1, epochs=args.epochs,
                   loss=sum(losses)/max(1, len(losses)), train_images=len(train_rows), validation_images=len(val_rows)))
    metrics = evaluate(model, Samples(val_rows), device, args.classes)
    passed = all(row['examples'] >= 5 and row['precision'] >= .8 and row['recall'] >= .8 for row in metrics.values())
    checkpoint = dict(state_dict={k: v.cpu() for k, v in model.state_dict().items()},
                      classes=ROBOT_CLASSES, active_classes=args.classes, validated=passed,
                      training_sessions=sorted({row['session'] for row in train_rows}),
                      hardware=[{'drone': 'Crazyflie', 'rover': 'RoverC'}[name] for name in args.classes], metrics=metrics)
    temporary = root/'robots.candidate.tmp'
    torch.save(checkpoint, temporary)
    temporary.replace(root/'robots.candidate.pt')
    if passed and args.activate:
        temporary = root/'robots.tmp'
        torch.save(checkpoint, temporary)
        temporary.replace(root/'robots.pt')
    report = dict(status='Trained and validated' if passed else 'Needs more varied examples',
                  metrics=metrics, active_classes=args.classes, activated=passed and args.activate,
                  train_images=len(train_rows), validation_images=len(val_rows))
    write_json(root/'progress.json', report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default=str(DATA_DIR))
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--classes', nargs='+', choices=['drone', 'rover'], default=['drone', 'rover'])
    args = parser.parse_args()
    if not 1 <= args.epochs <= 200:
        parser.error('epochs must be 1–200')
    try:
        run(args)
    except Exception as exc:
        root = Path(args.dataset)
        root.mkdir(parents=True, exist_ok=True)
        write_json(root/'progress.json', dict(status='Training failed', error=str(exc)[:240]))
        raise


if __name__ == '__main__':
    main()
