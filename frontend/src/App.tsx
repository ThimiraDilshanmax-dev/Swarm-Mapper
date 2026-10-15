import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowDown, ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUp, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, CircuitBoard, Clock3, Compass, Crosshair, Expand, FlaskConical, Focus, FolderOpen, Gauge, Info, Layers3, LoaderCircle, Map, Maximize2, MousePointer2, Network, Pause, Play, Radio, Route, Settings2, ShieldCheck, SkipBack, SkipForward, SlidersHorizontal, Square, Target, Terminal, Wifi, X, Zap } from 'lucide-react';
import MapCanvas from './MapCanvas';
import { api, duration } from './api';
import { Calibration, Connection, Modal, Optimization, Sessions, type Action } from './Panels';
import type { Layers, Profile, Reading, State, View } from './types';

const nav:[View,string,typeof Map][]=[['live','Live workspace',Map],['sessions','Session library',FolderOpen],['compare','Compare & refine',Layers3],['calibration','Calibration',SlidersHorizontal]];
const titles:Record<View,[string,string]>={live:['Mapping workspace','Every measurement, a clearer picture.'],sessions:['Your experiments','Recorded locally. Ready to reproduce.'],compare:['Compare & refine','Understand the estimate behind your map.'],calibration:['Robot calibration','Good maps begin with measured hardware.']};
const round=(n:number,d=2)=>Number.isFinite(n)?n.toFixed(d):'—';

