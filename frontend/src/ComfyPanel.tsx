import React, {useEffect, useRef, useState} from 'react';
import './comfy.css';
import {ArrowRight, Check, CircleAlert, Download, FileJson, Image as ImageIcon, LoaderCircle, Network, RefreshCw, Server, Upload, X} from 'lucide-react';

export type ComfyWorkflow={id:string;name:string;description:string;requires_reference:boolean;source:'example'|'uploaded'};
export type ComfyConfig={base_url:string;configured:boolean;api_key_configured:boolean;workflows:ComfyWorkflow[];notice:string};
type CheckResult={ok:boolean;message:string;devices:{name:string;vram_total?:number}[];missing_nodes?:string[];warnings?:string[]};
export type ImageOptions={image_provider:'seedream'|'comfyui';workflow_id:string|null;reference_image:string|null;seed:number};
export const defaultImageOptions:ImageOptions={image_provider:'seedream',workflow_id:null,reference_image:null,seed:2026};

async function request<T>(path:string,init?:RequestInit):Promise<T>{
 const response=await fetch('/api'+path,{...init,headers:{'Content-Type':'application/json',...init?.headers}});
 if(!response.ok){const body=await response.json().catch(()=>({detail:response.statusText}));throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}
 return response.json();
}

export function ComfyWorkspace(){
 const [config,setConfig]=useState<ComfyConfig|null>(null),[selected,setSelected]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(''),[result,setResult]=useState<CheckResult|null>(null),[imported,setImported]=useState('');
 const input=useRef<HTMLInputElement>(null);
 async function load(){const data=await request<ComfyConfig>('/comfy/config');setConfig(data);setSelected(previous=>data.workflows.some(w=>w.id===previous)?previous:(data.workflows[0]?.id||''));return data;}
 useEffect(()=>{load().catch(e=>setError(e.message));},[]);
 async function check(){setBusy('check');setError('');setResult(null);try{setResult(await request<CheckResult>('/comfy/check',{method:'POST',body:JSON.stringify({workflow_id:selected||undefined})}));}catch(e){setError((e as Error).message)}finally{setBusy('')}}
 async function importFile(file:File){
  setBusy('import');setError('');setImported('');setResult(null);
  try{if(file.size>2*1024*1024)throw new Error('工作流 JSON 请控制在 2MB 以内。');const raw=JSON.parse(await file.text());const data=await request<ComfyWorkflow>('/comfy/workflows',{method:'POST',body:JSON.stringify(raw)});await load();setSelected(data.id);setImported('已导入工作流：'+data.name);}
  catch(e){setError('导入失败：'+(e as Error).message)}finally{setBusy('');if(input.current)input.current.value='';}
 }
 const workflow=config?.workflows.find(w=>w.id===selected);
 return <div className="comfy-workspace">
  <div className="page-heading"><div><div className="eyebrow">PRODUCTION / IMAGE ENGINE</div><h1>ComfyUI 工作区</h1><p>配置分镜图片服务，管理 API 工作流与参考图输入。</p></div><span className="mode-tag">可选图片引擎</span></div>
  <div className="comfy-overview" aria-label="ComfyUI 接入概况"><div><span className="comfy-overview-icon"><Server size={19}/></span><div><span>服务配置</span><strong>{config?(config.configured?'已配置地址':'待配置'):'正在读取'}</strong></div></div><div><span className="comfy-overview-icon"><FileJson size={19}/></span><div><span>可用工作流</span><strong>{config?config.workflows.length+' 个':'正在读取'}</strong></div></div><div><span className={'comfy-overview-icon '+(result?.ok?'is-success':'')}><Network size={19}/></span><div><span>连接检查</span><strong>{busy==='check'?'检查中':result?(result.ok?'检查通过':'检查未通过'):'尚未检查'}</strong></div></div></div>
  <div className="workflow-map" aria-label="图片服务集成流程"><div><small>01 · 脚本策划</small><b>脚本与分镜</b><span>主题、提示词与镜头时长</span></div><ArrowRight size={16}/><div className="workflow-map-focus"><small>02 · 当前配置环节</small><b>ComfyUI 分镜图片</b><span>工作流、参考图与随机种子</span></div><ArrowRight size={16}/><div><small>03 · 镜头生成</small><b>Seedance 视频</b><span>分镜图片转为视频片段</span></div><ArrowRight size={16}/><div><small>04 · 成片交付</small><b>配音与合成</b><span>MiniMax 配音、FFmpeg 合成</span></div></div>
  {error&&<div className="inline-error comfy-error" role="alert"><CircleAlert size={16}/><span>{error}</span></div>}
  {imported&&<div className="comfy-success" role="status"><Check size={16}/>{imported}</div>}
  <div className="comfy-settings-grid"><section className="panel"><div className="panel-title"><div className="comfy-section-heading"><Server size={18}/><h2>服务连接</h2></div><span className={'comfy-state '+(config?.configured?'ready':'')}>{config?(config.configured?'地址已配置':'待配置地址'):'读取中'}</span></div>
   <div className="setting-row"><span>服务地址</span><b className="comfy-server-address">{config?.base_url||'尚未配置'}</b></div><div className="setting-row"><span>访问密钥</span><b>{config?.api_key_configured?'已配置（不展示密钥）':'未配置 · 无鉴权服务可留空'}</b></div><div className="setting-row"><span>连接状态</span><b>{busy==='check'?'检查中':result?(result.ok?'检查通过':'检查未通过'):'尚未检查'}</b></div>
   <p className="comfy-help">在服务器 <code>.env</code> 中填写 <code>COMFYUI_BASE_URL</code>；需要鉴权时填写 <code>COMFYUI_API_KEY</code>，重启服务后生效。支持本机、局域网或自建云端服务。</p>
   <button className="button dark" disabled={!!busy||!config?.configured} onClick={check}>{busy==='check'?<LoaderCircle className="spin" size={15}/>:<RefreshCw size={15}/>}检查连接与所选工作流</button>
   <p className="muted comfy-note">检查仅查询服务和节点信息，不提交生成任务。</p>
   {result&&<div className={'comfy-check-result '+(result.ok?'ok':'')} role="status"><b>{result.ok?'连接检查通过':'需要处理'}</b><p>{result.message}</p>{result.devices?.map((d,i)=><p key={i}>设备：{d.name}{d.vram_total!=null?' · '+(d.vram_total/1024**3).toFixed(1)+' GB 显存':''}</p>)}{!!result.missing_nodes?.length&&<p>缺少节点：{result.missing_nodes.join('、')}</p>}{result.warnings?.map((w,i)=><p key={i}>提示：{w}</p>)}</div>}
  </section><section className="panel"><div className="panel-title"><div className="comfy-section-heading"><FileJson size={18}/><h2>API 工作流</h2></div><span className="comfy-workflow-count">{config?.workflows.length||0} 个可选</span></div>
   <label className="comfy-label">当前工作流<select value={selected} onChange={e=>{setSelected(e.target.value);setResult(null)}} aria-label="当前工作流">{!config?.workflows.length&&<option value="">暂无工作流</option>}{config?.workflows.map(w=><option key={w.id} value={w.id}>{w.name}{w.source==='example'?' · 示例模板':''}</option>)}</select></label>
   {workflow&&<div className="workflow-description"><div><Network size={17}/><b>{workflow.name}</b></div><p>{workflow.description||'使用导入的 ComfyUI API 工作流生成分镜图片。'}</p><div className="workflow-badges"><span>{workflow.requires_reference?'需要参考图':'无需参考图'}</span><span>{workflow.source==='example'?'内置示例 · 待适配模型':'已导入工作流'}</span></div></div>}
   <div className="comfy-button-row"><input ref={input} className="visually-hidden" type="file" accept=".json,application/json" aria-label="导入API工作流JSON" onChange={e=>{const file=e.target.files?.[0];if(file)importFile(file)}}/><button className="button secondary" disabled={!!busy} onClick={()=>input.current?.click()}>{busy==='import'?<LoaderCircle className="spin" size={15}/>:<Upload size={15}/>}导入 API 格式 JSON</button>{selected&&<a className="button secondary" href={'/api/comfy/workflows/'+encodeURIComponent(selected)+'/download'} download><Download size={15}/>下载工作流</a>}</div>
   <p className="comfy-help">先在 ComfyUI 内调通工作流，再导出 API 格式 JSON。普通界面工作流 JSON 不能直接执行。参考图功能需要工作流支持并绑定对应的 LoadImage 节点。</p>
  </section></div>
  <section className="panel comfy-guide"><div className="panel-title"><h2>接入步骤</h2><span className="muted">首次使用请按顺序完成</span></div><div className="comfy-guide-steps"><div><span>01</span><h3>准备生成服务</h3><p>部署 ComfyUI，安装模型和所需节点，在服务器配置文件中填写服务地址。</p></div><div><span>02</span><h3>验证并导入工作流</h3><p>将示例 checkpoint 替换为实际模型，先在 ComfyUI 内生成成功，再导出并导入 API 工作流。</p></div><div><span>03</span><h3>创建视频任务</h3><p>新建任务时选择 ComfyUI 和工作流，按需上传参考图。审核脚本后开始生成镜头。</p></div></div><div className="notice">{config?.notice||'固定种子有助于复现画面，但不保证人物一致。实际一致性依赖参考图、模型及工作流设计。演示模式使用程序绘制素材，不连接 ComfyUI。'}</div></section>
 </div>;
}

