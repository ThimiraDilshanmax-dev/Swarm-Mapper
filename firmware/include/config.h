#pragma once

// Set true ONLY after checking the hardware wiring and voltage interfaces.
constexpr bool HARDWARE_VERIFIED = true;
// GPIO numbers, not physical header positions. Verify the actual carrier board.
constexpr int SDA_PIN = 8, SCL_PIN = 9;
constexpr int XSHUT_PINS[3] = {10, 11, 12}; // front, left, right
constexpr int ENCODER_PINS[2][2] = {{13, 14}, {15, 16}};
constexpr int MOTOR_PINS[2][2] = {{4, 5}, {6, 7}};
constexpr int ENCODER_SIGN[2] = {1, 1}; // verify forward-positive on both wheels
constexpr int MOTOR_SIGN[2] = {1, 1};   // adjust for mirrored mounting
constexpr int RGB_PIN = 48; // Official v1.1: 38; older official boards: 48. Verify yours.
constexpr int STOP_PIN = 18;
constexpr bool USE_PHYSICAL_STOP_CONTACT = false;
// 0 = VL53L0X, 1 = VL53L1X. "V2" is not a chip identifier.
constexpr int TOF_MODELS[3] = {0,0,0};
constexpr uint32_t TOF_BUDGET_US = 50000;
constexpr uint32_t TOF_PERIOD_MS = 80;
constexpr uint32_t WATCHDOG_MS = 250;
constexpr int PWM_HZ = 20000;
constexpr int PWM_BITS = 10;
// Starting speed-loop parameters; tune with wheels raised, then under load.
constexpr float WHEEL_KP = 900.0f;
constexpr float WHEEL_KI = 1800.0f;
constexpr float WHEEL_FEED_FORWARD = 2200.0f;
constexpr float MAX_LINEAR_SPEED = 0.5f;
constexpr float MAX_ANGULAR_SPEED = 2.0f;