export default function App(){
  const [state,setState]=useState<State|null>(null);
  const [view,setView]=useState<View>('live');
  const [online,setOnline]=useState(false);
  const [needsLogin,setNeedsLogin]=useState(false);
  const [loginToken,setLoginToken]=useState('');
  const [error,setError]=useState('');
  const [modal,setModal]=useState<'connect'|'new'|'optimize'|'help'|null>(null);
  const [name,setName]=useState('');
  const [selected,setSelected]=useState<Reading|null>(null);
  const [layers,setLayers]=useState<Layers>({occupancy:true,boundary:true,path:true,odometry:false,rays:true,reference:true});
  const [layerMenu,setLayerMenu]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const [speed,setSpeed]=useState(.12);
  const [seekValue,setSeekValue]=useState(0);
  const [annotation,setAnnotation]=useState('');
  const ws=useRef<WebSocket|null>(null),cid=useRef(''),current=useRef<State|null>(null);
  const keys=useRef(new Set<string>()),speedRef=useRef(speed);
  const [held,setHeld]=useState<string[]>([]);
  const [connectionKey,setConnectionKey]=useState(0);
  const controlsEnabled=useRef(true);
  controlsEnabled.current=(view==='live'||view==='compare')&&!modal&&!state?.working;
  const release=useCallback(()=>{
    keys.current.clear();setHeld([]);
    if(ws.current?.readyState===WebSocket.OPEN)ws.current.send(JSON.stringify({type:'drive',v:0,omega:0}));
  },[]);
  useEffect(()=>{speedRef.current=speed;},[speed]);
  useEffect(()=>{setAnnotation(state?.replay?.note||'');},[state?.replay?.id]);
  useEffect(()=>{setSelected(null);},[state?.session_id,state?.replay?.id,state?.optimization?.cost]);
  useEffect(()=>{if(!state?.armed)release();},[state?.armed,release]);
  useEffect(()=>{if(selected&&!state?.readings.some(r=>r.id===selected.id))setSelected(null);},[state?.readings,selected]);
  useEffect(()=>{
    if(!modal&&(view==='live'||view==='compare'))return;
    release();const s=current.current;
    if(s?.armed&&s.owner===cid.current&&!s.demo&&ws.current?.readyState===WebSocket.OPEN)ws.current.send(JSON.stringify({type:'stop'}));
  },[modal,view,release]);
  useEffect(()=>{if(!expanded)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';const esc=(e:KeyboardEvent)=>{if(e.key==='Escape')setExpanded(false);};window.addEventListener('keydown',esc);return()=>{document.body.style.overflow=previous;window.removeEventListener('keydown',esc);};},[expanded]);
  useEffect(()=>{if(state)setSpeed(v=>Math.min(v,state.profile.max_speed));},[state?.profile.max_speed]);
  useEffect(()=>{current.current=state;if(state?.replay)setSeekValue(state.replay.cursor);},[state]);
  useEffect(()=>{if(!error)return;const timer=setTimeout(()=>setError(''),9000);return()=>clearTimeout(timer);},[error]);
  useEffect(()=>{
    let stopped=false,retry:ReturnType<typeof setTimeout>|undefined;
    const connect=async()=>{
      try{
        await api('/bootstrap');if(stopped)return;setNeedsLogin(false);
        const initial=await api<State>('/state');if(stopped)return;setState(initial);
        const socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/ui');
        ws.current=socket;
        socket.onopen=()=>{if(!stopped)setOnline(true);};
        socket.onmessage=e=>{try{const message=JSON.parse(e.data);if(message.type==='welcome')cid.current=message.client_id;else if(message.type==='state'&&!stopped)setState(message);}catch{setError('Could not decode an update from the local engine.');}};
        socket.onerror=()=>{if(!stopped)setOnline(false);};
        socket.onclose=()=>{if(ws.current===socket){cid.current='';keys.current.clear();}if(!stopped){setHeld([]);setOnline(false);retry=setTimeout(connect,1500);}};
      }catch(e){if(stopped)return;setNeedsLogin(true);setError((e as Error).message);retry=setTimeout(connect,4000);}
    };
    void connect();
    return()=>{stopped=true;if(retry)clearTimeout(retry);ws.current?.close();};
  },[connectionKey]);
  useEffect(()=>{
    const movement=['arrowup','arrowdown','arrowleft','arrowright','w','a','s','d'];
    const down=(e:KeyboardEvent)=>{
      const tag=(e.target as HTMLElement)?.tagName;
      if(['INPUT','TEXTAREA','SELECT'].includes(tag)||(e.target as HTMLElement)?.isContentEditable)return;
      if(e.code==='Space'){e.preventDefault();release();if(ws.current?.readyState===WebSocket.OPEN)ws.current.send(JSON.stringify({type:'stop'}));return;}
      if(movement.includes(e.key.toLowerCase())&&controlsEnabled.current&&current.current?.armed&&current.current.owner===cid.current&&!current.current.replay){e.preventDefault();keys.current.add(e.key.toLowerCase());setHeld([...keys.current]);}
    };
    const up=(e:KeyboardEvent)=>{if(movement.includes(e.key.toLowerCase())){keys.current.delete(e.key.toLowerCase());setHeld([...keys.current]);}};
    const blur=()=>{release();const s=current.current;if(s?.armed&&s.owner===cid.current&&!(s.source==='simulator'&&s.demo)&&ws.current?.readyState===WebSocket.OPEN)ws.current.send(JSON.stringify({type:'stop'}));};
    const visibility=()=>{if(document.hidden)blur();};
    window.addEventListener('keydown',down);window.addEventListener('keyup',up);window.addEventListener('blur',blur);document.addEventListener('visibilitychange',visibility);
    const timer=setInterval(()=>{
      const s=current.current;if(!s?.armed||s.owner!==cid.current||s.replay||document.hidden||ws.current?.readyState!==WebSocket.OPEN)return;
      const k=keys.current;
      const v=controlsEnabled.current?((k.has('arrowup')||k.has('w')?1:0)-(k.has('arrowdown')||k.has('s')?1:0))*speedRef.current:0;
      const omega=controlsEnabled.current?((k.has('arrowleft')||k.has('a')?1:0)-(k.has('arrowright')||k.has('d')?1:0))*Math.min(.85,s.profile.max_turn):0;
      ws.current.send(JSON.stringify({type:'drive',v,omega}));
    },50);
    return()=>{clearInterval(timer);window.removeEventListener('keydown',down);window.removeEventListener('keyup',up);window.removeEventListener('blur',blur);document.removeEventListener('visibilitychange',visibility);release();};
  },[release]);
  const action:Action=useCallback(async(kind,data={})=>{
    if(['stop','estop','pause','finish','source','replay','live','profile','optimize'].includes(kind))release();
    try{await api('/action',{action:kind,client_id:cid.current,...data});return true;}
    catch(e){setError((e as Error).message);return false;}
  },[release]);
  const go=(target:View)=>{release();setView(target);setSelected(null);if(target==='compare')setLayers(l=>({...l,odometry:true}));};
  const driveButton=(key:string,Icon:typeof ArrowUp,label:string)=><button aria-label={label} title={label} disabled={!state?.armed||state.owner!==cid.current||!!state.replay||state.working} className={'drive-key '+(held.includes(key)?'pressed':'')}
    onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);keys.current.add(key);setHeld([...keys.current]);}}
    onPointerUp={()=>release()} onPointerCancel={()=>release()} onLostPointerCapture={()=>release()}><Icon size={19}/></button>;

  if(needsLogin&&!state)return <div className="startup"><div className="brand-mark"><Focus size={26}/></div><h1>Welcome to Contour</h1><p>Enter the operator token from the server’s .local/operator-token file.</p><form onSubmit={async e=>{e.preventDefault();try{await api('/login',{token:loginToken});setConnectionKey(k=>k+1);}catch(e){setError((e as Error).message);}}}><input type="password" aria-label="Operator token" value={loginToken} onChange={e=>setLoginToken(e.target.value)} required/><button className="button primary">Open workspace<ArrowRight size={16}/></button></form>{error&&<small>{error}</small>}</div>;
  if(!state)return <div className="startup"><div className="brand-mark"><Focus size={26}/></div><h1>Contour</h1><p>Connecting to your local research engine…</p><LoaderCircle className="spin"/>{error&&<small>{error}</small>}</div>;
  const active=state.mapping==='mapping'||state.mapping==='paused';
  const sessionId=state.replay?.id||state.session_id;
  const uncertainty=100*Math.sqrt(Math.max(state.covariance[0],state.covariance[1]));
  const latest=selected||[...state.readings].reverse().find(r=>r.accepted)||state.readings.at(-1);
  const showMap=view==='live'||view==='compare';
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>{e.preventDefault();go('live');}}><div className="brand-mark"><Focus size={23}/></div><span>contour<span className="brand-dot">.</span></span></a>
      <div className="workspace-switch"><span className="workspace-avatar">R</span><div><strong>Robotics lab</strong><small>Local workspace</small></div><ChevronDown size={15}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{nav.map(([id,label,Icon])=><button key={id} aria-label={label} title={label} aria-current={view===id?'page':undefined} className={'nav-item '+(view===id?'active':'')} onClick={()=>go(id)}><Icon size={18}/><span>{label}</span>{view===id&&<span className="nav-active-dot"/>}</button>)}</nav>
      <div className="sidebar-divider"/>
      <div className="nav-label">RESOURCES</div>
      <button className="nav-item" aria-label="Hardware connection" title="Hardware connection" onClick={()=>setModal('connect')}><Radio size={18}/><span>Hardware connection</span></button>
      <button className="nav-item" aria-label="Quick guide" title="Quick guide" onClick={()=>setModal('help')}><CircleHelp size={18}/><span>Quick guide</span></button>
      <a className="nav-item" aria-label="Research API" title="Research API" href="/docs" target="_blank" rel="noreferrer"><Terminal size={18}/><span>Research API</span><ArrowRight size={13}/></a>
      <div className="sidebar-bottom">
        <div className="robot-card"><div className="robot-card-top"><span className="robot-icon"><CircuitBoard size={20}/></span><span className={'tiny-dot '+(state.connected?'green':'amber')}/></div><strong>Master robot <span>01</span></strong><p>{state.source==='simulator'?'Synthetic sensor environment':state.connected?'ESP32-S3 connected':'Waiting for ESP32-S3'}</p><button onClick={()=>setModal('connect')}>{state.source==='simulator'?'Connect hardware':'Connection settings'}<ArrowRight size={14}/></button></div>
        <div className="sidebar-version"><span className="tiny-dot green"/>Local engine <span>v0.1.0</span></div>
      </div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Workspace<ChevronRight size={13}/><span>Master robot</span></div><div className="topbar-right"><span className={'engine-status '+(!online?'offline':'')}><span className={'tiny-dot '+(online?'green':'amber')}/>{online?'Engine online':'Reconnecting…'}</span><span className="topbar-separator"/><button className="icon-button" aria-label="Open quick guide" onClick={()=>setModal('help')}><CircleHelp size={19}/></button><div className="user-avatar">RL</div></div></header>
      <main>
        {error&&<div className="toast" role="alert"><Info size={18}/><span>{error}</span><button className="icon-button" aria-label="Dismiss message" onClick={()=>setError('')}><X size={17}/></button></div>}
        <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>{state.replay?'RECORDED EXPERIMENT':'ROBOTICS RESEARCH CONSOLE'}</div><h1>{state.replay&&showMap?'Replay laboratory':titles[view][0]}</h1><p>{state.replay&&showMap?state.session_name+' · original measurements, reconstructed locally.':titles[view][1]}</p></div>
          <div className="heading-actions"><button className="button" onClick={()=>setModal('connect')}><Wifi size={16}/>{state.source==='simulator'?'Simulation lab':'ESP32-S3'}<ChevronDown size={14}/></button>
            {showMap&&<button className="button" disabled={!sessionId} onClick={()=>{if(sessionId)window.location.href='/api/export/'+sessionId+'/zip';}}><ArrowDownToLine size={16}/>Export survey</button>}
          </div>
        </div>
        {showMap&&<>
          <div className="stats-grid">
            <Stat icon={Route} label="DISTANCE TRAVELLED" value={round(state.summary.distance)} unit="m" detail={state.replay?'Recorded trajectory':'Encoder–IMU estimate'} colour="purple"/>
            <Stat icon={Radio} label="ACCEPTED READINGS" value={state.grid.accepted.toLocaleString()} detail={state.grid.rejected.toLocaleString()+' rejected · all sensors'} colour="teal"/>
            <Stat icon={Crosshair} label="POSITION UNCERTAINTY" value={'± '+round(uncertainty,1)} unit="cm" detail="Estimated 1σ · Kalman covariance" colour="blue"/>
            <Stat icon={Clock3} label="SESSION TIME" value={duration(state.summary.duration)} detail={state.replay?'Recorded acquisition time':state.demo?'Sample survey · 4× time':active?'Recording original measurements':'Ready when you are'} colour="amber"/>
          </div>
          <div className="workspace-toolbar"><div className="mode-group"><span className={'live-indicator '+(state.replay?'replay':'')}><span className="tiny-dot"/>{state.replay?'REPLAY':'LIVE'}</span><span className="toolbar-divider"/><span className="session-label">{state.session_id||state.replay?state.session_name:'New mapping session'}</span><span className={'badge '+(state.mapping==='mapping'?'mint':'neutral')}>{state.replay?'Read-only':state.mapping==='mapping'?'Mapping':state.mapping==='paused'?'Paused':state.mapping==='finished'?'Saved':'Ready'}</span></div>
            <div className="toolbar-actions">{state.replay?<button className="button small" onClick={()=>action('live')}><Radio size={14}/>Return to live</button>:active?<><button className="button small" onClick={()=>action(state.mapping==='mapping'?'pause':'resume')}>{state.mapping==='mapping'?<Pause size={14}/>:<Play size={14}/>} {state.mapping==='mapping'?'Pause':'Resume'}</button><button className="button small dark" onClick={()=>action('finish')}><Square size={12}/>Finish survey</button></>:<><button className="button small" disabled={state.source!=='simulator'||!online} onClick={()=>{setSelected(null);action('demo',{name:'Sample · irregular object'});}}><FlaskConical size={14}/>Run sample survey</button><button className="button small primary" disabled={!state.connected||!online} onClick={()=>{setName('Survey '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));setModal('new');}}><Play size={14}/>Start mapping</button></>}</div>
          </div>
          {state.source==='simulator'&&!state.replay&&<div className="simulation-caption"><FlaskConical size={13}/><span>SIMULATION</span> Synthetic sensor readings pass through the same Kalman filter and mapping pipeline as hardware.</div>}
          {state.pending_ack&&<div className="notice amber compact"><LoaderCircle size={16} className="spin"/><p>Waiting for the robot to acknowledge its requested state.</p></div>}
          {state.grid.clipped&&<div className="notice amber compact"><Info size={16}/><p>The survey reached the 16 m map extent. Export this segment and reset the origin for another survey.</p></div>}
          {state.needs_segment&&<div className="notice amber compact" role="status"><Info size={16}/><p>Pose continuity was lost. Finish this survey, check the robot, and start a new session segment.</p></div>}
          <div className="mapping-layout">
            <div className="map-column">
              {expanded&&<div className="map-curtain" onClick={()=>setExpanded(false)}/>}
              <section className={'panel map-panel'+(expanded?' map-expanded':'')}><div className="map-heading"><div><h2><Map size={17}/>Object map</h2><span>2D occupancy & supported boundary</span></div><div className="map-heading-tools"><span className="badge neutral">EKF fusion</span><div className="layer-dropdown"><button className={'button small '+(layerMenu?'selected':'')} onClick={()=>setLayerMenu(!layerMenu)}><Layers3 size={15}/>Layers<ChevronDown size={13}/></button>{layerMenu&&<div className="layer-menu">{(Object.keys(layers) as (keyof Layers)[]).map(key=><label key={key}><input type="checkbox" checked={layers[key]} onChange={e=>setLayers(l=>({...l,[key]:e.target.checked}))}/>{({occupancy:'Occupancy evidence',boundary:'Supported boundary',path:'EKF trajectory',odometry:'Encoder-only trajectory',rays:'Recent sensor footprints',reference:'Simulation reference'})[key]}</label>)}</div>}</div><button className="icon-button" aria-label={expanded?'Exit expanded map':'Expand map'} title={expanded?'Exit · Escape':'Expand map'} onClick={()=>setExpanded(!expanded)}>{expanded?<X size={16}/>:<Maximize2 size={16}/>}</button></div></div>
                <MapCanvas state={state} layers={layers} selected={selected} onSelect={setSelected}/>
                {state.replay&&<div className="replay-calibration"><span>{state.replay.override?'Current calibration override':'Recorded calibration'} · read-only replay</span><select className="replay-speed" aria-label="Replay speed" value={state.replay.speed} onChange={e=>action('replay_speed',{speed:+e.target.value})}>{[.5,1,2,4].map(v=><option key={v} value={v}>{v}×</option>)}</select><button className="button small" disabled={state.working} onClick={async()=>{try{const profile=await api<Profile>('/profile');await action('replay',{id:state.replay!.id,profile});}catch(e){setError((e as Error).message);}}}><RefreshIcon/>Rebuild with current profile</button></div>}
                <div className="map-reading-picker"><label htmlFor="measurement-picker">Inspect a measurement</label><select id="measurement-picker" value={selected?.id||''} onChange={e=>setSelected(state.readings.find(r=>r.id===+e.target.value)||null)}><option value="">Follow latest accepted return</option>{[...state.readings].reverse().map(r=><option key={r.id} value={r.id}>{'#'+r.id+' · '+r.sensor+' · '+(r.distance===null?'no range':round(r.distance,3)+' m')+' · '+r.reason}</option>)}</select></div>
                <div className="map-legend"><span><i className="legend-line purple"/>EKF trajectory</span><span><i className="legend-square"/>Occupied evidence</span><span><i className="legend-dot"/>Supported boundary</span><span className="legend-hint"><MousePointer2 size={12}/>Drag to pan · scroll to zoom</span></div>
                <div className="pose-strip"><span><span className="pose-label">X</span>{round(state.pose[0],3)}<small>m</small></span><span><span className="pose-label">Y</span>{round(state.pose[1],3)}<small>m</small></span><span><Compass size={13}/>{round(state.pose[2]*180/Math.PI,1)}<small>°</small></span><span className="pose-strip-end"><span className={'tiny-dot '+state.led}/> {state.led==='cyan'?'Mapping active':state.stop_latched?'Stop latched':state.connected?'Source connected':'Disconnected'}</span></div>
              </section>
              {state.replay?<section className="panel replay-panel"><div className="replay-controls"><button className="icon-button" aria-label="Previous frame" onClick={()=>action('seek',{index:Math.max(0,state.replay!.cursor-1)})}><SkipBack size={17}/></button><button className="play-button" aria-label={state.replay.playing?'Pause replay':'Play replay'} disabled={state.working} onClick={()=>action('play')}>{state.replay.playing?<Pause size={17}/>:<Play size={17}/>}</button><button className="icon-button" aria-label="Next frame" onClick={()=>action('seek',{index:state.replay!.cursor+1})}><SkipForward size={17}/></button><input aria-label="Replay frame" type="range" min={0} max={state.replay.total} value={seekValue} disabled={state.working} onChange={e=>setSeekValue(+e.target.value)} onPointerUp={e=>action('seek',{index:+e.currentTarget.value})} onKeyUp={e=>action('seek',{index:+e.currentTarget.value})}/><span className="mono">{state.replay.cursor} / {state.replay.total}</span></div><small>Single-step the acquisition sequence. Motion output is disabled.</small></section>:<section className="panel activity-panel"><div className="section-label"><Activity size={15}/>SESSION ACTIVITY<span>{state.events.length} recent events</span></div><div className="activity-list">{state.events.slice(0,3).map((e,i)=><div className="activity-item" key={e.t+':'+i}><span className={'tiny-dot '+(e.kind==='fault'?'amber':e.kind==='stop'?'purple':'green')}/><p>{e.message}</p><time>{new Date(e.t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time></div>)}</div></section>}
              {view==='compare'&&<section className="panel comparison-panel"><div className="panel-heading"><div><h2>Estimation & correction</h2><p>Compare local fusion with a documented global reference.</p></div><span className="badge lavender">Research tools</span></div><div className="comparison-grid"><div><span className="field-caption">GYRO BIAS</span><strong className="mono">{round(state.gyro_bias,5)} <small>rad/s</small></strong><p>Estimated by the four-state EKF.</p></div><div><span className="field-caption">RATE DISAGREEMENT</span><strong className="mono">{round(state.disagreement,3)} <small>rad/s</small></strong><p>Wheel rotation versus corrected gyro.</p></div><div><span className="field-caption">BIAS UNCERTAINTY</span><strong className="mono">{round(Math.sqrt(state.kalman.bias_variance),5)} <small>rad/s</small></strong><p>Estimated standard deviation.</p></div></div>
                {state.optimization&&<div className="optimization-result"><CheckCircle2 size={19}/><div><strong>Surveyed-reference correction applied</strong><p>Endpoint residual {round(state.optimization.endpoint_before*100,1)} → {round(state.optimization.endpoint_after*100,1)} cm · {state.optimization.keyframes} keyframes. Original observations were reprojected.</p></div></div>}
                <div className="comparison-actions"><p>Three fixed sensors do not provide automatic reliable loop closure. A measured endpoint can constrain the graph.</p><button className="button primary" disabled={active||state.path.length<10||state.working} onClick={()=>setModal('optimize')}>{state.working?<LoaderCircle size={16} className="spin"/>:<Network size={16}/>}Surveyed correction</button></div></section>}
            </div>
            <aside className="right-column">
              <section className="panel sensor-panel"><div className="side-heading"><h2>Sensor readings</h2><span className="badge neutral">ToF × 3</span></div><div className="sensor-diagram" aria-hidden="true"><div className="sensor-beam front"/><div className="sensor-beam left"/><div className="sensor-beam right"/><div className="mini-robot"><CircuitBoard size={27}/></div><span className="sensor-label front">F</span><span className="sensor-label left">L</span><span className="sensor-label right">R</span></div>
                {(['front','left','right'] as const).map(id=>{const r=state.live_ranges.find(r=>r.sensor===id);const stale=!!r&&(state.range_time-r.t>.5||(!state.replay&&state.age>.5));const valid=r?.valid&&!stale;return <div className="sensor-row" key={id}><span className={'sensor-dot '+id}/><div><strong>{id[0].toUpperCase()+id.slice(1)}</strong><small>{stale?'Stale return':valid?'Valid return':'No reliable return'}</small></div><span className="sensor-value">{r&&valid&&r.distance!==null?round(r.distance,3):'—'}<small>m</small></span></div>;})}
                <div className="sensor-foot"><span className="tiny-dot purple"/>{state.measurement_source==='simulator'?'Synthetic ToF model':state.profile.tof_model} <span>·</span> {state.replay?'Recorded':state.age<.5?'Receiving':'Stale'}</div>
              </section>
              <section className="panel drive-panel"><div className="side-heading"><h2>Manual control</h2><span className={'badge '+(state.armed?'mint':'neutral')}>{state.replay?'Disabled':state.armed?'Armed':'Disarmed'}</span></div><p className="side-subtitle">Arrow keys or WASD. Release to stop.</p><div className="drive-pad"><span/>{driveButton('arrowup',ArrowUp,'Drive forward')}<span/>{driveButton('arrowleft',ArrowLeft,'Turn left')}<button className="drive-stop" aria-label="Stop motion" title="Stop motion · Space" onClick={()=>action('stop')}><Square size={12} fill="currentColor"/></button>{driveButton('arrowright',ArrowRight,'Turn right')}<span/>{driveButton('arrowdown',ArrowDown,'Drive backward')}<span/></div>
                <div className="speed-label"><span>Speed limit</span><strong className="mono">{round(speed,2)} <small>m/s</small></strong></div><input aria-label="Drive speed limit" type="range" min={.02} max={state.profile.max_speed} step={.01} value={Math.min(speed,state.profile.max_speed)} onChange={e=>setSpeed(+e.target.value)}/>
                <button className={'button full '+(state.armed?'':'primary')} disabled={!!state.replay||!online||!state.connected||state.stop_latched||!!state.working} onClick={()=>action(state.armed?'stop':'arm')}>{state.armed?<Square size={14}/>:<ShieldCheck size={15}/>} {state.armed?'Disarm drive':'Arm drive'}</button>
                <button className="emergency-button" onClick={()=>action(state.stop_latched?'clear_stop':'estop')}><span/> {state.stop_latched?'Clear latched stop':'Emergency stop'}</button><small className="drive-foot">Robot-side command watchdog remains active.</small>
              </section>
              <section className="panel reading-panel"><div className="side-heading"><h2>Reading inspector</h2><Target size={16}/></div>{latest?<><div className="reading-selected"><span className="badge lavender">#{latest.id}</span><strong>{latest.sensor[0].toUpperCase()+latest.sensor.slice(1)} sensor</strong><span className={'tiny-dot '+(latest.accepted?'green':'amber')}/></div><dl className="reading-details"><div><dt>Range</dt><dd>{latest.distance===null?'—':round(latest.distance,3)+' m'}</dd></div><div><dt>Acquired at</dt><dd>{round(latest.t,3)} s</dd></div><div><dt>Origin X / Y</dt><dd>{round(latest.origin[0])} / {round(latest.origin[1])} m</dd></div><div><dt>Updated cells</dt><dd>{latest.cells}</dd></div><div><dt>Decision</dt><dd className={latest.accepted?'teal-text':'amber-text'}>{latest.reason}</dd></div></dl><p className="inspector-note">Highlighted footprint shows angular uncertainty. Select another return on the map.</p>{selected&&<button className="text-button" onClick={()=>setSelected(null)}>Follow latest reading<ArrowRight size={12}/></button>}</>:<div className="inspector-empty"><MousePointer2 size={23}/><p>Start mapping, then select a return to see how it contributes.</p></div>}</section>
            </aside>
          </div>
          {state.replay&&<section className="panel annotation-panel"><div><h3>Experiment notes</h3><p>Document wheel slip, surface conditions, or the reference used.</p></div><textarea aria-label="Experiment notes" placeholder="Add a research note…" value={annotation} onChange={e=>setAnnotation(e.target.value)}/><button className="button" onClick={()=>action('annotate',{note:annotation})}>Save note</button></section>}
          <div className="workspace-foot"><span><ShieldCheck size={13}/>Measurements stay on this computer</span><span>Boundary detail is limited by field of view and pose uncertainty.</span></div>
        </>}
        {view==='sessions'&&<Sessions action={action} onOpen={()=>{setSelected(null);setView('live');}}/>}
        {view==='calibration'&&<Calibration state={state} action={action}/>}
      </main>
    </div>
    {modal==='connect'&&<Connection state={state} action={action} onClose={()=>setModal(null)}/>}
    {modal==='new'&&<Modal title="Start a mapping session" subtitle="Record the master robot’s measurements and build a live map." onClose={()=>setModal(null)}><form onSubmit={async e=>{e.preventDefault();if(await action('start',{name})){setModal(null);setSelected(null);}}}><label className="field">Session name<input autoFocus value={name} onChange={e=>setName(e.target.value)} required maxLength={100}/></label><div className="notice compact"><Info size={17}/><p>Starting a survey does not start the motors. Arm drive separately when you are ready.</p></div><footer><span>{state.source==='simulator'?'Synthetic sensor environment':'Physical master robot'}</span><button className="button primary"><Play size={15}/>Start session</button></footer></form></Modal>}
    {modal==='optimize'&&<Optimization state={state} action={action} onClose={()=>setModal(null)}/>}
    {modal==='help'&&<Modal title="A clearer view of your experiment" subtitle="Contour · local robotics research console" onClose={()=>setModal(null)}>
      <div className="guide-steps">{[[FlaskConical,'Explore the simulator','Run a sample survey to watch an irregular object emerge from synthetic measurements.'],[Radio,'Connect your robot','Configure firmware Wi-Fi and pairing, select ESP32-S3, and verify calibration before arming.'],[Compass,'Drive and inspect','Start a session. Arm drive, then hold arrow keys or WASD. Space stops motion; releasing keys requests zero speed.'],[Layers3,'Replay and compare','Finish a survey to save it. Open the library to step through measurements or compare EKF and encoder-only trajectories.']].map(([Icon,title,text])=>{const I=Icon as typeof Map;return <div className="guide-step" key={String(title)}><span className="option-icon"><I size={20}/></span><div><h3>{String(title)}</h3><p>{String(text)}</p></div></div>;})}</div>
      <div className="notice amber compact"><Info size={17}/><p>Fixed ToF sensors provide sparse observations. Small surface details and automatic loop closure are not guaranteed. The physical motor disconnect remains independent of this application.</p></div><footer><span>Full setup, wiring, and test instructions are in README.md.</span><button className="button primary" onClick={()=>setModal(null)}>Got it<CheckCircle2 size={15}/></button></footer>
    </Modal>}
    {state.working&&<div className="processing-indicator"><LoaderCircle size={16} className="spin"/>Rebuilding measurement history…</div>}
  </div>;
}

function Stat({icon:Icon,label,value,unit,detail,colour}:{icon:typeof Map;label:string;value:string;unit?:string;detail:string;colour:string}){
  return <section className="stat-card"><div className="stat-top"><span>{label}</span><span className={'stat-icon '+colour}><Icon size={17}/></span></div><div className="stat-value">{value}{unit&&<small>{unit}</small>}</div><div className="stat-detail"><span className={'tiny-dot '+colour}/>{detail}</div></section>;
}

function RefreshIcon(){return <Settings2 size={13}/>;}
