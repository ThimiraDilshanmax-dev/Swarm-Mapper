# Contour Swarm-Mapper: Complete Step-by-Step Operating Guide

This guide provides end-to-end instructions for setting up, configuring, connecting, calibrating, and running the **Contour** robot mapping system.

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Prerequisites](#2-prerequisites)
3. [Step 1: Start the PC Application Console](#step-1-start-the-pc-application-console)
4. [Step 2: Network & Mobile Hotspot Setup](#step-2-network--mobile-hotspot-setup)
5. [Step 3: Firmware Configuration & Flashing](#step-3-firmware-configuration--flashing)
6. [Step 4: Bench Verification & Sensor Checks](#step-4-bench-verification--sensor-checks)
7. [Step 5: Unlock & Arm Drive in the Web Console](#step-5-unlock--arm-drive-in-the-web-console)
8. [Step 6: Live 2D Object Mapping & RC Driving](#step-6-live-2d-object-mapping--rc-driving)
9. [Step 7: Surveyed Pose Graph Optimization](#step-7-surveyed-pose-graph-optimization)
10. [Step 8: Session Replay & Data Export](#step-8-session-replay--data-export)
11. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## 1. System Overview

* **Master Robot**: ESP32-S3-N16R8, 2× N20 encoder gearmotors, MX1508 motor driver, MPU6050 6-DoF IMU, and 3 fixed Time-of-Flight (ToF) sensors (Front, Left, Right).
* **PC Application (Contour)**: Local FastAPI Python backend + React TypeScript HTML5 Canvas frontend. Fuses encoders and gyroscope via a 4-state Extended Kalman Filter (EKF), builds a probabilistic occupancy grid map, extracts 2D object boundaries, and provides manual RC driving controls over local Wi-Fi WebSockets.

---

## 2. Prerequisites

Ensure your host PC has the following installed:
* **Python**: 3.11 or newer (verify with `python --version`).
* **Node.js**: v20.19+ or v24+ (verify with `node --version`).
* **PlatformIO**: Installed either via VS Code extension or command line (`pip install platformio`).

---

## Step 1: Start the PC Application Console

1. Open PowerShell and navigate to the project root directory:
   ```powershell
   cd "c:\My Files\Academics\5 Short Semester 2 - Sep 2026\CO3060 - Computer Systems Design Project\Repos\Swarm-Mapper"
   ```

2. Allow port `8000` through Windows Defender Firewall (run once as Administrator if not already done):
   ```powershell
   netsh advfirewall firewall add rule name="Contour" dir=in action=allow protocol=TCP localport=8000
   ```

3. Launch the application with the `-Lan` flag so it accepts connections from the robot on your local network:
   ```powershell
   .\start.cmd -Lan
   ```
   * *Note*: On the first run, the script automatically installs Python dependencies from `requirements.lock`, compiles the frontend with `npm`, and opens `http://127.0.0.1:8000` in your browser.

4. Keep this terminal window open while using Contour.

---

## Step 2: Network & Mobile Hotspot Setup

> **Important**: The ESP32-S3 **only supports 2.4 GHz Wi-Fi**. Furthermore, university or campus Wi-Fi networks typically enforce **AP Client Isolation**, which blocks the robot from communicating with your laptop.

**Recommended Setup (Mobile Hotspot):**
1. Turn on **Mobile Hotspot** on your smartphone.
   * On iPhone: Ensure **"Maximize Compatibility"** is enabled (forces 2.4 GHz).
2. Connect both your **PC** and your **ESP32** to this phone hotspot.
3. Find your PC's IP address on the hotspot network:
   * Open a new PowerShell terminal and run:
     ```powershell
     ipconfig
     ```
   * Look for the **Wireless LAN adapter Wi-Fi** IPv4 address (typically `192.168.43.xxx` or `172.20.10.xxx`).
4. In the Contour web interface (`http://127.0.0.1:8000`), click **Hardware connection** in the left sidebar:
   * Copy the **Robot pairing token** (click **Show** or **Copy**).

---

## Step 3: Firmware Configuration & Flashing

1. Navigate to the firmware directory:
   ```powershell
   cd firmware
   ```

2. Create `firmware/include/secrets.h` (copy from `secrets.example.h`):
   ```cpp
   #pragma once
   constexpr char WIFI_SSID[] = "YOUR_HOTSPOT_NAME";
   constexpr char WIFI_PASSWORD[] = "YOUR_HOTSPOT_PASSWORD";
   constexpr char SERVER_HOST[] = "192.168.43.XXX"; // Your PC's Wi-Fi/Hotspot IP
   constexpr uint16_t SERVER_PORT = 8000;
   constexpr char ROBOT_TOKEN[] = "PASTE_TOKEN_FROM_CONTOUR_HERE";
   ```

3. Check hardware configuration in `firmware/include/config.h`:
   * **ToF Model**:
     * If your breakout boards are **VL53L0X** (standard purple/blue "V2" boards): set `constexpr int TOF_MODELS[3] = {0, 0, 0};`.
     * If your breakout boards are **VL53L1X**: set `constexpr int TOF_MODELS[3] = {1, 1, 1};`.
   * **Motor Safety**: Keep `HARDWARE_VERIFIED = false;` during initial bench testing.
   * **RGB LED**: Verify pin (`38` for DevKitC-1 v1.1; `48` for older revisions).

4. **Verify ToF XSHUT configuration in `firmware/src/main.cpp`**:
   In `initializeSensors()`:
   * Ensure `pinMode(XSHUT_PINS[i], OUTPUT);` (push-pull) is used so the ESP32 actively drives XSHUT to 3.3V.
   * Ensure `delay(50);` is given after driving XSHUT `HIGH` to allow internal sensor boot.
   * Ensure `setTimeout(200);` is used.

5. Connect the ESP32-S3 to your PC with a USB data cable and flash the firmware:
   ```powershell
   pio run -t upload
   ```

---

## Step 4: Bench Verification & Sensor Checks

With the robot wheels elevated off the ground:

1. Open the PlatformIO serial monitor:
   ```powershell
   pio device monitor
   ```
2. Press the **EN / RESET** button on the ESP32. Verify the startup log:
   ```text
   front ToF: ready
   left ToF: ready
   right ToF: ready
   MPU6050: ready
   Contour firmware. Hardware verification: MOTORS INHIBITED. RGB GPIO: 38
   ```

3. **Check the Built-in RGB LED**:
   * **Pulsing Blue**: Searching for Wi-Fi / connecting to PC.
   * **Solid Green**: Connected to Contour backend and healthy!

4. **Verify Telemetry in Contour Web Console**:
   * Open `http://127.0.0.1:8000`.
   * The status card will show **"ESP32-S3 connected"** with a green indicator.
   * **ToF Sensors**: In the right sidebar under **Sensor readings (ToF × 3)**, wave your hand in front of Front, Left, and Right sensors; verify the distance changes in real time.
   * **MPU6050 Gyro**: Rotate the robot on the table; verify the **🧭 Heading** value under the map updates smoothly.
   * **Wheel Encoders**: Rotate each wheel forward by hand; verify encoder counts increment positively.

---

## Step 5: Unlock & Arm Drive in the Web Console

Contour prevents motor drive until safety verification is completed:

1. In `firmware/include/config.h`:
   * Set `constexpr bool HARDWARE_VERIFIED = true;`.
   * Re-flash the board: `pio run -t upload`.
2. In the Contour web console, click **Calibration** in the left sidebar:
   * Under **Robot geometry**, verify your wheel diameter and wheel base.
   * Under **Mapping & Kalman filter**, select your actual **ToF chip model** (`VL53L0X` or `VL53L1X`).
   * In the right panel, check the box: **☑ I verified these values against my physical robot.**
   * Click **Save calibration**.
3. In the left sidebar, click **Hardware connection**:
   * Select **"ESP32-S3"** as the active source.
4. Return to the **Live** tab:
   * Click **Arm drive** (or press the arm shortcut). The status badge will change to **Armed (mint green)**.

---

## Step 6: Live 2D Object Mapping & RC Driving

1. **Place the Robot**:
   * Place the robot on a level floor facing a stationary target object (cardboard box, cylinder, or irregular fixture).
   * Mark the robot's starting position and heading with tape on the floor.
2. **Start Mapping Session**:
   * Click **Start mapping** in the top toolbar. Enter a session name (e.g., `Box Survey 01`).
   * The RGB LED will transition to **Pulsing Cyan**.
3. **Drive the Robot**:
   * Focus the drive area and drive using **Arrow Keys** or **WASD** (or on-screen virtual pad).
   * **Release key**: requests zero speed.
   * **Spacebar**: stops motion immediately.
   * Drive slowly around the perimeter of the object (recommended speed: `0.10` to `0.15 m/s`).
4. **Observe Real-Time Mapping**:
   * **Purple Line**: 4-state EKF estimated trajectory.
   * **Gray Cells**: Observed free space.
   * **Dark Cells**: High-probability occupied regions.
   * **Purple Dots / Outline**: Supported object boundary.
   * **Reading Inspector**: Click any point or measurement ray to see its acquisition timestamp, sensor origin, raw range, and cell contribution.
5. **Pause / Finish**:
   * Click **Pause** if repositioning is needed.
   * Click **Finish survey** once you complete the loop around the object.

---

## Step 7: Surveyed Pose Graph Optimization

Since three fixed ToF sensors provide sparse observations, accumulated odometry drift can occur over long loops.

1. Drive the robot back to your exact marked physical starting tape fixture (matching the original position `(0, 0)` and heading `0.0°`).
2. Click **Finish survey**.
3. Go to the **Compare** tab (or click **Surveyed correction**):
   * Endpoint X: `0.00 m`
   * Endpoint Y: `0.00 m`
   * Endpoint Heading: `0.0°`
   * Position Sigma: `0.03 m`
   * Check **☑ I independently verified this endpoint and its heading**.
   * Enter a note (e.g. `Returned to marked tape fixture`).
   * Click **Optimize & rebuild**.
4. The nonlinear least-squares solver will distribute trajectory drift across keyframes and reproject all original ToF readings, producing an aligned closed boundary.

---

## Step 8: Session Replay & Data Export

1. Open the **Session library** tab in the sidebar:
   * View all recorded surveys stored in the local SQLite database.
   * Click **Open replay** on any session.
2. **Interactive Playback**:
   * Use Play / Pause or the timeline slider to step through the survey frame by frame.
   * Select readings to inspect how individual sensor pulses shaped the map.
   * Try rebuilding the map with modified grid resolution or calibration parameters.
3. **Export Research Bundle**:
   * Click **Export survey** in the top right.
   * Downloads a `.zip` archive containing:
     * `telemetry.json` & `telemetry.csv` (raw timestamps, encoder ticks, gyro rates, ranges).
     * `trajectory.json` (fused EKF and odometry poses).
     * `map.png` & `map.pgm` (occupancy grid).
     * `map.yaml` (ROS-compatible map metadata).
     * `boundary.svg` (vector outline of the mapped object).
     * `profile.json` (calibration snapshot).

---

## Troubleshooting Common Issues

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| **`Host is unreachable (errno 118)`** | ESP32 cannot route to PC IP due to campus AP isolation or wrong IP. | Connect both laptop and ESP32 to a 2.4 GHz phone mobile hotspot; verify laptop IP with `ipconfig` and update `SERVER_HOST` in `secrets.h`. |
| **`[Wire.cpp:499] requestFrom() returned Error -1`** | ToF sensor not responding / not waking up. | 1. In `main.cpp`, change XSHUT pinMode to `OUTPUT` (not `OPEN_DRAIN`).<br>2. In `config.h`, check whether your chips are `VL53L0X` (`0`) or `VL53L1X` (`1`).<br>3. Check jumper wires for SDA (GPIO 8) and SCL (GPIO 9). |
| **Cannot click "Arm drive" / Disarmed** | Safety checks active in firmware or UI. | 1. In web app: open **Calibration**, select ToF chip, tick "I verified these values...", and click **Save calibration**.<br>2. In `config.h`: set `HARDWARE_VERIFIED = true` and re-flash.<br>3. Ensure all 3 ToF sensors show valid ranges in the UI. |
| **One wheel spins backwards when driving forward** | Motor polarity reversed. | In `firmware/include/config.h`, invert the corresponding wheel sign in `MOTOR_SIGN` (e.g., change `{1, 1}` to `{-1, 1}`). |
| **Robot stops suddenly after ~250 ms** | Safety watchdog timeout. | Normal behavior when keyboard keys are released or connection drops; hold down the movement key to maintain continuous motion. |
| **Heading drifts when robot is stationary** | Uncalibrated gyro zero-bias. | Keep the robot completely still on a flat table for 5 seconds after boot; the EKF automatically learns and suppresses stationary gyro bias. |
