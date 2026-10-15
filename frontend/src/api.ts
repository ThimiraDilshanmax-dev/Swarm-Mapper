export async function api<T>(path:string, body?:unknown):Promise<T> {
  const response = await fetch('/api' + path, { credentials:'same-origin',
    ...(body !== undefined ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {}) });
  if (!response.ok) {
    const detail = await response.json().catch(()=>({detail:response.statusText}));
    throw new Error(typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail));
  }
  return response.json();
}
export function download(name:string, object:unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(object,null,2)],{type:'application/json'}));
  const a=document.createElement('a'); a.href=url; a.download=name; a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export const duration = (seconds:number) => {
  const n=Math.max(0,Math.floor(seconds));
  return String(Math.floor(n/60)).padStart(2,'0') + ':' + String(n%60).padStart(2,'0');
};
