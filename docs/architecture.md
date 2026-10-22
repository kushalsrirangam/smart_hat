# VisionCap architecture and safe refactoring roadmap

## Current system
Camera and ultrasonic inputs feed Python code under `smart hat code/working smart_hat/final_hat_code/`. A TensorFlow Lite model performs object recognition. Flask and SocketIO expose control and streaming; Firebase stores telemetry; Dash/Plotly visualizes results.

## Suggested target structure (not implemented)
```text
src/visioncap/
  hardware/       # Camera, GPIO, ultrasonic drivers
  inference/      # TensorFlow Lite model loading and prediction
  detection/      # Filtering, risk and alert decision logic
  api/            # Flask routes and SocketIO
  telemetry/      # Firebase/logging adapters
  speech/         # Voice alert integration
web/              # Existing browser assets
tests/            # Unit tests with hardware mocks
config/           # Example non-secret configuration
```

## Migration sequence
1. Establish repeatable hardware smoke tests on the Raspberry Pi and record a working revision.
2. Move hardcoded paths and credentials to environment/configuration values; rotate any credentials that may have been committed.
3. Extract camera, GPIO, and Firebase interfaces behind adapters, then introduce mocks.
4. Isolate TFLite inference and decision logic; add deterministic tests using synthetic detections.
5. Refactor Flask routes and browser resources incrementally while checking video, alerts, and dashboards on hardware.
6. Add dependency lockfiles, linting and CI for code that does not require Raspberry Pi hardware.

**Do not rename or move the running entry point until hardware tests succeed.** This project is edge computer vision, not agentic AI.
