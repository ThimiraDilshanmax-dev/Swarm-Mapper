# Contour

A local robotics research console for manually driving one master robot and building a real-time 2D object map from wheel encoders, an MPU6050, and three fixed Time-of-Flight sensors.

The application includes a working sensor simulator, a four-state Extended Kalman Filter, occupancy mapping, measurement inspection, SQLite recording, deterministic reconstruction, replay, exports, and reference-assisted pose graph optimization.

## Start on Windows

Double-click **start.cmd** in this folder. It creates a local Python environment if needed, installs missing dependencies, builds the interface when needed, and opens:

**http://127.0.0.1:8000**

Requirements for a fresh installation:

- Python 3.11 or newer.
- Node.js 20.19+ or a current LTS release, including npm.
- Internet access for the first dependency installation. Operation is local after installation.

The implementation was built and checked with Python 3.12 and Node.js 24 on Windows.

From PowerShell:

~~~powershell
.\start.cmd
~~~

For physical robot connections, enable LAN listening:

~~~powershell
.\start.cmd -Lan
~~~

Additional options:

~~~powershell
.\start.cmd -NoBrowser
.\start.cmd -Rebuild
.\start.cmd -Lan -Port 8001
~~~

Keep the server terminal open. Ctrl+C stops the server. If a port is already occupied, stop the existing instance or choose another port.

## Try a complete mapping experiment

1. Open the Live workspace. The initial source is clearly labelled **Simulation**.
2. Click **Run sample survey**.
3. The simulated robot circles an irregular object at accelerated simulation time. Its wheel counts, gyro rate, and ToF observations enter the same estimation/mapping code used for hardware.
4. Inspect the growing occupied evidence, purple supported boundary, EKF path, and sensor footprints. The beige dashed object is explicitly labelled simulation reference and can be hidden under Layers.
5. The sample survey finishes and saves automatically. Finish manually if you want a shorter recording.
6. Open **Session library**, then **Open replay**.
7. Use playback, the frame slider, or previous/next-frame controls. Select returns on the map to inspect individual observations.
8. Use **Export survey** to download the research bundle.

The simulator is synthetic. Reference geometry and the simulated true pose are not used as localization inputs. The backend receives generated encoder counts, gyro measurements, and noisy range measurements.

For manual simulation: Start mapping, then Arm drive. Hold arrow keys/WASD or an on-screen direction button. Release to request zero speed. Space stops and disarms.

## What is implemented

| Capability | Implementation |
| --- | --- |
| One-master architecture | Only the master supplies mapping data; computation runs on the computer |
| Manual control | Keyboard and pointer controls, speed limits, single controller ownership |
| Kalman filtering | Four-state EKF: X, Y, heading, and gyroscope bias |
| Occupancy mapping | Finite-angle ToF return bands and conservative free-space evidence |
| Object boundary | Supported occupied cells with gaps retained |
| Live inspection | Sensor identity, acquisition time, pose, footprint, validity, changed cells |
| Recording | Original telemetry, calibration, events, notes, and result metadata in SQLite |
| Replay | Reconstruct from raw samples; single-step frames or play the sequence |
| Comparison | Encoder-only, EKF, and reference-corrected trajectories |
| Optimization | SE(2) keyframe pose graph with a documented surveyed endpoint |
| Exports | JSON, CSV, SVG, PNG, PGM, map YAML, and a ZIP research bundle |
| Firmware | ESP32-S3 N16R8 profile; both VL53L0X and VL53L1X drivers compiled in |

## Physical hardware

The firmware is buildable, but physical wiring, motor behaviour, sensor calibration, and mapping accuracy require validation on your robot. No physical robot was available during software verification.

Use:

- ESP32-S3 N16R8 development board.
- Two N20 motors with quadrature encoders.
- MX1508 motor driver, provided its electrical/current ratings suit your actual motors.
- Three VL53L0X or VL53L1X breakout boards with exposed XSHUT.
- MPU6050 breakout.
- Appropriate motor supply and regulated electronics supplies.
- A physical motor-power disconnect, suitable fusing, secure connectors, and rigid sensor mounts.

