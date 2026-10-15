import math
import numpy as np
import pytest
from mapper.estimation import Estimator, interpolate_pose
from mapper.models import Profile


def test_stationary_kalman_filter_identifies_bias_and_preserves_psd():
    e=Estimator(Profile())
    for i in range(300):
        e.update(i*.01,0,0,.025)
    assert abs(e.bias-.025)<.002
    assert np.linalg.norm(e.pose[:2])==0
    assert np.linalg.eigvalsh(e.cov).min()>-1e-12
    assert np.allclose(e.cov,e.cov.T)
    assert e.cov.shape==(4,4)


def test_fused_turn_is_better_than_slipping_wheel_heading():
    p=Profile()
    e=Estimator(p)
    for i in range(300):
        e.update(i*.01,0,0,.02)
    mpc=math.pi*p.wheel_diameter/p.counts_per_revolution
    left=right=0.
    for i in range(1,401):
        # Actual yaw rate .2; encoder-only turn has a persistent 15% excess.
        dl=(.12-.23*p.wheel_base/2)*.025
        dr=(.12+.23*p.wheel_base/2)*.025
        left+=dl/mpc;right+=dr/mpc
        e.update(2.99+i*.025,round(left),round(right),.22)
    assert abs(e.pose[2]-2.)<abs(e.odom[2]-2.)
    assert abs(e.pose[2]-2.)<.16


def test_count_reset_and_long_gap_are_rejected():
    e=Estimator(Profile())
    e.update(0,10000,10000,0)
    with pytest.raises(ValueError,match="discontinuity"):
        e.update(.05,0,0,0)
    with pytest.raises(ValueError):
        e.update(2,10000,10000,0)


def test_wrapped_heading_interpolation_uses_short_arc():
    p=interpolate_pose([0,0,math.radians(179)],[2,4,math.radians(-179)],.5)
    assert p[:2]==[1,2]
    assert abs(abs(p[2])-math.pi)<1e-6
