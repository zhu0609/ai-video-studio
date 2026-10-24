import React, {useEffect, useRef, useState} from 'react';
import {AudioLines, Sparkles, X} from 'lucide-react';
import {ImageSourceFields, defaultImageOptions, type ImageOptions} from './ComfyPanel';

export function CreateModal({onClose,onSubmit,busy}:{onClose:()=>void;onSubmit:(data:unknown)=>void;busy:boolean}){
 const modalRef=useRef<HTMLElement>(null);
 useEffect(()=>{
  const previousOverflow=document.body.style.overflow;
  const previousFocus=document.activeElement as HTMLElement|null;
  document.body.style.overflow='hidden';
  return()=>{document.body.style.overflow=previousOverflow;previousFocus?.focus()};
 },[]);
 useEffect(()=>{
  const handleKey=(event:KeyboardEvent)=>{
   if(event.key==='Escape'&&!busy){event.preventDefault();onClose();return}
   if(event.key!=='Tab')return;
   const controls=Array.from(modalRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')||[]).filter(element=>element.offsetParent!==null);
   const first=controls[0],last=controls[controls.length-1];
   if(!first)return;
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  };
  document.addEventListener('keydown',handleKey);
  return()=>document.removeEventListener('keydown',handleKey);
 },[onClose,busy]);
 const [theme,setTheme]=useState(''),[brief,setBrief]=useState(''),[count,setCount]=useState(2),[duration,setDuration]=useState(12),[ratio,setRatio]=useState('9:16'),[style,setStyle]=useState('电影纪实'),[voice,setVoice]=useState(false),[subtitles,setSubtitles]=useState(true),[auto,setAuto]=useState(false),[mode,setMode]=useState('demo');
 const [imageOptions,setImageOptions]=useState<ImageOptions>(defaultImageOptions),[imageReady,setImageReady]=useState(true);
 return <div className="modal-backdrop"><section ref={modalRef} className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div className="modal-heading"><div><span className="eyebrow">新建生产任务</span><h2 id="create-title">创建视频项目</h2></div><button className="icon-button" disabled={busy} onClick={onClose} aria-label="关闭"><X size={21}/></button></div><form onSubmit={e=>{e.preventDefault();onSubmit({theme,brief,count,duration,ratio,style,voice,subtitles,auto,mode,...imageOptions})}}>
 <label>视频主题 <span>*</span><input autoFocus required minLength={2} maxLength={200} value={theme} onChange={e=>setTheme(e.target.value)} placeholder="例如：未来城市里的中国美食"/></label><div className="suggestions">{['治愈系乡村生活','未来城市里的中国美食','雨夜里的书店'].map(t=><button type="button" key={t} onClick={()=>setTheme(t)}>{t}</button>)}</div>
 <label>补充要求<textarea maxLength={2000} rows={2} value={brief} onChange={e=>setBrief(e.target.value)} placeholder="描述目标受众、场景人物、画面风格或需要避免的内容…"/></label>
 <div className="form-grid"><label>视频数量<input type="number" min={1} max={20} required value={count} onChange={e=>setCount(+e.target.value)}/></label><label>目标时长（秒）<input type="number" min={5} max={600} required value={duration} onChange={e=>setDuration(+e.target.value)}/></label><label>画面比例<select value={ratio} onChange={e=>setRatio(e.target.value)}><option>9:16</option><option>16:9</option><option>1:1</option></select></label><label>视觉风格<select value={style} onChange={e=>setStyle(e.target.value)}>{['电影纪实','治愈自然','未来科幻','国风水墨','商业广告','动漫插画'].map(s=><option key={s}>{s}</option>)}</select></label></div>
 <ImageSourceFields value={imageOptions} onChange={setImageOptions} mode={mode} onReadyChange={setImageReady}/>
 <div className="toggle-group"><label className="check-label"><input type="checkbox" checked={voice} onChange={e=>setVoice(e.target.checked)}/><AudioLines size={16}/>口播配音</label><label className="check-label"><input type="checkbox" checked={subtitles} onChange={e=>setSubtitles(e.target.checked)}/>添加字幕</label><label className="check-label"><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/>跳过脚本审核，自动执行</label></div>
 <label>运行模式<select value={mode} onChange={e=>setMode(e.target.value)}><option value="demo">演示模式 · 不调用付费模型</option><option value="live">真实模式 · 调用已配置的官方 API</option></select></label><div className="notice">{mode==='demo'?'演示画面由程序绘制，带 DEMO 标识。勾选配音时使用提示音，不是真实口播。':`真实模式按供应商规则计费。本次计划生成 ${count} 条视频、约 ${count*Math.ceil(duration/5)} 个镜头；未配置密钥时无法提交。`}</div><div className="modal-footer"><span>{Math.ceil(duration/5)} 镜头 / 条 · 支持多镜头拼接</span><button disabled={busy||(mode==='live'&&!imageReady)} className="button dark" type="submit"><Sparkles size={16}/>{busy?'正在创建…':'创建并开始策划'}</button></div>
 </form></section></div>
}

