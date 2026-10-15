# Verification record

Checked on Windows, 15 October 2026, using Python 3.12 and Node.js 24.

## Software checks

- Automated suite: 38 tests passed after the follow-up review. Coverage includes low-speed EKF bias behavior/covariance, wrapped headings, range validity and transforms, independent evidence counts, conservative map export, deterministic reconstruction, reference constraints, authentication, recording/export/replay, controller ownership, disconnect/deadman stopping, stop latches, hardware inhibition, malformed requests/imports, Unicode profile persistence, and the paired robot telemetry/command exchange. This includes a host C++ test of the actual firmware arm guard; it skips on machines without a host compiler.
- Frontend: TypeScript checking and Vite production build passed.
- Firmware: PlatformIO build passed for the supplied ESP32-S3 N16R8 board profile. Reported application RAM use was 47,316 bytes and flash image use was 923,109 bytes. No firmware was flashed to a physical board.
- Browser: completed a synthetic irregular-object survey, producing 280 recorded frames, 278 accepted returns, and supported occupancy cells around the object.
- Browser: verified session-library loading, replay frame stepping/play/pause, selected playback speed, current-profile reconstruction, individual measurement selection, expanded map, and disabled drive controls during replay.
- Browser: checked layout at a 1536-pixel desktop viewport and in a 390-pixel-wide same-origin frame; no horizontal document overflow was observed. This is not a full mobile-device compatibility test.
- Export: native HTTP download and automated tests verified a ZIP with raw JSON, CSV, calibration, SVG, PNG, PGM, and YAML. Browser automation intercepted attachment fetches, so downloaded bundle contents were checked through native HTTP instead.
- Follow-up live-server checks: authenticated WebSocket velocity/stop commands succeeded. The revised simulator recorded 280 frames and 278 accepted returns, producing 513 supported boundary cells. Reference-assisted correction rebuilt the map and exported a validated ZIP; replay seek correctly reset and repopulated recorded sensor values. These are synthetic checks, not measurements of physical accuracy.
- Follow-up browser checks: the saved-profile calibration form rendered 31 numeric fields, and the dialog focus trap worked. Background-tab scheduling and the bridge's missing file-access permission limited asynchronous import/keyboard checks; see REVIEW.md for scope.

The backend test runner currently emits one dependency deprecation warning concerning Starlette's httpx-based TestClient. It does not fail the tests.

## Required physical acceptance checks

1. Identify each actual ToF chip and carrier circuit. Verify supply/interface voltage, exposed XSHUT, ESP32 carrier pinout, RGB pin, motor supply, driver limits, encoder voltage, battery protection, and physical motor disconnect.
2. With motor power isolated, flash with `HARDWARE_VERIFIED = false`. Confirm three addressed ToF sensors, the MPU6050, telemetry, command acknowledgements, RGB states, and safe reconnection.
3. Measure geometry and full-quadrature counts per wheel revolution. Verify every motor/encoder sign with the wheels raised. Save the measured profile.
4. Enable the verification gates only after the checks above. Tune the wheel-speed loop at low speed. Measure response to key release, Space, latched stop, lost browser focus, server/network interruption, physical stop, and sensor fault.
5. Run measured straight paths and clockwise/counterclockwise turns. Compare EKF and encoder-only trajectories. Check stationary bias before starting a survey.
6. Map a measured simple reference object, then an irregular one. Record surface/lighting/standoff conditions, boundary gaps, endpoint drift, repeatability, and errors against independent measurements.
7. Test reference-assisted graph correction only with a measured endpoint. Compare the entire boundary against ground truth; endpoint residual alone is insufficient.

No physical mapping accuracy, motor tuning, carrier compatibility, or stopping distance is claimed from software compilation and simulation alone.
