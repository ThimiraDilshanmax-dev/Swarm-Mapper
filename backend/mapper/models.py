from __future__ import annotations

import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SensorConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: Literal["front", "left", "right"]
    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)
    yaw: float
    fov: float = Field(default=math.radians(15), ge=0.02, le=1.2)
    offset: float = Field(default=0, ge=-0.2, le=0.2)
    min_range: float = Field(default=0.05, ge=0.01, le=1)
    max_range: float = Field(default=2, ge=0.1, le=4)

    @model_validator(mode="after")
    def valid_limits(self):
        if self.max_range <= self.min_range:
            raise ValueError("Maximum range must exceed minimum range")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = Field(default="Master · prototype", min_length=1, max_length=80)
    wheel_diameter: float = Field(default=0.065, ge=0.015, le=0.5)
    wheel_base: float = Field(default=0.16, ge=0.05, le=1)
    counts_per_revolution: int = Field(default=1440, ge=4, le=1000000)
    left_scale: float = Field(default=1, ge=0.5, le=1.5)
    right_scale: float = Field(default=1, ge=0.5, le=1.5)
    gyro_bias: float = Field(default=0, ge=-0.5, le=0.5)
    max_speed: float = Field(default=0.18, ge=0.02, le=0.5)
    max_turn: float = Field(default=1.2, ge=0.1, le=2)
    resolution: float = Field(default=0.025, ge=0.015, le=0.1)
    sensor_height: float = Field(default=0.12, ge=0.02, le=2)
    target_side: Literal["left", "right", "all"] = "left"
    tof_model: Literal["unconfirmed", "VL53L0X", "VL53L1X"] = "unconfirmed"
    verified: bool = False
    sensors: list[SensorConfig] = Field(default_factory=lambda: [
        SensorConfig(id="front", x=0.10, yaw=0),
        SensorConfig(id="left", y=0.075, yaw=math.pi / 2),
        SensorConfig(id="right", y=-0.075, yaw=-math.pi / 2),
    ])

    @model_validator(mode="after")
    def exactly_three(self):
        if sorted(s.id for s in self.sensors) != ["front", "left", "right"]:
            raise ValueError("Exactly one front, left, and right sensor is required")
        return self


class RangeSample(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    sensor: Literal["front", "left", "right"]
    t: float = Field(ge=0)
    distance: float | None = Field(default=None, ge=0, le=10)
    valid: bool = True
    status: str = Field(default="valid", max_length=80)
    signal: float | None = None
    ambient: float | None = None


class Telemetry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    type: Literal["telemetry"] = "telemetry"
    seq: int = Field(ge=0)
    t: float = Field(ge=0)
    left: int
    right: int
    gyro_z: float = Field(ge=-20, le=20)
    ranges: list[RangeSample] = Field(default_factory=list, max_length=12)
    armed: bool = False
    mapping: Literal["idle", "mapping", "paused", "finished"] = "idle"
    stop_latched: bool = False
    physical_stop: bool = False
    ack: int = -1
    motor_enabled: bool = False


class Closure(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float = Field(default=0, ge=-20, le=20)
    y: float = Field(default=0, ge=-20, le=20)
    yaw: float = Field(default=0, ge=-math.pi, le=math.pi)
    position_sigma: float = Field(default=0.03, ge=0.005, le=1)
    yaw_sigma: float = Field(default=math.radians(3), ge=0.005, le=0.5)
    confirmed: bool = False
    note: str = Field(default="", max_length=500)
