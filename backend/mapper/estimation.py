"""Planar wheel/gyro fusion; no accelerometer double integration."""
from __future__ import annotations
import math
import numpy as np
from .models import Profile


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def interpolate_pose(a: list[float], b: list[float], fraction: float) -> list[float]:
    f = min(1.0, max(0.0, fraction))
    return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]),
            wrap(a[2] + f * wrap(b[2] - a[2]))]


class Estimator:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.pose = np.zeros(3)
        self.odom = np.zeros(3)
        # Error covariance for [x, y, heading, gyro_bias].
        self.cov = np.diag([0.0001, 0.0001, 0.0003, 0.0001])
        self.last: tuple[float, int, int] | None = None
        self.history: list[tuple[float, list[float]]] = []
        self.velocity = [0.0, 0.0]
        self.disagreement = 0.0
        self.distance = 0.0
        self.bias = profile.gyro_bias
        self.stationary_samples = 0
        self.stationary_duration = 0.0
        self.rate_duration = self.rate_turn = self.rate_gyro = 0.0

    def update(self, t: float, left: int, right: int, gyro: float) -> bool:
        if self.last is None:
            self.last = (t, left, right)
            self.history.append((t, self.pose.tolist()))
            return True
        prev_t, prev_l, prev_r = self.last
        dt = t - prev_t
        if dt <= 0:
            raise ValueError("Odometry discontinuity: acquisition time did not increase")
        scale = math.pi * self.profile.wheel_diameter / self.profile.counts_per_revolution
        dl = (left - prev_l) * scale * self.profile.left_scale
        dr = (right - prev_r) * scale * self.profile.right_scale
        # A count reset, impossible jump, or long acquisition gap needs a new segment.
        if dt > 1.0 or max(abs(dl), abs(dr)) > max(0.08, dt * 1.5):
            raise ValueError("Odometry discontinuity: reset/reconnect the source before mapping")
        self.last = (t, left, right)
        ds = (dr + dl) / 2
        wheel_turn = (dr - dl) / self.profile.wheel_base
        self.disagreement = abs(wheel_turn / dt - (gyro - self.bias))
        quiet = abs(dl) + abs(dr) < 1e-7 and abs(gyro - self.bias) < 0.06
        if quiet:
            self.stationary_samples += 1
            self.stationary_duration += dt
        else:
            self.stationary_samples = 0
            self.stationary_duration = 0.0
        # A short pause between quantized encoder ticks is not a zero-rate
        # observation. Require sustained stillness before the strong update.
        stationary = quiet and self.stationary_duration >= 0.3
        self.rate_duration += dt
        self.rate_turn += wheel_turn
        self.rate_gyro += gyro * dt
        fused_turn = (gyro - self.bias) * dt
        mid = float(self.pose[2]) + fused_turn / 2
        f = np.eye(4)
        f[0, 2], f[1, 2] = -ds * math.sin(mid), ds * math.cos(mid)
        f[0, 3], f[1, 3] = ds * math.sin(mid) * dt / 2, -ds * math.cos(mid) * dt / 2
        f[2, 3] = -dt
        self.pose += [ds * math.cos(mid), ds * math.sin(mid), fused_turn]
        self.pose[2] = wrap(float(self.pose[2]))
        motion_var = (0.0001 * math.sqrt(dt) + abs(ds) * 0.05) ** 2
        q = np.diag([motion_var, motion_var, (0.02 * dt)**2, 0.0003**2 * dt])
        self.cov = f @ self.cov @ f.T + q
        # Rate consistency observes gyro bias: gyro_z - wheel_yaw_rate = bias.
        # Stationary zero-rate updates are strongest. Encoder quantization and
        # wheel/gyro disagreement inflate moving updates, limiting slip influence.
        # Non-overlapping rate windows reduce tick quantization and avoid
        # repeatedly treating overlapping averages as independent evidence.
        if stationary or self.rate_duration >= 0.2 - 1e-9:
            z = self.rate_gyro / self.rate_duration
            if not stationary:
                z -= self.rate_turn / self.rate_duration
            quantization = scale / (self.profile.wheel_base * self.rate_duration)
            innovation = z - self.bias
            measurement_var = 0.003**2 if stationary else (
                0.03**2 + quantization**2 + (0.5 * innovation)**2)
            gain = self.cov[:, 3] / (self.cov[3, 3] + measurement_var)
            correction = gain * innovation
            self.pose += correction[:3]
            self.pose[2] = wrap(float(self.pose[2]))
            self.bias += float(correction[3])
            h = np.array([[0., 0., 0., 1.]])
            a = np.eye(4) - np.outer(gain, h[0])
            # Joseph form preserves positive semidefiniteness numerically.
            self.cov = a @ self.cov @ a.T + np.outer(gain, gain) * measurement_var
            self.cov = (self.cov + self.cov.T) / 2
            self.innovation = float(innovation)
            self.kalman_gain = float(gain[3])
            self.rate_duration = self.rate_turn = self.rate_gyro = 0.0
        omid = float(self.odom[2]) + wheel_turn / 2
        self.odom += [ds * math.cos(omid), ds * math.sin(omid), wheel_turn]
        self.odom[2] = wrap(float(self.odom[2]))
        self.velocity = [ds / dt, fused_turn / dt]
        self.distance += abs(ds)
        self.history.append((t, self.pose.tolist()))
        if len(self.history) > 1000:
            self.history = self.history[-500:]
        return True

    def at(self, t: float) -> list[float] | None:
        if not self.history or t < self.history[0][0] - 0.1 or t > self.history[-1][0] + 0.1:
            return None
        if t <= self.history[0][0]:
            return self.history[0][1].copy()
        for i in range(len(self.history) - 1, 0, -1):
            a, b = self.history[i - 1], self.history[i]
            if a[0] <= t <= b[0]:
                return interpolate_pose(a[1], b[1], (t - a[0]) / max(1e-9, b[0] - a[0]))
        return self.history[-1][1].copy()