### GPIO assignments

These are GPIO labels, not physical header positions. Verify the actual carrier-board pinout.

| Signal | GPIO |
| --- | --- |
| I2C SDA: three ToF sensors and MPU6050 | 8 |
| I2C SCL | 9 |
| Front / left / right XSHUT | 10 / 11 / 12 |
| Left encoder A / B | 13 / 14 |
| Right encoder A / B | 15 / 16 |
| Left motor input A / B | 4 / 5 |
| Right motor input A / B | 6 / 7 |
| Reserved MPU interrupt | 17 |
| Optional physical-stop auxiliary contact | 18 |
| RGB data | 38 by default; verify whether your carrier uses 38, 48, or another pin |

Reserve GPIO19/20 for USB and GPIO43/44 for serial. Avoid boot-strapping pins. GPIO35–37 are unavailable on the applicable octal-PSRAM N16R8 module.

### Electrical interfaces

- Power the ESP32 through its verified 5 V input or USB during bench setup.
- Use a motor-power branch matched to the actual motor rating, with common ground.
- Motor current must not flow through ESP32 power headers or a solderless breadboard.
- Check the ToF breakout schematic before selecting VIN and I2C voltage. A board accepting 5 V power can still expose lower-voltage XSHUT/interrupt pins.
- XSHUT firmware outputs are open-drain: LOW holds reset; HIGH releases the line. Use the breakout's correct pull-up, rather than adding a pull-up to an arbitrary rail.
- Verify MPU6050 supply and I2C pull-ups. AD0 is LOW for address 0x68.
- Encoder supply is separate from the motor supply. Convert encoder outputs to safe ESP32 logic levels where required.
- Check that the MX1508 board accepts 3.3 V control. Add an appropriate interface if it does not.
- Fit motor-input pull-downs and suitable supply decoupling. Typical initial noise suppression includes 100 nF across motor terminals and a suitably rated bulk capacitor near the driver.
- USB and external 5 V must not backfeed one another; verify the carrier's power path.

The optional GPIO18 contact is a low-voltage monitoring loop: 10 kOhm pull-up to 3.3 V, normally closed auxiliary contact to ground. Motor power uses a separate appropriately rated contact. HIGH means stop/broken monitoring circuit. Never connect motor voltage to GPIO18.

See the chip/carrier documentation rather than assuming all boards labelled V2 share the same circuit:

