import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, Check, CheckCircle2, CircuitBoard, Clipboard, FileJson, FolderOpen, Info, LoaderCircle, Radio, RefreshCw, Save, ShieldCheck, Upload, Usb, X } from 'lucide-react';
import { api, download, duration } from './api';
import type { Profile, Session, State } from './types';
export type Action=(kind:string,data?:Record<string,unknown>)=>Promise<boolean>;

export function Modal({title,subtitle,onClose,children}:{title:string;subtitle?:string;onClose:()=>void;children:React.ReactNode}){
  const root=useRef<HTMLElement>(null),close=useRef(onClose);close.current=onClose;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const controls=()=>[...root.current!.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')].filter(el=>el.getClientRects().length>0);
    if(!root.current?.contains(document.activeElement))controls()[0]?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){e.preventDefault();close.current();}
      if(e.key==='Tab'){
        const items=controls(),index=items.indexOf(document.activeElement as HTMLElement);
        if(e.shiftKey&&(index<=0)){e.preventDefault();items.at(-1)?.focus();}
        else if(!e.shiftKey&&(index===items.length-1||index<0)){e.preventDefault();items[0]?.focus();}
      }
    };
    window.addEventListener('keydown',key);
    return()=>{window.removeEventListener('keydown',key);previous?.focus();};
  },[]);
  return <div className="modal-shade" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <section ref={root} className="modal" role="dialog" aria-modal="true" aria-label={title}><header><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={19}/></button></header>{children}</section>
  </div>;
}

export function Connection({state,action,onClose}:{state:State;action:Action;onClose:()=>void}){
  const [pairing,setPairing]=useState<{robot_token:string;addresses:string[];port:number}|null>(null);
  const [reveal,setReveal]=useState(false);const [copied,setCopied]=useState(false);
  const [failure,setFailure]=useState('');
  useEffect(()=>{api<typeof pairing>('/pairing').then(setPairing).catch(e=>setFailure(e.message));},[]);
  return <Modal title="Connect your master robot" subtitle="Keep the console and robot on the same local network." onClose={onClose}>
    <div className="connection-options">
      <button className={'connection-option '+(state.source==='simulator'?'selected':'')} onClick={async()=>{if(await action('source',{source:'simulator'}))onClose();}}>
        <span className="option-icon"><CircuitBoard size={23}/></span><div><strong>Simulation lab</strong><p>Try mapping with synthetic encoder, IMU, and ToF data.</p></div><ArrowRight size={18}/>
      </button>
      <button className={'connection-option '+(state.source==='robot'?'selected':'')} onClick={()=>action('source',{source:'robot'})}>
        <span className="option-icon teal"><Radio size={23}/></span><div><strong>ESP32-S3 master</strong><p>{state.source==='robot'?(state.connected?'Authenticated robot connected':'Waiting for firmware connection…'):'Connect the physical robot over Wi-Fi.'}</p></div><ArrowRight size={18}/>
      </button>
    </div>
    <div className="setup-box"><h3>Firmware pairing</h3><p>Select ESP32-S3 above, run the server in LAN mode, and enter these details in the firmware configuration.</p>
      <label>Computer LAN address<div className="code-value">{pairing?.addresses.filter(a=>!a.startsWith('127.')).join(' / ')||'Use your computer’s Wi-Fi IPv4 address'}</div></label>
      <label>WebSocket endpoint<div className="code-value">ws://&lt;computer-ip&gt;:{pairing?.port||8000}/ws/robot</div></label>
      <label>Robot pairing token<div className="token-line"><input aria-label="Robot pairing token" readOnly type={reveal?'text':'password'} value={pairing?.robot_token||''}/><button className="text-button" onClick={()=>setReveal(!reveal)}>{reveal?'Hide':'Show'}</button><button className="icon-button" aria-label="Copy robot token" onClick={()=>{if(pairing)navigator.clipboard.writeText(pairing.robot_token).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),2000);}).catch(()=>setFailure('Clipboard unavailable; show and copy the token manually.'));}}>{copied?<Check size={16}/>:<Clipboard size={16}/>}</button></div></label>
      {failure&&<p className="error-text">{failure}</p>}
      <div className="inline-note"><ShieldCheck size={16}/><span>Motion stays disabled until both firmware wiring verification and application calibration are complete.</span></div>
    </div>
    <footer><span><Usb size={15}/> USB is used for flashing and diagnostics.</span><button className="button primary" onClick={onClose}>Done</button></footer>
  </Modal>;
}

