import numpy as np
from mapper.mapping import Grid
from mapper.models import Profile, RangeSample
from mapper.service import MapperService
from mapper.simulation import Simulator


def test_invalid_return_does_not_clear_unknown_space():
    g=Grid(Profile())
    result=g.integrate(RangeSample(sensor="left",t=1,distance=None,valid=False,status="weak signal"),[0,0,0],1)
    assert not result["accepted"]
    assert not np.any(g.seen)
    assert g.rejected==1


def test_extrinsics_rotate_with_robot_and_band_has_multiple_cells():
    g=Grid(Profile(target_side="all"))
    result=g.integrate(RangeSample(sensor="front",t=1,distance=1),[2,3,np.pi/2],1)
    assert abs(result["origin"][0]-2)<1e-6
    assert abs(result["origin"][1]-3.1)<1e-6
    assert abs(result["endpoint"][1]-4.1)<1e-6
    assert result["cells"]>3
    assert g.accepted==1


def test_background_sensor_does_not_become_target_boundary():
    g=Grid(Profile(target_side="left"))
    for i in range(12):
        g.integrate(RangeSample(sensor="right",t=i,distance=.5),[0,0,0],i)
    assert np.any(g.seen)
    assert not g.boundary()


def test_pgm_preserves_uncertain_space_until_repeated_evidence():
    g=Grid(Profile())
    sample=RangeSample(sensor="front",t=1,distance=1)
    g.integrate(sample,[0,0,0],1)
    def exported_at(x,y):
        pixels=np.frombuffer(g.pgm().split(b"\n",3)[3],dtype=np.uint8).reshape(g.n,g.n)
        row,column=g.cell(x,y)
        return pixels[g.n-1-row,column]
    assert exported_at(.5,0)==205  # One weak free-space observation is uncertain.
    for i in range(30):
        g.integrate(sample,[0,0,0],i+2)
    assert exported_at(.5,0)==254
    assert exported_at(1.1,0)==0
    assert exported_at(0,2)==205  # Unobserved space remains unknown.


def test_replay_is_deterministic_from_raw_measurements():
    p=Profile()
    sim=Simulator(p)
    samples=[]
    for _ in range(120):
        frame=sim.step(.05,.1,.1,True,"mapping",False,0)
        samples.append(dict(frame=frame.model_dump(),integrate=True))
    a=MapperService._rebuild_replay(p,samples)
    b=MapperService._rebuild_replay(p,samples)
    assert np.array_equal(a[1].log_odds,b[1].log_odds)
    assert a[2]==b[2]
    assert a[1].accepted>0