export function ImageSourceFields({value,onChange,mode,onReadyChange}:{value:ImageOptions;onChange:(next:ImageOptions)=>void;mode:string;onReadyChange:(ready:boolean)=>void}){
 const [config,setConfig]=useState<ComfyConfig|null>(null),[error,setError]=useState(''),[uploading,setUploading]=useState(false),[referenceUrl,setReferenceUrl]=useState('');
 const input=useRef<HTMLInputElement>(null);
 useEffect(()=>{request<ComfyConfig>('/comfy/config').then(setConfig).catch(e=>setError(e.message));},[]);
 const selected=config?.workflows.find(w=>w.id===value.workflow_id);
 useEffect(()=>{onReadyChange(value.image_provider!=='comfyui'||!!(config?.configured&&selected&&(!selected.requires_reference||value.reference_image)));},[value.image_provider,value.reference_image,selected,config?.configured,onReadyChange]);
 const update=(partial:Partial<ImageOptions>)=>onChange({...value,...partial});
 async function upload(file:File){
  setError('');if(!['image/png','image/jpeg','image/webp'].includes(file.type)){setError('仅支持 PNG、JPEG 或 WEBP 图片。');return}if(file.size>10*1024*1024){setError('参考图不能超过 10MB。');return}setUploading(true);
  try{const result=await request<{key:string;url:string;width:number;height:number}>('/references/upload',{method:'POST',headers:{'Content-Type':file.type},body:file});update({reference_image:result.key});setReferenceUrl(result.url);}
  catch(e){setError((e as Error).message)}finally{setUploading(false);if(input.current)input.current.value=''}
 }
 return <div className="image-options"><div className="field-heading">分镜图片来源<span>视频由 Seedance 生成</span></div><div className="image-provider-cards"><button type="button" aria-pressed={value.image_provider==='seedream'} className={value.image_provider==='seedream'?'selected':''} onClick={()=>{update({image_provider:'seedream',workflow_id:null,reference_image:null});setReferenceUrl('')}}><ImageIcon size={19}/><b>Seedream</b><small>官方 API 图片生成</small>{value.image_provider==='seedream'&&<Check size={14}/>}</button><button type="button" aria-pressed={value.image_provider==='comfyui'} className={value.image_provider==='comfyui'?'selected':''} onClick={()=>update({image_provider:'comfyui',workflow_id:value.workflow_id||config?.workflows[0]?.id||null})}><Network size={19}/><b>ComfyUI</b><small>自定义工作流与参考图</small>{value.image_provider==='comfyui'&&<Check size={14}/>}</button></div>
 {value.image_provider==='comfyui'&&<div className="comfy-form"><label>图片生成工作流<select aria-label="图片生成工作流" value={value.workflow_id||''} onChange={e=>{const next=config?.workflows.find(w=>w.id===e.target.value);update({workflow_id:e.target.value||null,reference_image:next?.requires_reference?value.reference_image:null});if(!next?.requires_reference)setReferenceUrl('')}}><option value="">请选择工作流</option>{config?.workflows.map(w=><option key={w.id} value={w.id}>{w.name}{w.source==='example'?'（示例）':''}</option>)}</select></label>{selected?.source==='example'&&<p className="comfy-form-tip">示例工作流需先在 ComfyUI 中替换为已安装的 checkpoint 并调通，再导入；仅选择模板不代表服务可运行。</p>}
 <label>随机种子<input type="number" min={0} max={2147483647} required value={value.seed} onChange={e=>update({seed:Number(e.target.value)})}/></label><div className="field-heading">人物 / 场景参考图<span>{selected?.requires_reference?'当前工作流必填':'当前工作流不接收参考图'}</span></div>
 <input ref={input} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" aria-label="上传参考图" onChange={e=>{const file=e.target.files?.[0];if(file)upload(file)}}/>{referenceUrl?<div className="reference-preview"><img src={referenceUrl} alt="已上传的分镜参考图"/><div><b>参考图已上传</b><p>图片仅在支持参考图绑定的工作流中生效。</p><button className="text-button" type="button" onClick={()=>{update({reference_image:null});setReferenceUrl('')}}><X size={13}/>移除参考图</button></div></div>:<button className="reference-drop" disabled={uploading||!selected?.requires_reference} type="button" onClick={()=>input.current?.click()}>{uploading?<LoaderCircle className="spin" size={19}/>:<Upload size={19}/>}<span>{uploading?'正在上传…':selected?.requires_reference?'上传一张人物或场景参考图':'请先选择支持参考图的工作流'}<small>PNG / JPEG / WEBP · 最大 10MB</small></span></button>}
 {error&&<p className="comfy-form-error" role="alert">{error}</p>}{mode==='demo'?<div className="notice">演示模式只展示生产流程，不连接 ComfyUI；本次图片来源与参考图设置仅在真实模式执行时生效。</div>:!config?.configured?<div className="notice comfy-warning">ComfyUI 服务尚未配置。请到“ComfyUI 工作区”查看接入说明，并在服务器 .env 中填写地址后重启。</div>:<p className="comfy-form-tip">已配置服务地址。建议先到 ComfyUI 工作区检查连接和节点。固定种子不能单独保证人物一致。</p>}
 </div>}
 </div>;
}
