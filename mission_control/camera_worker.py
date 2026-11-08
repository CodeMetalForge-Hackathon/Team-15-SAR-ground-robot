"""Optional host webcam MJPEG producer. Started only by an explicit view action."""
import sys
import time


def main():
    import cv2
    camera = cv2.VideoCapture(0)
    for _ in range(4):
        if camera.isOpened():
            break
        camera.release()
        time.sleep(.5)
        camera = cv2.VideoCapture(0)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    camera.set(cv2.CAP_PROP_FPS, 30)
    try:
        if not camera.isOpened():
            return
        while True:
            started = time.monotonic()
            ok, frame = camera.read()
            if not ok:
                return
            height, width = frame.shape[:2]
            frame = cv2.resize(frame, (960, round(height * 960 / width)))
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                sys.stdout.buffer.write(jpeg.tobytes())
                sys.stdout.buffer.flush()
            time.sleep(max(0, 1/30 - (time.monotonic()-started)))
    except BrokenPipeError:
        pass
    finally:
        camera.release()


if __name__ == '__main__':
    main()