- [Espressif S3 module documentation](https://documentation.espressif.com/esp32-s3-wroom-1_wroom-1u_datasheet_en.html)
- [ST VL53L1X datasheet](https://www.st.com/resource/en/datasheet/vl53l1x.pdf)
- [ST VL53L0X datasheet](https://www.st.com/resource/en/datasheet/vl53l0x.pdf)
- [Example carrier voltage and XSHUT documentation](https://www.pololu.com/product/3415)

### Mechanical setup

Mount sensors front 0 degrees, left +90 degrees, and right -90 degrees, at a common suitable height. Keep windows unobstructed. Remove protective optical liners where the manufacturer instructs.

Use robot coordinates X forward, Y left, positive yaw counterclockwise. Measure sensor offsets relative to the midpoint between drive-wheel centres. Mount the MPU6050 rigidly with its Z axis up; transform/reconfigure the gyro reading in firmware if the actual orientation differs.

## Firmware build and connection

The firmware uses Arduino-ESP32 on its ESP-IDF/FreeRTOS foundation through PlatformIO. This makes the established ToF and MPU drivers usable in one reproducible build. The motor controller and command watchdog run in their own 100 Hz FreeRTOS task, independently of the network loop.

Timestamped encoder/gyro frames are acquired at a nominal 100 Hz and batched into approximately 20 WebSocket messages per second. Each ToF module runs on its own configured measurement cycle; a new range is included only when available. Network batching preserves the individual acquisition timestamps.

The supplied board profile explicitly configures 16 MB flash and 8 MB OPI PSRAM. The two application partitions are 6 MB each.

1. Install the development dependencies:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
~~~

2. Copy firmware/include/secrets.example.h to firmware/include/secrets.h. Fill in:

- Wi-Fi SSID/password.
- This computer's actual Wi-Fi IPv4 address. Do not use localhost.
- Server port, normally 8000.
- Robot pairing token from **Hardware connection** in the app.

3. Review firmware/include/config.h:

- Set each TOF_MODELS entry to 0 for VL53L0X or 1 for VL53L1X.
- Verify RGB_PIN, encoder polarity, motor polarity, and all GPIO assignments.
- Enable physical-stop contact handling only when that contact is wired.
- Leave HARDWARE_VERIFIED false while doing the initial sensor/communication checks.

4. Build:

~~~powershell
cd firmware
..\.venv\Scripts\python.exe -m platformio run
~~~

5. Flash and monitor, replacing COM7 with the actual port:

~~~powershell
..\.venv\Scripts\python.exe -m platformio run --target upload --upload-port COM7
..\.venv\Scripts\python.exe -m platformio device monitor --port COM7 --baud 115200
~~~

If necessary, use the carrier's BOOT/RESET procedure to enter download mode. Select the physical board's appropriate USB connector.

6. Launch the application with -Lan. Allow the server on the private network when Windows Firewall asks. The computer and robot must be reachable on that network; guest/client isolation can prevent this.
7. In **Hardware connection**, select **ESP32-S3 master**. Firmware connects to /ws/robot with a pairing-token Authorization header. The app initially rejects robot connections while Simulation is selected.
8. Verify all three ToF sensors and the IMU initialize correctly.
9. Measure and save the physical calibration in the app. Confirm the actual ToF model and verification checkbox.
10. With the motors physically isolated or wheels raised, finish the wiring review. Set HARDWARE_VERIFIED true, rebuild, and reflash.
11. Confirm each forward wheel command produces forward-positive encoder counts. Tune the speed-loop gains at low speed before floor operation.

Both the application and firmware must permit motor operation. Motor availability also requires the IMU and all three ToF sensors to initialize successfully. Placeholder wheel/encoder values are not a calibrated robot.

The three sensors are assigned 7-bit addresses 0x30, 0x31, and 0x32 after individually releasing XSHUT. This sequence repeats at startup. MPU6050 uses 0x68.

This release uses robot protocol **2**. Reflash the updated firmware if you used an earlier build. Each explicit arm action creates a new token; a watchdog timeout or disconnect invalidates the current token, so repeated velocity commands cannot restart the motors. Command sequences reset on a new connection, allowing a computer restart with the robot still powered.

The VL53L0X path checks the device's range-status bits as well as timeout and distance limits, following the [ST reference driver distributed by Adafruit](https://github.com/adafruit/Adafruit_VL53L0X/blob/master/src/core/src/vl53l0x_api_core.cpp). It does not reproduce that driver's complete software sigma estimator. Validate range performance on the actual surface and carrier. A sensor that stops producing fresh measurements inhibits the motors, even if its I2C address still responds.

Included firmware joins an existing Wi-Fi network. ESP32 access-point provisioning is a future extension; it is not claimed as implemented.

## Calibration

Open **Calibration** and enter:

- Wheel diameter and effective wheel separation.
- Encoder counts per wheel revolution, including gearbox and full-quadrature decoding.
- Left/right distance multipliers.
- Initial gyro bias.
- Sensor positions, mounting angles, range offsets, effective beam width, and usable range.
- Sensor height, target side, grid resolution, and speed limits.

Use several marked wheel revolutions and measured straight runs to establish distance per count. Use measured turns in both directions to refine effective separation. Hold the robot stationary to observe gyroscope bias settling.

Defaults such as 65 mm wheels, 160 mm separation, and 1440 counts/revolution are illustrative.

Changing calibration requires finishing the current survey. Calibration is stored with each recording, and replay uses the recorded profile by default.

## Kalman filter and mapping details

The EKF state is [x, y, heading, gyro_bias]. Wheel increments supply planar translation; the bias-corrected gyroscope supplies rotation. Wheel/gyro rate consistency and stationary zero-rate observations update the bias. The filter propagates a 4x4 covariance with the nonlinear motion Jacobian and uses a Joseph-form covariance update.

Moving bias updates use non-overlapping 200 ms rate windows. Strong stationary updates require at least 300 ms of sustained encoder/gyro stillness. This avoids treating short gaps between encoder ticks during a slow turn as evidence of zero rotation.

Encoder-only odometry is calculated separately for comparison. The accelerometer is not double-integrated to invent a position estimate. This implementation assumes a planar robot and correctly mounted Z-axis gyro.

The EKF does not use ToF ranges as absolute pose measurements. Without map/reference constraints, global position and heading drift remain possible. Displayed uncertainty is a model estimate, not a validated accuracy certificate.

Range observations are placed using their estimated acquisition-time poses and calibrated sensor transforms. Valid observations add distributed occupied evidence over an angular/range band; free-space evidence is conservative. Invalid returns do not clear unknown space.

Each return contributes at most once to a cell, including its independent boundary-support count. Overlapping sampled rays from the same observation do not create extra support. The inspector's updated-cell count includes both free and occupied evidence.

The target-facing setting controls which observations support the object boundary. All sensor observations can still contribute to the surrounding occupancy map.

Starting a session preserves a learned stationary gyro bias when enough stationary samples are available. That initial bias is saved in the recording so reconstruction uses the same initial condition.

The current grid covers 16 m x 16 m around the source origin. A clipping notice appears at the extent. Use another segment for larger surveys. Grid resolution is independent of physical accuracy.

Replay supports acquisition-time playback speeds and reconstruction with the current calibration profile. Such overrides do not overwrite original measurements; exports identify both the acquisition profile and the derived-map profile.

The replay sensor panel follows recorded raw returns, including paused intervals. The Calibration editor always opens the current saved robot profile, independently of a recording's calibration. Imported profiles are validated before replacing the editor's values.

The boundary is a set of supported occupied cells. It is not forced closed or replaced with a convex hull. Area/perimeter are deliberately not reported from incomplete evidence. Small rough features can be unresolved due to field of view, occlusion, reflectance, lighting, and pose error.

Firmware estimates ToF acquisition time using the configured measurement-budget midpoint. It is an approximation; very fast motion and long timing budgets increase placement uncertainty.

## Pose graph correction

1. Finish a session or open a replay.
2. Open **Compare & refine**.
3. Select **Surveyed correction**.
4. Enter the independently measured endpoint X/Y/heading relative to the starting frame.
5. Document the reference method and explicitly confirm it.
6. Optimize and rebuild.

Zero endpoint coordinates are valid only when you actually returned to the same position and heading, or when using a known corresponding simulation reference. Being visually near the start is insufficient.

The solver uses SE(2) keyframes, relative-motion constraints, a fixed starting pose, robust least squares, and the supplied endpoint prior. Original observations are reprojected through the corrected trajectory into a new grid. Reference/result metadata is retained with the recording and exports.

This is reference-assisted pose graph optimization. Automatic reliable loop detection from three fixed scalar ranges is not implemented. Reduced endpoint residual does not by itself prove improved whole-boundary accuracy.

## Control and stopping

- Arm drive explicitly before manual movement.
- Arrow keys/WASD or held pointer buttons request velocity.
- Releasing requests zero velocity.
- Space stops and disarms.
- Pause stops movement and pauses map integration; raw telemetry continues.
- Finish stops movement and saves the session.
- Emergency stop latches disabled motion until deliberately cleared.
- Manual control stops on lost focus, controller disconnect, or stale heartbeat.
- The application watchdog is approximately 300 ms; the firmware watchdog is 250 ms.
- Commands include boot ID, sequence, and a short deadline based on robot telemetry time.
- Reconnection never automatically resumes movement.
- A reboot or odometry discontinuity requires a new session segment.
- Replay cannot arm the robot.
- Opening a dialog or leaving the driving workspace stops manual control. Graph correction also disarms before processing.

The simulator's automated sample survey can run without a manual-control heartbeat because it cannot command hardware. Physical and manually driven sources do not receive that exception.

The app distinguishes desired states from robot acknowledgements. A zero-speed request, acknowledgement, and physical stopping are different events; validate stopping distance on your chassis. The driver defaults to zero effort/coasting, not a certified emergency brake. Use the physical motor disconnect independently.

### RGB states

| Robot state | LED |
| --- | --- |
| Boot | White |
| Connecting / application disconnected | Pulsing blue |
| Connected and ready | Green |
| Mapping | Pulsing cyan |
| Paused | Amber |
| Finish command received | Brief purple |
| Latched stop | Red |

The app's indicator represents requested/known state; firmware drives the physical LED from its own applied state.

## Files and exports

Local runtime data lives in the ignored .local directory:

- sessions.sqlite3: samples, sessions, events, and reference-result metadata.
- profile.json: current physical calibration.
- robot-token: ESP32 authentication secret.
- operator-token: browser/API authentication secret.

Localhost gets an operator cookie automatically. Access from another computer requires the operator token. Pairing secrets are not committed. This is a private-LAN tool; TLS termination and wider deployment are outside this release.

Export ZIP contents:

- session.json: original samples, saved calibration, events, notes, and derived trajectory metadata.
- measurements.csv: frame/sample timestamps, counts, gyro, range status, and integration decisions.
- profile.json: calibration used for the exported map.
- map.pgm and map.yaml: metric occupancy-map files.
- map.png: grayscale occupancy visualization.
- boundary.svg: supported boundary cells, expressed in metres.

PNG/PGM use image-down coordinates; YAML supplies world origin/resolution. Gray cells retain unknown or insufficiently certain evidence; black is occupied and white is free. SVG reflects world Y for image display. Unsupported gaps are not closed.

## Development and checks

Backend:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
~~~

Frontend development, with the backend running:

~~~powershell
cd frontend
npm ci
npm run dev
~~~

Vite proxies API/WebSocket requests to port 8000. Production uses one origin and the built frontend served by FastAPI.

Build/check everything:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test.ps1
~~~

Backend API documentation is at /docs. Protected HTTP routes accept the operator cookie or Authorization: Bearer <operator-token>. Robot WebSocket authentication uses its separate robot token.

Tests cover EKF bias convergence and covariance, heading interpolation, invalid ranges, sensor transforms, target-side filtering, deterministic reconstruction, documented graph constraints, authentication, recording/export/replay, and controller disconnect stopping.

Compilation and simulator checks do not replace physical hardware tests.

Verification results and the physical acceptance checklist are recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md).

The follow-up bug review and regression coverage are described in [docs/REVIEW.md](docs/REVIEW.md).

## Project structure

~~~text
backend/mapper/     API, protocol models, EKF, mapping, simulator, graph, SQLite
backend/tests/      Algorithm and integration tests
frontend/src/       React console and Canvas renderer
firmware/           PlatformIO project, board profile, GPIO/configuration
scripts/            Windows launch and verification scripts
requirements.lock   Pinned runtime Python dependencies
start.cmd           Windows entry point
~~~

## Troubleshooting

| Symptom | Check |
| --- | --- |
| App does not start | Python/Node prerequisites, launcher terminal, occupied port |
| ESP32 cannot connect | -Lan mode, correct computer IPv4, Wi-Fi isolation/firewall, token, source selection |
| Motors inhibited | Firmware verification, successful sensor initialization, app calibration verification |
| ToF does not initialize | Actual chip selection, power/interface voltage, XSHUT, I2C wiring |
| Only one ToF responds | Independent XSHUT wires and startup address assignment |
| Encoder path mirrored | Motor/encoder polarity, robot coordinate convention |
| Map bends or fails to close | Wheel scale/separation, gyro bias, slip, sensor transforms, missing reference |
| Some edges are missing | Target side, field of view, occlusion, quality/range filtering, material/lighting |
| Pose discontinuity | Finish the session, verify robot position, and start a new segment |
| Network interruption | Motion stops; explicit reconnection/rearming is required |
