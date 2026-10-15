export type Pose = [number, number, number];
export type PathPoint = [number, number, number, number];
export interface SensorConfig { id: 'front'|'left'|'right'; x: number; y: number; yaw: number; fov: number; offset: number; min_range: number; max_range: number }
export interface Profile {
  name: string; wheel_diameter: number; wheel_base: number; counts_per_revolution: number;
  left_scale: number; right_scale: number; gyro_bias: number; max_speed: number; max_turn: number;
  resolution: number; sensor_height: number; target_side: 'left'|'right'|'all';
  tof_model: 'unconfirmed'|'VL53L0X'|'VL53L1X'; verified: boolean; sensors: SensorConfig[];
}
export interface Reading { id:number; t:number; sensor:string; distance:number|null; accepted:boolean; reason:string; pose:Pose; origin:[number,number]; angle:number; fov:number; endpoint:[number,number]; target:boolean; cells:number; signal:number|null; ambient:number|null }
export interface GridData { resolution:number; origin:[number,number]; width:number; height:number; data:number[]; boundary:number[][]; version:number; accepted:number; rejected:number; bounds:{width:number;height:number}|null; clipped:boolean }
export interface Summary { distance:number; readings:number; accepted:number; rejected:number; frames:number; duration:number; gaps:number }
export interface State {
  type:'state'; source:'simulator'|'robot'; connected:boolean; armed:boolean; owner:string|null;
  stop_latched:boolean; mapping:'idle'|'mapping'|'paused'|'finished'; led:string; age:number;
  robot:Record<string,unknown>; ack:number; pending_ack:boolean; pose:Pose; velocity:number[];
  covariance:number[]; gyro_bias:number; disagreement:number;
  kalman:{innovation:number;bias_gain:number;bias_variance:number};
  path:PathPoint[]; odom_path:PathPoint[]; original_path:PathPoint[]; grid:GridData;
  readings:Reading[]; events:{t:number;kind:string;message:string}[]; summary:Summary;
  profile:Profile; robot_profile:Profile; session_id:string|null; session_name:string;
  replay:{id:string;note?:string;override?:boolean;cursor:number;total:number;playing:boolean;speed:number}|null;
  optimization:{keyframes:number;endpoint_before:number;endpoint_after:number;cost:number;source:string}|null;
  working:boolean; reference:number[][]|null; demo:boolean; sim_speed:number; needs_segment:boolean;
  measurement_source:'simulator'|'robot'; range_time:number;
  live_ranges:{sensor:string;t:number;distance:number|null;valid:boolean;status:string}[];
}
export interface Session { id:string;name:string;created:number;source:string;status:string;profile:Profile;summary:Summary;samples:number;note:string }
export type View = 'live'|'sessions'|'calibration'|'compare';
export interface Layers { occupancy:boolean; boundary:boolean; path:boolean; odometry:boolean; rays:boolean; reference:boolean }