export function Sessions({action,onOpen}:{action:Action;onOpen:()=>void}){
  const [sessions,setSessions]=useState<Session[]>([]);
  const [loading,setLoading]=useState(true);const [error,setError]=useState('');
  const load=()=>{setLoading(true);setError('');api<Session[]>('/sessions').then(setSessions).catch(e=>setError(e.message)).finally(()=>setLoading(false));};
  useEffect(load,[]);
  return <section className="panel library-panel">
    <div className="panel-heading"><div><h2>Session library</h2><p>Original measurements, ready to inspect and reproduce.</p></div><button className="button" onClick={load}><RefreshCw size={15}/>Refresh</button></div>
    {loading?<div className="empty-state"><LoaderCircle className="spin"/><p>Reading your local library…</p></div>:!sessions.length?<div className="empty-state"><FolderOpen size={40}/><h3>Your research starts here</h3><p>Finish a survey to save its measurements and calibration.</p></div>:<div className="table-wrap"><table><thead><tr><th>Survey</th><th>Source</th><th>Duration</th><th>Frames</th><th>Status</th><th/></tr></thead><tbody>{sessions.map(s=><tr key={s.id}>
      <td><strong>{s.name}</strong><small>{new Date(s.created*1000).toLocaleString()}</small></td>
      <td><span className={'badge '+(s.source==='simulator'?'lavender':'mint')}>{s.source==='simulator'?'Simulated':'ESP32'}</span></td>
      <td className="mono">{duration(s.summary.duration||0)}</td><td className="mono">{s.samples.toLocaleString()}</td><td><span className="status-text">{s.status}</span></td>
      <td><div className="table-actions"><a className="icon-button" title="Download research bundle" aria-label={'Download '+s.name} href={'/api/export/'+s.id+'/zip'}><ArrowDownToLine size={16}/></a><button className="button small" onClick={async()=>{if(await action('replay',{id:s.id}))onOpen();}}>Open replay<ArrowRight size={14}/></button></div></td>
    </tr>)}</tbody></table></div>}
    {error&&<p className="error-text">{error}</p>}
    <div className="panel-foot"><Info size={14}/> Sessions stay on this computer. Exports include original samples, calibration, and map artifacts.</div>
  </section>;
}

