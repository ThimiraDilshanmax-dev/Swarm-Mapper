"""SE(2) keyframe graph with an explicitly supplied surveyed endpoint."""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from .estimation import wrap, interpolate_pose
from .models import Closure


def optimize_path(path: list[list[float]], closure: Closure) -> tuple[list[list[float]], dict]:
    if not closure.confirmed or not closure.note.strip():
        raise ValueError("A confirmed, documented physical endpoint reference is required")
    if len(path) < 10:
        raise ValueError("Record a longer trajectory before optimizing")
    original = np.asarray([p[1:4] for p in path], dtype=float)
    indices = sorted(set([0, len(path) - 1] + list(range(0, len(path), max(1, len(path) // 160)))))
    poses = original[indices]
    n = len(poses)
    relative = []
    sigmas = []
    for a, b in zip(poses[:-1], poses[1:]):
        dx, dy = b[:2] - a[:2]
        c, s = math.cos(a[2]), math.sin(a[2])
        relative.append([c * dx + s * dy, -s * dx + c * dy, wrap(b[2] - a[2])])
        distance = math.hypot(dx, dy)
        sigmas.append([0.01 + 0.04 * distance, 0.01 + 0.04 * distance, 0.012 + 0.04 * distance])
    relative, sigmas = np.asarray(relative), np.asarray(sigmas)
    endpoint = np.array([closure.x, closure.y, closure.yaw])

    def residual(flat):
        p = np.vstack([poses[0], flat.reshape(-1, 3)])
        result = []
        for i, (a, b) in enumerate(zip(p[:-1], p[1:])):
            dx, dy = b[:2] - a[:2]
            c, s = math.cos(a[2]), math.sin(a[2])
            actual = np.array([c * dx + s * dy, -s * dx + c * dy, wrap(b[2] - a[2])])
            r = actual - relative[i]
            r[2] = wrap(float(r[2]))
            result.extend(r / sigmas[i])
        end = p[-1] - endpoint
        end[2] = wrap(float(end[2]))
        result.extend(end / [closure.position_sigma, closure.position_sigma, closure.yaw_sigma])
        return np.asarray(result)

    sparse = lil_matrix((3 * (n - 1) + 3, 3 * (n - 1)), dtype=int)
    for i in range(n - 1):
        if i:
            sparse[3*i:3*i+3, 3*(i-1):3*i] = 1
        sparse[3*i:3*i+3, 3*i:3*i+3] = 1
    sparse[-3:, -3:] = 1
    solved = least_squares(residual, poses[1:].ravel(), jac_sparsity=sparse.tocsr(),
                           loss="soft_l1", f_scale=2, max_nfev=120)
    if not solved.success and not solved.optimality < 0.05:
        raise ValueError("Optimizer did not converge; original map retained")
    corrected_keys = np.vstack([poses[0], solved.x.reshape(-1, 3)])
    # Interpolate the correction transform, preserving high-frequency local motion.
    output = []
    segment = 0
    corrections = []
    for a, b in zip(poses, corrected_keys):
        angle = wrap(float(b[2] - a[2]))
        c, s = math.cos(angle), math.sin(angle)
        corrections.append([b[0] - c*a[0] + s*a[1], b[1] - s*a[0] - c*a[1], angle])
    for i, row in enumerate(path):
        while segment < len(indices) - 2 and i > indices[segment + 1]:
            segment += 1
        f = (i - indices[segment]) / max(1, indices[segment + 1] - indices[segment])
        tx, ty, angle = interpolate_pose(corrections[segment], corrections[segment + 1], f)
        c, s = math.cos(angle), math.sin(angle)
        output.append([row[0], c*row[1] - s*row[2] + tx, s*row[1] + c*row[2] + ty, wrap(row[3] + angle)])
    before = float(np.linalg.norm(original[-1, :2] - endpoint[:2]))
    after = float(np.linalg.norm(np.asarray(output[-1][1:3]) - endpoint[:2]))
    return output, dict(keyframes=n, cost=float(solved.cost), endpoint_before=before,
                        endpoint_after=after, source="surveyed endpoint", reference=closure.model_dump())
