import { useEffect, useRef, useState } from 'react';
import { Crosshair, Minus, Plus } from 'lucide-react';
import type { Layers, Reading, State } from './types';

const colours:Record<string,string>={front:'#8b5cf6',left:'#149b9a',right:'#e3a344'};
export default function MapCanvas({state,layers,selected,onSelect}:{state:State;layers:Layers;selected:Reading|null;onSelect:(r:Reading)=>void}) {
  const ref=useRef<HTMLCanvasElement>(null);
  const container=useRef<HTMLDivElement>(null);
  const [size,setSize]=useState({w:800,h:460});
  const [camera,setCamera]=useState({x:0,y:1.45,scale:109});
  const drag=useRef<{x:number;y:number;cx:number;cy:number;moved:boolean}|null>(null);
  useEffect(()=>{
    const observer=new ResizeObserver(entries=>{
      const r=entries[0].contentRect;setSize({w:r.width,h:r.height});
    });
    if(container.current)observer.observe(container.current);
    return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const canvas=ref.current;if(!canvas)return;
    const dpr=window.devicePixelRatio||1;
    canvas.width=size.w*dpr;canvas.height=size.h*dpr;
    const ctx=canvas.getContext('2d')!;ctx.scale(dpr,dpr);
    const {w,h}=size, scale=camera.scale;
    const xy=(x:number,y:number):[number,number]=>[w/2+(x-camera.x)*scale,h/2-(y-camera.y)*scale];
    ctx.fillStyle='#fafbfe';ctx.fillRect(0,0,w,h);
    const step=scale>160?0.25:0.5;
    const minX=camera.x-w/2/scale,maxX=camera.x+w/2/scale;
    const minY=camera.y-h/2/scale,maxY=camera.y+h/2/scale;
    ctx.lineWidth=1;ctx.strokeStyle='#e9edf4';
    for(let x=Math.floor(minX/step)*step;x<=maxX;x+=step){const [sx]=xy(x,0);ctx.beginPath();ctx.moveTo(sx,0);ctx.lineTo(sx,h);ctx.stroke();}
    for(let y=Math.floor(minY/step)*step;y<=maxY;y+=step){const [,sy]=xy(0,y);ctx.beginPath();ctx.moveTo(0,sy);ctx.lineTo(w,sy);ctx.stroke();}
    ctx.font='10px "Segoe UI",sans-serif';ctx.fillStyle='#a1a9ba';
    for(let x=Math.ceil(minX);x<=maxX;x++){const [sx]=xy(x,0);ctx.fillText(x+' m',sx+5,h-12);}
    for(let y=Math.ceil(minY);y<=maxY;y++){const [,sy]=xy(0,y);if(sy>25&&sy<h-35)ctx.fillText(y+' m',12,sy-5);}
    if(layers.reference&&state.reference){
      ctx.beginPath();state.reference.forEach((p,i)=>{const a=xy(p[0],p[1]);i?ctx.lineTo(...a):ctx.moveTo(...a);});
      ctx.closePath();ctx.fillStyle='#f0eee9';ctx.fill();ctx.strokeStyle='#c8c4ba';ctx.setLineDash([5,5]);ctx.stroke();ctx.setLineDash([]);
      const mid=state.reference.reduce((a,p)=>[a[0]+p[0]/state.reference!.length,a[1]+p[1]/state.reference!.length],[0,0]);
      const label=xy(mid[0],mid[1]);ctx.textAlign='center';ctx.fillStyle='#aaa69c';ctx.font='10px "Segoe UI",sans-serif';
      ctx.fillText('SIMULATION REFERENCE',label[0],label[1]);ctx.textAlign='left';
    }
    const g=state.grid;
    if(layers.occupancy){
      const cell=g.resolution*scale;
      for(let y=0;y<g.height;y++)for(let x=0;x<g.width;x++){
        const value=g.data[y*g.width+x];if(value<0)continue;
        if(value>61)ctx.fillStyle='rgba(71,78,102,'+Math.min(.68,(value-48)/70)+')';
        else if(value<45)ctx.fillStyle='rgba(100,156,174,0.075)';
        else continue;
        const p=xy(g.origin[0]+x*g.resolution,g.origin[1]+(y+1)*g.resolution);
        ctx.fillRect(p[0],p[1],cell+.3,cell+.3);
      }
    }
    if(layers.boundary){
      ctx.fillStyle='#6d5ce7';
      for(const p of g.boundary){const a=xy(p[0],p[1]);ctx.fillRect(a[0]-1.2,a[1]-1.2,2.4,2.4);}
    }
    const drawPath=(path:number[][],colour:string,dashed=false)=>{
      if(path.length<2)return;ctx.beginPath();ctx.lineWidth=2;ctx.strokeStyle=colour;ctx.setLineDash(dashed?[5,5]:[]);
      path.forEach((p,i)=>{const a=xy(p[1],p[2]);i?ctx.lineTo(...a):ctx.moveTo(...a);});ctx.stroke();ctx.setLineDash([]);
    };
    if(layers.odometry)drawPath(state.odom_path,'#d7a44b',true);
    if(state.original_path.length&&layers.path)drawPath(state.original_path,'#d386af',true);
    if(layers.path)drawPath(state.path,'#8c7bed');
    if(state.path.length&&layers.path){
      const a=xy(state.path[0][1],state.path[0][2]);ctx.beginPath();ctx.arc(...a,4,0,Math.PI*2);
      ctx.fillStyle='#fff';ctx.fill();ctx.strokeStyle='#8c7bed';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#9099ab';ctx.font='10px "Segoe UI",sans-serif';ctx.fillText('START',a[0]+10,a[1]+3);
    }
    const drawReading=(r:Pick<Reading,'origin'|'angle'|'fov'|'distance'|'accepted'|'sensor'>,highlight=false)=>{
      if(r.distance===null||!r.accepted)return;
      const a=xy(...r.origin),radius=r.distance*scale;
      ctx.beginPath();ctx.moveTo(...a);
      ctx.arc(...a,radius,-r.angle-r.fov/2,-r.angle+r.fov/2);
      ctx.closePath();ctx.fillStyle=highlight?'rgba(124,99,231,.20)':'rgba(124,99,231,.06)';ctx.fill();
      ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...xy(r.origin[0]+r.distance*Math.cos(r.angle),r.origin[1]+r.distance*Math.sin(r.angle)));
      ctx.strokeStyle=highlight?'#6d5ce7':colours[r.sensor]||'#999';ctx.lineWidth=highlight?2:1;ctx.setLineDash([3,4]);ctx.stroke();ctx.setLineDash([]);
      const end=xy(r.origin[0]+r.distance*Math.cos(r.angle),r.origin[1]+r.distance*Math.sin(r.angle));
      ctx.beginPath();ctx.arc(...end,highlight?5:3,0,Math.PI*2);ctx.fillStyle=colours[r.sensor]||'#999';ctx.fill();
    };
    if(layers.rays){
      const latest:Record<string,Reading>={};state.readings.forEach(r=>{latest[r.sensor]=r;});
      if(state.readings.length)Object.values(latest).forEach(r=>drawReading(r));
      else state.live_ranges.forEach(r=>{
        const sensor=state.profile.sensors.find(s=>s.id===r.sensor)!;const [x,y,t]=state.pose,c=Math.cos(t),s=Math.sin(t);
        drawReading({origin:[x+c*sensor.x-s*sensor.y,y+s*sensor.x+c*sensor.y],angle:t+sensor.yaw,fov:sensor.fov,distance:r.distance,accepted:r.valid,sensor:r.sensor});
      });
    }
    if(selected)drawReading(selected,true);
    const [rx,ry]=xy(state.pose[0],state.pose[1]);
    ctx.save();ctx.translate(rx,ry);
    ctx.beginPath();ctx.ellipse(0,0,Math.max(12,2*Math.sqrt(state.covariance[0])*scale),Math.max(12,2*Math.sqrt(state.covariance[1])*scale),0,0,Math.PI*2);
    ctx.fillStyle='rgba(124,99,231,.07)';ctx.fill();ctx.strokeStyle='rgba(124,99,231,.2)';ctx.stroke();
    ctx.rotate(-state.pose[2]);
    ctx.shadowColor='rgba(42,40,73,.2)';ctx.shadowBlur=10;ctx.shadowOffsetY=3;
    ctx.fillStyle='#fff';ctx.strokeStyle='#6151cf';ctx.lineWidth=1.7;ctx.beginPath();ctx.roundRect(-13,-10,26,20,5);ctx.fill();ctx.stroke();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
    ctx.fillStyle='#3a3f50';ctx.fillRect(-9,-13,16,4);ctx.fillRect(-9,9,16,4);
    ctx.fillStyle='#7663df';ctx.beginPath();ctx.moveTo(9,-4);ctx.lineTo(16,0);ctx.lineTo(9,4);ctx.closePath();ctx.fill();ctx.restore();
    ctx.fillStyle='#686c85';ctx.font='10px "Segoe UI",sans-serif';ctx.textAlign='center';ctx.fillText('MASTER 01',rx,ry+31);ctx.textAlign='left';
    const bar=scale*.5;ctx.strokeStyle='#949db1';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(w-35-bar,h-28);ctx.lineTo(w-35,h-28);ctx.stroke();ctx.font='10px "Segoe UI",sans-serif';ctx.fillStyle='#8790a5';ctx.fillText('0.5 m',w-35-bar/2-12,h-37);
  },[state,layers,selected,camera,size]);
  return <div className="map-surface" ref={container}>
    <canvas ref={ref} aria-label="Live two-dimensional occupancy map; drag to pan and scroll to zoom"
      onWheel={e=>setCamera(c=>({...c,scale:Math.max(35,Math.min(420,c.scale*Math.exp(-e.deltaY*.001)))}))}
      onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,cx:camera.x,cy:camera.y,moved:false};}}
      onPointerMove={e=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>4)d.moved=true;if(d.moved)setCamera(c=>({...c,x:d.cx-dx/c.scale,y:d.cy+dy/c.scale}));}}
      onPointerUp={e=>{const d=drag.current;drag.current=null;if(d&&!d.moved){const bounds=e.currentTarget.getBoundingClientRect();let closest:Reading|null=null,best=18;for(const r of state.readings){if(!r.accepted)continue;const x=size.w/2+(r.endpoint[0]-camera.x)*camera.scale,y=size.h/2-(r.endpoint[1]-camera.y)*camera.scale;const dist=Math.hypot(e.clientX-bounds.left-x,e.clientY-bounds.top-y);if(dist<best){closest=r;best=dist;}}if(closest)onSelect(closest);}}}
      onPointerCancel={()=>{drag.current=null;}} />
    <div className="map-coordinate"><span className="tiny-dot purple"/>Metric frame <span>·</span> {state.grid.resolution*100} cm / cell</div>
    <div className="map-tools">
      <button title="Zoom in" aria-label="Zoom in" onClick={()=>setCamera(c=>({...c,scale:Math.min(420,c.scale*1.2)}))}><Plus size={16}/></button>
      <button title="Zoom out" aria-label="Zoom out" onClick={()=>setCamera(c=>({...c,scale:Math.max(35,c.scale/1.2)}))}><Minus size={16}/></button>
      <button title="Fit survey" aria-label="Fit survey" onClick={()=>{
        const points=state.path.length?state.path.map(p=>[p[1],p[2]]):[[0,0],[0,3.2]];
        points.push(...state.grid.boundary);
        const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
        const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
        setCamera({x:(x0+x1)/2,y:(y0+y1)/2,scale:Math.min(200,(size.w-100)/Math.max(2,x1-x0+1),(size.h-100)/Math.max(2,y1-y0+1))});
      }}><Crosshair size={16}/></button>
    </div>
    {!state.grid.accepted&&<div className="map-empty"><span className="tiny-dot purple"/> {state.mapping==='mapping'?'Waiting for valid observations':'Start a survey to build your map'}</div>}
  </div>;
}