function Field({label,value,onChange,suffix,step=1,min,max}:{label:string;value:number;onChange:(n:number)=>void;suffix?:string;step?:number;min?:number;max?:number}){
  return <label className="field">{label}<div className="number-field"><input type="number" required value={Number.isFinite(value)?value:''} step={step} min={min} max={max} onChange={e=>onChange(e.target.valueAsNumber)}/>{suffix&&<span>{suffix}</span>}</div></label>;
}
export function Calibration({state,action}:{state:State;action:Action}){
  const [p,setP]=useState<Profile>(()=>structuredClone(state.robot_profile));
  const [saved,setSaved]=useState(false);const [error,setError]=useState('');
  const change=(key:keyof Profile,value:unknown)=>{setSaved(false);setP(old=>({...old,[key]:value}));};
  const sensor=(i:number,key:string,value:number)=>{setSaved(false);setP(old=>({...old,sensors:old.sensors.map((s,j)=>j===i?{...s,[key]:value}:s)}));};
  return <form className="calibration-layout" onSubmit={async e=>{e.preventDefault();if(await action('profile',{profile:p})){setSaved(true);setError('');}}}>
    <div className="calibration-main">
      <div className="notice amber"><Info size={19}/><div><strong>Measure first. Map with confidence.</strong><p>Defaults are illustrative. Confirm your wheel geometry, encoder decoding, sensor chip, and mounting before arming hardware.</p></div></div>
      <section className="panel form-panel"><div className="panel-heading"><div><h2>Robot geometry</h2><p>Use the effective dimensions measured on your chassis.</p></div><CircuitBoard size={21}/></div>
        <div className="form-grid"><label className="field span-two">Profile name<input required value={p.name} maxLength={80} onChange={e=>change('name',e.target.value)}/></label>
          <Field label="Wheel diameter" value={p.wheel_diameter*1000} onChange={n=>change('wheel_diameter',n/1000)} suffix="mm" step={0.1} min={15} max={500}/>
          <Field label="Wheel separation" value={p.wheel_base*1000} onChange={n=>change('wheel_base',n/1000)} suffix="mm" step={0.1} min={50} max={1000}/>
          <Field label="Counts / wheel revolution" value={p.counts_per_revolution} onChange={n=>change('counts_per_revolution',n)} min={4} max={1000000}/>
          <Field label="Sensor mounting height" value={p.sensor_height*1000} onChange={n=>change('sensor_height',n/1000)} suffix="mm" min={20} max={2000}/>
          <Field label="Left distance multiplier" value={p.left_scale} onChange={n=>change('left_scale',n)} step={0.001} min={.5} max={1.5}/>
          <Field label="Right distance multiplier" value={p.right_scale} onChange={n=>change('right_scale',n)} step={0.001} min={.5} max={1.5}/>
        </div>
      </section>
      <section className="panel form-panel"><div className="panel-heading"><div><h2>Mapping & Kalman filter</h2><p>Planar encoder–gyroscope fusion with estimated gyro bias.</p></div><span className="badge lavender">EKF · 4 states</span></div>
        <div className="form-grid">
          <label className="field">ToF chip model<select value={p.tof_model} onChange={e=>{const model=e.target.value as Profile['tof_model'];setSaved(false);setP(old=>({...old,tof_model:model,sensors:old.sensors.map(s=>({...s,fov:(model==='VL53L0X'?25:15)*Math.PI/180}))}));}}><option value="unconfirmed">Unconfirmed — identify module</option><option>VL53L0X</option><option>VL53L1X</option></select></label>
          <label className="field">Target-facing sensors<select value={p.target_side} onChange={e=>change('target_side',e.target.value)}><option value="left">Object on left</option><option value="right">Object on right</option><option value="all">All sensors / surroundings</option></select></label>
          <Field label="Grid resolution" value={p.resolution*1000} onChange={n=>change('resolution',n/1000)} suffix="mm" min={15} max={100}/>
          <Field label="Initial gyro bias" value={p.gyro_bias} onChange={n=>change('gyro_bias',n)} suffix="rad/s" step={.0001} min={-.5} max={.5}/>
          <Field label="Maximum linear speed" value={p.max_speed} onChange={n=>change('max_speed',n)} suffix="m/s" step={.01} min={.02} max={.5}/>
          <Field label="Maximum turn rate" value={p.max_turn} onChange={n=>change('max_turn',n)} suffix="rad/s" step={.05} min={.1} max={2}/>
        </div>
      </section>
      <section className="panel form-panel"><div className="panel-heading"><div><h2>Sensor mounting</h2><p>Robot frame: X forward, Y left, positive yaw counterclockwise.</p></div></div>
        {p.sensors.map((s,i)=><div className="sensor-calibration" key={s.id}><h3><span className={'sensor-dot '+s.id}/>{s.id}</h3><div className="form-grid three">
          <Field label="X offset" value={s.x*1000} onChange={n=>sensor(i,'x',n/1000)} suffix="mm" min={-1000} max={1000}/>
          <Field label="Y offset" value={s.y*1000} onChange={n=>sensor(i,'y',n/1000)} suffix="mm" min={-1000} max={1000}/>
          <Field label="Mounting yaw" value={s.yaw*180/Math.PI} onChange={n=>sensor(i,'yaw',n*Math.PI/180)} suffix="°" step={.1}/>
          <Field label="Effective beam width" value={s.fov*180/Math.PI} onChange={n=>sensor(i,'fov',n*Math.PI/180)} suffix="°" step={.1} min={2} max={60}/>
          <Field label="Range offset correction" value={s.offset*1000} onChange={n=>sensor(i,'offset',n/1000)} suffix="mm" min={-200} max={200}/>
          <Field label="Minimum valid range" value={s.min_range} onChange={n=>sensor(i,'min_range',n)} suffix="m" step={.01} min={.01} max={1}/>
          <Field label="Maximum valid range" value={s.max_range} onChange={n=>sensor(i,'max_range',n)} suffix="m" step={.05} min={.1} max={4}/>
        </div></div>)}
      </section>
    </div>
    <aside className="calibration-aside"><section className="panel form-panel"><ShieldCheck className="purple-text" size={28}/><h3>Hardware verification</h3><p>Confirm counts per revolution include your gearbox and decoding convention. Also verify voltages and the firmware pin assignment.</p>
      <label className="check-row"><input type="checkbox" checked={p.verified} onChange={e=>change('verified',e.target.checked)}/><span>I verified these values against my physical robot.</span></label>
      <button className="button primary full" type="submit"><Save size={16}/>{saved?'Profile saved':'Save calibration'}</button>
      {saved&&<p className="success-text"><CheckCircle2 size={14}/>Saved. Drive remains disarmed.</p>}
      {error&&<p className="error-text">{error}</p>}
      <div className="divider"/><button type="button" className="button full" onClick={()=>download('contour-profile.json',p)}><FileJson size={16}/>Export profile</button>
      <label className="button full file-button"><Upload size={16}/>Import profile<input type="file" accept=".json" onChange={async e=>{const input=e.currentTarget;try{const file=input.files?.[0];if(file){const profile=await api<Profile>('/profile/validate',JSON.parse(await file.text()));setP(profile);setSaved(false);setError('');}}catch{setError('Invalid calibration profile. Check that all geometry and sensor values are present and within limits.');}finally{input.value='';}}}/></label>
    </section><div className="aside-tip"><Info size={17}/><p>Changing calibration requires a finished session. Original recordings preserve the profile used during acquisition.</p></div></aside>
  </form>;
}

