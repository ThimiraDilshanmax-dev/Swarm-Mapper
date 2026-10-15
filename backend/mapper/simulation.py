"""Seeded simulated hardware. Ground truth is never supplied to the estimator."""
from __future__ import annotations
import math
import numpy as np
from .models import Profile, RangeSample, Telemetry
from .estimation import wrap


class Simulator:
    def __init__(self, profile: Profile, seed: int = 42):
        self.profile = profile
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.seq = 0
        self.pose = np.zeros(3)
        self.counts = np.zeros(2)
        self.wheels = np.zeros(2)
        self.distance = 0.0
        self.demo = False
        self.demo_distance = 0.0
        self.demo_done = False
        self.shape = "irregular"
        self.radius = 1.6
        self.polygon = self.make_polygon()
        self.last_ranges = -1.0

    def make_polygon(self):
        # Local map frame: the object is to the robot's left at the start.
        theta = np.linspace(0, 2 * math.pi, 80, endpoint=False)
        if self.shape == "box":
            return [[-0.75, 0.95], [0.75, 0.95], [0.75, 2.25], [-0.75, 2.25]]
        radial = np.ones_like(theta) * 0.73
        if self.shape == "irregular":
            radial *= 1 + 0.16 * np.sin(3 * theta + 0.3) + 0.09 * np.cos(7 * theta) + 0.025 * np.sin(17 * theta)
        return [[float(r * math.cos(a)), float(self.radius + r * math.sin(a) * 0.87)]
                for r, a in zip(radial, theta)]

    def raycast(self, origin: np.ndarray, angle: float) -> float | None:
        direction = np.array([math.cos(angle), math.sin(angle)])
        nearest = float("inf")
        vertices = np.asarray(self.polygon)
        for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
            edge = b - a
            cross = direction[0] * edge[1] - direction[1] * edge[0]
            if abs(cross) < 1e-9:
                continue
            delta = a - origin
            t = (delta[0] * edge[1] - delta[1] * edge[0]) / cross
            u = (delta[0] * direction[1] - delta[1] * direction[0]) / cross
            if t >= 0 and 0 <= u <= 1:
                nearest = min(nearest, t)
        return nearest if math.isfinite(nearest) else None

    def step(self, dt: float, v: float, omega: float, armed: bool, mapping: str,
             stop_latched: bool, ack: int) -> Telemetry:
        if self.demo and armed and not self.demo_done:
            v = min(0.23, self.profile.max_speed)
            omega = v / self.radius
            self.demo_distance += abs(v * dt)
            if self.demo_distance >= 2 * math.pi * self.radius:
                self.demo_done = True
                v = omega = 0
        if not armed or stop_latched:
            v = omega = 0
        desired = np.array([v - omega * self.profile.wheel_base / 2,
                            v + omega * self.profile.wheel_base / 2])
        self.wheels += (desired - self.wheels) * min(1, dt * 12)
        if stop_latched or not armed:
            self.wheels *= max(0, 1 - dt * 30)
        left, right = self.wheels * dt
        ds = (left + right) / 2
        turn = (right - left) / self.profile.wheel_base
        mid = self.pose[2] + turn / 2
        self.pose += [ds * math.cos(mid), ds * math.sin(mid), turn]
        self.pose[2] = wrap(float(self.pose[2]))
        self.distance += abs(ds)
        mpc = math.pi * self.profile.wheel_diameter / self.profile.counts_per_revolution
        self.counts += [left * 1.002 / mpc, right * 0.999 / mpc]
        self.t += dt
        self.seq += 1
        gyro = turn / dt + 0.0025 + self.rng.normal(0, 0.0015)
        ranges = []
        if self.t - self.last_ranges >= 0.08:
            self.last_ranges = self.t
            c, s = math.cos(self.pose[2]), math.sin(self.pose[2])
            for sensor in self.profile.sensors:
                origin = self.pose[:2] + [c * sensor.x - s * sensor.y, s * sensor.x + c * sensor.y]
                hits = [self.raycast(origin, self.pose[2] + sensor.yaw + a)
                        for a in (-sensor.fov * 0.25, 0, sensor.fov * 0.25)]
                hits = [h for h in hits if h is not None and sensor.min_range <= h <= sensor.max_range]
                distance = min(hits) + self.rng.normal(0, 0.008) if hits else None
                valid = distance is not None and self.rng.random() > 0.015
                ranges.append(RangeSample(sensor=sensor.id, t=self.t, distance=distance,
                    valid=valid, status="valid" if valid else "no reliable return",
                    signal=1.2 if valid else 0.02, ambient=0.03))
        return Telemetry(seq=self.seq, t=self.t, left=round(self.counts[0]), right=round(self.counts[1]),
                         gyro_z=float(gyro), ranges=ranges, armed=armed, mapping=mapping,
                         stop_latched=stop_latched, ack=ack, motor_enabled=True)
