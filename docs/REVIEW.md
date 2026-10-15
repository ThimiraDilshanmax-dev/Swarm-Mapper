# Follow-up bug review

The review reproduced failures with focused regression tests before fixing the affected behavior.

## Corrections

| Area | Problem | Correction |
| --- | --- | --- |
| EKF | Gaps between low-speed encoder ticks could be learned as gyro bias, suppressing a real slow turn. | Require sustained stillness and use non-overlapping wheel/gyro rate windows. |
| Acquisition pose | A range just before the first pose sample could use the latest pose. | Use the earliest pose within the allowed tolerance. |
| Occupancy evidence | Several sampled rays from one scalar return could increase one cell's hit count repeatedly. | Apply one contribution per return/cell, with independent boundary-support counts. |
| PNG export | Weak, uncertain observations could be shown as free while PGM retained unknown space. | Preserve uncertainty consistently in PNG and PGM. |
| Control | Optimization could begin while drive remained armed. | Disarm before starting the solver and retain disarmed state on failure. |
| Watchdog | Refreshing an armed command after a local timeout could restart motion. | Protocol 2 arm tokens require a fresh explicit arm action; the server also respects acknowledged robot-side disarming. |
| Reconnection | A server restart could leave its sequence numbers behind the powered robot's previous connection. | Reset firmware command-sequence context on reconnect. |
| Sensor health | A responding I2C device could stop delivering fresh measurements. | Detect stale ToF measurement cycles and inhibit motors. |
| VL53L0X validity | An in-range numerical distance could be accepted despite device-status errors. | Check device range status before accepting a return. Full ST software sigma estimation remains outside this driver. |
| Finished recordings | Later movement and telemetry gaps could change the displayed finished distance/gap count. | Keep acquisition summary counters tied to the recorded trajectory. |
| Replay | Sensor values could reflect live or last-integrated readings rather than the selected recorded time. | Rebuild and advance a separate recorded sensor timeline. |
| Calibration | Opening calibration from replay could use the recording's profile as the editable robot profile. | Supply the current saved profile independently in state updates. |
| Imports/API | Badly shaped profile imports or malformed request bodies could crash a view or produce an internal server error. | Validate profile imports and request objects before applying them. |
| State transitions | An invalid source selection could partially change source state. | Validate before mutating state; detach old robot ownership before closing its socket. |
| Notes | A saved replay note could remain stale in state updates. | Update the active recording metadata after saving. |
| Windows text | Loading a UTF-8 profile with the Windows default encoding could corrupt its name. | Read profiles explicitly as UTF-8 and test a Unicode save/restart. |
| Interface | Driving keys could remain active around dialogs; narrow navigation lost accessible names. | Gate movement to the active driving workspace, clear stale keys, trap dialog focus, and label icon navigation. |
| Clock continuity | A non-increasing acquisition timestamp could be silently ignored. | Stop motion, pause mapping, and require a new coordinate segment. |

## Validation scope

The automated suite includes mathematical, map/export, API, recording/replay, control, and robot-protocol checks. An optional host C++ test compiles and runs the actual firmware arm guard when `g++` is available. The ESP32 firmware is also compiled with its pinned PlatformIO toolchain.

Live local-server checks exercise authenticated WebSocket velocity/stop commands, a complete synthetic survey, graph correction/reprojection, replay sensor timing, and a research-bundle export. The browser review checked the calibration form and dialog focus trap. Broader browser checks from the initial implementation are listed separately in VERIFICATION.md.

The browser bridge ran against a background Chrome tab with delayed asynchronous work; its file-upload helper also lacked the extension's file-access permission. No extension permissions were changed. Generated input fixtures and backend validation cover malformed imports without reading user files; physical keyboard focus and real-device control still need the acceptance checks below.

No physical robot was available. Verify motor stopping/rearming, sensor faults, encoder calibration, ToF quality, and mapping accuracy on the actual chassis before field use. The new backend and protocol 2 firmware should be used together.