export function Optimization({state,action,onClose}:{state:State;action:Action;onClose:()=>void}){
  const [confirmed,setConfirmed]=useState(false),[note,setNote]=useState('');
  const [x,setX]=useState(0),[y,setY]=useState(0),[yaw,setYaw]=useState(0);
  const [sigma,setSigma]=useState(.03);
  return <Modal title="Add a surveyed endpoint" subtitle="An independent reference constrains the pose graph." onClose={onClose}>
    <div className="notice amber compact"><Info size={18}/><p>Do not force the path closed just because it looks close. Enter a measured endpoint, or use zero only after physically returning to the same position and heading.</p></div>
    <form onSubmit={async e=>{e.preventDefault();if(await action('optimize',{closure:{x,y,yaw:yaw*Math.PI/180,position_sigma:sigma,yaw_sigma:Math.PI/60,confirmed,note}}))onClose();}}>
      <div className="form-grid three"><Field label="Endpoint X" value={x} onChange={setX} suffix="m" step={.01} min={-20} max={20}/><Field label="Endpoint Y" value={y} onChange={setY} suffix="m" step={.01} min={-20} max={20}/><Field label="Endpoint heading" value={yaw} onChange={setYaw} suffix="°" min={-180} max={180}/></div>
      <Field label="Position standard deviation" value={sigma} onChange={setSigma} suffix="m" step={.005} min={.005} max={1}/>
      <label className="field">Reference method<textarea required placeholder="Example: robot aligned in a measured starting fixture." value={note} onChange={e=>setNote(e.target.value)} maxLength={500}/></label>
      <label className="check-row"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/><span>I independently verified this endpoint and its heading.</span></label>
      <footer><span>{state.path.length.toLocaleString()} trajectory samples</span><button className="button primary" disabled={!confirmed||!note.trim()||state.working} type="submit">{state.working?<LoaderCircle className="spin" size={16}/>:<RefreshCw size={16}/>}Optimize & rebuild</button></footer>
    </form>
  </Modal>;
}
