"""Conservative sparse-ToF occupancy evidence, boundary extraction, and exports."""
from __future__ import annotations
import math
import numpy as np
from scipy.ndimage import label
from .models import Profile, RangeSample


class Grid:
    def __init__(self, profile: Profile, size: float = 16):
        self.profile = profile
        self.resolution = profile.resolution
        self.n = math.ceil(size / self.resolution)
        self.origin = [-self.n * self.resolution / 2] * 2
        self.log_odds = np.zeros((self.n, self.n), dtype=np.float32)
        self.hits = np.zeros((self.n, self.n), dtype=np.uint16)
        self.seen = np.zeros((self.n, self.n), dtype=bool)
        self.readings: list[dict] = []
        self.accepted = 0
        self.rejected = 0
        self.version = 0

    def cell(self, x: float, y: float) -> tuple[int, int] | None:
        ix = math.floor((x - self.origin[0]) / self.resolution)
        iy = math.floor((y - self.origin[1]) / self.resolution)
        return (iy, ix) if 0 <= ix < self.n and 0 <= iy < self.n else None

    def integrate(self, sample: RangeSample, pose: list[float] | None,
                  reading_id: int, update: bool = True) -> dict:
        sensor = next(s for s in self.profile.sensors if s.id == sample.sensor)
        d = None if sample.distance is None else sample.distance + sensor.offset
        reason = "accepted"
        if not sample.valid or d is None:
            reason = sample.status if sample.status != "valid" else "invalid return"
        elif not sensor.min_range <= d <= sensor.max_range:
            reason = "outside calibrated range"
        elif pose is None:
            reason = "pose unavailable at acquisition time"
        accepted = reason == "accepted"
        if accepted:
            self.accepted += 1
        else:
            self.rejected += 1
        p = pose or [0.0, 0.0, 0.0]
        c, s = math.cos(p[2]), math.sin(p[2])
        sx, sy = p[0] + c * sensor.x - s * sensor.y, p[1] + s * sensor.x + c * sensor.y
        angle = p[2] + sensor.yaw
        endpoint = [sx + (d or 0) * math.cos(angle), sy + (d or 0) * math.sin(angle)]
        target = self.profile.target_side == "all" or sample.sensor == self.profile.target_side
        reading = dict(id=reading_id, t=sample.t, sensor=sample.sensor, distance=d,
                       accepted=accepted, reason=reason, pose=p, origin=[sx, sy],
                       angle=angle, fov=sensor.fov, endpoint=endpoint, target=target,
                       signal=sample.signal, ambient=sample.ambient, cells=0)
        if accepted and update:
            # Occupied evidence is distributed over an angular/range band, not a point.
            radial_sigma = max(0.018, d * 0.015)
            angles = np.linspace(angle - sensor.fov / 2, angle + sensor.fov / 2, 7)
            free_weights, occupied_weights = {}, {}
            for ai, a in enumerate(angles):
                angular_weight = math.exp(-0.5 * ((ai - 3) / 1.7) ** 2)
                # Weak free evidence, ending before the uncertain return.
                for r in np.arange(0.05, max(0.05, d - 3 * radial_sigma), self.resolution * 1.5):
                    cell = self.cell(sx + r * math.cos(a), sy + r * math.sin(a))
                    if cell:
                        free_weights[cell] = max(free_weights.get(cell, 0), angular_weight)
                for delta in (-radial_sigma, 0, radial_sigma):
                    cell = self.cell(sx + (d + delta) * math.cos(a), sy + (d + delta) * math.sin(a))
                    if cell:
                        weight = angular_weight * math.exp(-0.5 * (delta / radial_sigma) ** 2)
                        occupied_weights[cell] = max(occupied_weights.get(cell, 0), weight)
            # Each scalar observation contributes at most once to each cell,
            # regardless of how many sampled rays land there.
            for cell, weight in free_weights.items():
                if cell not in occupied_weights:
                    self.log_odds[cell] = max(-4, self.log_odds[cell] - 0.045 * weight)
                    self.seen[cell] = True
            for cell, weight in occupied_weights.items():
                self.log_odds[cell] = min(5, self.log_odds[cell] + 0.28 * weight)
                self.seen[cell] = True
                if target:
                    self.hits[cell] = min(65535, int(self.hits[cell]) + 1)
            reading["cells"] = len(free_weights.keys() | occupied_weights.keys())
            self.version += 1
        self.readings.append(reading)
        self.readings = self.readings[-400:]
        return reading

    def occupied_mask(self):
        return (self.log_odds > 0.48) & (self.hits >= 2)

    def boundary(self) -> list[list[float]]:
        mask = self.occupied_mask()
        groups, count = label(mask, structure=np.ones((3, 3)))
        if not count:
            return []
        sizes = np.bincount(groups.ravel())
        keep = np.flatnonzero(sizes >= 3)
        keep = keep[keep != 0]
        iy, ix = np.nonzero(mask & np.isin(groups, keep))
        # Deliberately unordered supported cells: never join across unobserved gaps.
        return [[round(self.origin[0] + (x + 0.5) * self.resolution, 4),
                 round(self.origin[1] + (y + 0.5) * self.resolution, 4)] for y, x in zip(iy, ix)]

    def payload(self) -> dict:
        iy, ix = np.nonzero(self.seen)
        if len(ix):
            lo_x, hi_x = max(0, int(ix.min()) - 1), min(self.n, int(ix.max()) + 2)
            lo_y, hi_y = max(0, int(iy.min()) - 1), min(self.n, int(iy.max()) + 2)
            cells = self.log_odds[lo_y:hi_y, lo_x:hi_x]
            seen = self.seen[lo_y:hi_y, lo_x:hi_x]
            values = np.where(seen, np.rint(100 / (1 + np.exp(-cells))), -1).astype(np.int16)
            data = values.ravel().tolist()
        else:
            lo_x = lo_y = 0
            hi_x = hi_y = 1
            data = [-1]
        boundary = self.boundary()
        bounds = None
        if boundary:
            a = np.asarray(boundary)
            bounds = dict(width=round(float(np.ptp(a[:, 0])), 3),
                          height=round(float(np.ptp(a[:, 1])), 3))
        return dict(resolution=self.resolution, origin=[
            self.origin[0] + lo_x * self.resolution, self.origin[1] + lo_y * self.resolution],
            width=hi_x - lo_x, height=hi_y - lo_y, data=data, boundary=boundary,
            bounds=bounds, version=self.version, accepted=self.accepted, rejected=self.rejected,
            clipped=bool(len(ix) and (ix.min() == 0 or iy.min() == 0 or ix.max() == self.n-1 or iy.max() == self.n-1)))

    def pgm(self) -> bytes:
        values = np.where(self.seen & (self.log_odds > 0.48), 0,
                          np.where(self.seen & (self.log_odds < -0.48), 254, 205)).astype(np.uint8)
        return ("P5\n%d %d\n255\n" % (self.n, self.n)).encode() + np.flipud(values).tobytes()
