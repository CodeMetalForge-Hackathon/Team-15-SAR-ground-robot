"""Bounded JSON-lines camera inference protocol, isolated from robot control."""
import base64
import json
import sys
import time
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['fast', 'accurate'], default='fast')
    args = parser.parse_args()
    try:
        import cv2
        import numpy as np
        from perception.robots import RuntimeDetector
        detector = RuntimeDetector(args.profile)
    except Exception as exc:
        print(json.dumps({'error': 'Detector unavailable: ' + str(exc)[:180] +
                          '. Install mission_control/vision-requirements.txt in the runtime Python.'}), flush=True)
        return
    print(json.dumps({'ready': True}), flush=True)
    while True:
        raw = sys.stdin.buffer.readline(3 * 1024 * 1024)
        if not raw:
            return
        try:
            started = time.perf_counter()
            frame = cv2.imdecode(np.frombuffer(base64.b64decode(raw.strip(), validate=True), np.uint8), cv2.IMREAD_COLOR)
            if frame is None or frame.size > 1920 * 1080 * 3:
                raise ValueError('Expected a JPEG no larger than 1920 × 1080')
            detections = detector.detect(frame)
            for detection in detections:
                x, y, w, h = detection['bbox']
                cv2.rectangle(frame, (x, y), (x+w, y+h), (22, 79, 224), 2)
                cv2.putText(frame, detection['label'].upper(), (x, max(22, y-8)), cv2.FONT_HERSHEY_SIMPLEX,
                            .65, (22, 79, 224), 2)
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise ValueError('Could not encode detection frame')
            elapsed = time.perf_counter() - started
            print(json.dumps(dict(detections=detections, profile=args.profile, robot_model=detector.robot_status,
                                  frame_size=[frame.shape[1], frame.shape[0]], inference_ms=round(elapsed*1000),
                                  jpeg=base64.b64encode(jpeg).decode())), flush=True)
        except Exception as exc:
            print(json.dumps({'error': str(exc)[:200]}), flush=True)


if __name__ == '__main__':
    main()
