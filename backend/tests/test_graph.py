import math
import numpy as np
import pytest
from mapper.graph import optimize_path
from mapper.models import Closure


def test_graph_reduces_documented_endpoint_error_without_moving_origin():
    path=[]
    for i in range(100):
        a=2*math.pi*i/99
        path.append([i*.1,math.sin(a)+.3*i/99,1-math.cos(a),a if a<math.pi else a-2*math.pi])
    corrected,result=optimize_path(path,Closure(confirmed=True,note="Measured test fixture"))
    assert result["endpoint_after"]<result["endpoint_before"]*.3
    assert np.allclose(corrected[0],path[0])
    assert len(corrected)==len(path)


def test_optimizer_refuses_unverified_or_undocumented_closure():
    path=[[i,0,0,0] for i in range(20)]
    with pytest.raises(ValueError,match="reference"):
        optimize_path(path,Closure())
    with pytest.raises(ValueError,match="reference"):
        optimize_path(path,Closure(confirmed=True))
