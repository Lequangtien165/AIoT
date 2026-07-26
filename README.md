# MediaPipe Face Detection

Desktop app that displays webcam video and draws a green rectangle around every detected face.

## Requirements

- Windows with an available webcam
- Python 3.12 recommended. Python 3.14 is also attempted by the setup below, but MediaPipe's published Python classifiers currently only guarantee support through Python 3.12.

## Setup

From Bash in this project directory:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Download the official MediaPipe short-range BlazeFace model:

```bash
mkdir -p models
curl -L --fail \
  --output models/blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite
```

## Run

```bash
python app.py
```

The default is camera index `0`. Use another camera with, for example:

```bash
python app.py --camera 1
```

Press `Q` or `Esc` to exit. If the camera cannot open, check Windows camera privacy settings and close any other app using the camera.

## Options

```text
--camera INDEX        Camera index, default: 0
--confidence VALUE    Detection confidence from 0 to 1, default: 0.5
```
