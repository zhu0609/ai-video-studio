import {useState} from 'react';
import {BarChart3, Check, ChevronDown, ChevronUp, CircleAlert, Clapperboard, Clock3, Download, FileText, Image as ImageIcon, Layers, Play, RefreshCw} from 'lucide-react';
import {api, send} from './api';
import {Status} from './Status';
import type {Batch, Shot, Video} from './types';

type VideoCardProps = {
  video: Video;
  batch: Batch;
  busy: boolean;
  perform: (fn: () => Promise<unknown>) => Promise<void>;
  preview: (value: {url: string; title: string}) => void;
};

const callKinds: Record<string, string> = {
  text: '脚本策划',
  image: '分镜图片',
  video: '视频生成',
  speech: '口播配音',
};

export function VideoCard({video, batch, busy, perform, preview}: VideoCardProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(video.title);
  const [draft, setDraft] = useState<Shot[]>([]);
  const [showCalls, setShowCalls] = useState(false);
  const shots = Array.isArray(video.shots) ? video.shots : [];
  const calls = Array.isArray(video.calls) ? video.calls : [];
  const disabled = busy || !!video.active_job;
  const completedImages = shots.filter(shot => !!shot.image).length;
  const completedClips = shots.filter(shot => !!shot.clip).length;
  const plannedSeconds = shots.reduce((total, shot) => total + shot.duration, 0);
  const requestCount = calls.reduce((total, call) => total + call.attempts, 0);
  const consumption = video.usage_summary?.summary;
  const usageNumber = (value: number | null | undefined) => value == null ? '未提供' : value.toLocaleString('zh-CN', {maximumFractionDigits: 2});

  const action = (actionName: string, shotId?: string) => perform(() => api(
    '/videos/' + video.id + '/actions',
    send({action: actionName, shot_id: shotId}),
  ));

  function redo(actionName: string, shotId?: string) {
    if (batch.mode === 'live' && !window.confirm('这将创建新的生成调用，可能产生额外费用。若只是等待超时，请使用恢复执行。确定重新生成？')) return;
    action(actionName, shotId);
  }

  function toggleEditor() {
    if (editing) {
      setEditing(false);
      return;
    }
    setTitle(video.title);
    setDraft(shots.map(shot => ({...shot})));
    setEditing(true);
  }

  function updateDraft(index: number, update: Partial<Shot>) {
    setDraft(current => current.map((shot, shotIndex) => shotIndex === index ? {...shot, ...update} : shot));
  }

  async function saveScript() {
    await perform(async () => {
      await api('/videos/' + video.id + '/script', {
        method: 'PUT',
        body: JSON.stringify({
          title,
          shots: draft.map(({id, duration, narration, prompt}) => ({id, duration, narration, prompt})),
        }),
      });
      setEditing(false);
    });
  }

  return <article className="video-card">
    <div className="video-card-header">
      <div className="video-number">{String(video.number).padStart(2, '0')}</div>
      <div className="video-title">
        <h2>{video.title}</h2>
        <p className="video-meta"><span>视频版本 {String(video.number).padStart(2, '0')}</span><span>修订 {video.revision}</span><span>ID {video.id.slice(0, 8)}</span></p>
      </div>
      <Status value={video.status}/>
    </div>

    {video.error && <div className="inline-error" role="alert"><CircleAlert size={16}/><span>{video.error}</span></div>}

    <div className="video-card-summary" aria-label="视频制作概况">
      <span><Layers size={14}/>{shots.length} 个镜头</span>
      <span><Clock3 size={14}/>{plannedSeconds.toFixed(1)} 秒 / 目标 {batch.duration} 秒</span>
      <span><ImageIcon size={14}/>图片 {completedImages}/{shots.length}</span>
      <span><Clapperboard size={14}/>片段 {completedClips}/{shots.length}</span>
      <span>{batch.voice ? '已启用配音' : '未启用配音'} · {batch.subtitles ? '已启用字幕' : '未启用字幕'}</span>
    </div>

    {batch.mode === 'live' && <section className="video-usage-summary" aria-label="本视频模型用量">
      <div className="video-usage-heading"><span><BarChart3 size={15}/>本视频模型用量</span><small>{consumption ? `${consumption.attempts} 次请求 · ${consumption.reported_calls}/${consumption.calls} 条已上报用量` : '正在同步统计'}</small></div>
      <div className="video-usage-values"><span>文本 Token <b>{usageNumber(consumption?.text_tokens)}</b></span><span>图片 Token <b>{usageNumber(consumption?.image_tokens)}</b></span><span>视频 Token <b>{usageNumber(consumption?.video_tokens)}</b></span><span>配音计费字符 <b>{usageNumber(consumption?.speech_characters)}</b></span></div>
      <div className="video-usage-footnote"><span>包括本视频的历史重做与脚本纠错；未提供不代表零消耗。</span><button className="text-button" aria-expanded={showCalls} onClick={() => setShowCalls(value => !value)}>{showCalls ? '收起调用明细' : '查看调用明细'}<ChevronDown size={12}/></button></div>
    </section>}

    <div className="video-actions">
      <button className="button secondary" disabled={disabled || !shots.length} onClick={toggleEditor}>
        <FileText size={14}/>{editing ? '取消编辑' : '审核 / 编辑脚本'}
      </button>
      <button className="text-button" disabled={disabled} onClick={() => redo('plan')}><RefreshCw size={14}/>重写脚本</button>
      <div className="spacer"/>
      {video.output && <>
        <button className="button secondary" onClick={() => preview({url: '/media/' + video.output, title: video.title})}><Play size={14}/>预览成片</button>
        <a className="button secondary" href={'/api/videos/' + video.id + '/download'}><Download size={14}/>下载</a>
      </>}
      {video.status !== 'completed' && <button className="button dark" disabled={disabled || !shots.length || editing} onClick={() => action(video.status === 'failed' ? 'resume' : 'generate')}>
        <Play size={14}/>{video.active_job ? '处理中…' : video.status === 'failed' ? '恢复执行' : '确认并生成'}
      </button>}
    </div>

    {editing ? <div className="script-editor">
      <div className="script-editor-heading"><h3>脚本与分镜编辑</h3><span>保存后，再确认开始生成</span></div>
      <label>视频标题<input value={title} maxLength={200} onChange={event => setTitle(event.target.value)}/></label>
      {draft.map((shot, index) => <div className="edit-shot" key={shot.id}>
        <b className="edit-shot-heading">镜头 {String(shot.position).padStart(2, '0')}</b>
        <label>时长（秒）<input type="number" min={1} max={10} step={0.1} value={shot.duration} onChange={event => updateDraft(index, {duration: +event.target.value})}/></label>
        <label>口播 / 字幕<textarea value={shot.narration} rows={2} onChange={event => updateDraft(index, {narration: event.target.value})}/></label>
        <label>画面与运镜<textarea value={shot.prompt} rows={3} onChange={event => updateDraft(index, {prompt: event.target.value})}/></label>
      </div>)}
      <div className="editor-footer">
        <span>总时长 {draft.reduce((total, shot) => total + shot.duration, 0).toFixed(1)} / {batch.duration} 秒 · 修改画面会使对应图片与视频失效。</span>
        <button className="button dark" disabled={disabled} onClick={saveScript}>保存脚本 <Check size={15}/></button>
      </div>
    </div> : <>
      <div className="video-section-heading"><h3>分镜与生成素材</h3><span>按镜头管理 · 支持局部重做</span></div>
      {shots.length ? <div className="shots">{shots.map(shot => <div className="shot" key={shot.id}>
        <div className="shot-image">
          {shot.image ? <img src={'/media/' + shot.image} alt={'镜头 ' + shot.position + ' 分镜图片'} loading="lazy"/> : <div className="shot-placeholder"><ImageIcon size={26}/><small>分镜图片待生成</small></div>}
          <span>{String(shot.position).padStart(2, '0')}</span>
        </div>
        <div className="shot-body">
          <div className="shot-top"><b>镜头 {shot.position}</b><span>{shot.duration.toFixed(1)} 秒</span></div>
          <p className="shot-prompt" title={shot.prompt}>{shot.prompt}</p>
          <p className="narration">“{shot.narration || '无口播'}”</p>
          <div className="shot-status"><span>图片 <Status value={shot.image_status}/></span><span>视频 <Status value={shot.clip_status}/></span></div>
          {shot.task_id && <small className="task-id">任务 ID：{shot.task_id}</small>}
          {shot.error && <p className="shot-error">{shot.error}</p>}
          <div className="shot-buttons">
            <button disabled={disabled} onClick={() => redo('image', shot.id)}>重做图片</button>
            <button disabled={disabled} onClick={() => redo('clip', shot.id)}>重做视频</button>
            {shot.clip && <button onClick={() => preview({url: '/media/' + shot.clip, title: '镜头 ' + shot.position})}><Play size={12}/>预览片段</button>}
          </div>
        </div>
      </div>)}</div> : <div className="video-empty-state"><FileText size={24}/><p>脚本策划完成后，分镜与生成进度将在这里展示。</p></div>}
    </>}

    <div className="video-card-bottom">
      <button className="text-button muted" aria-expanded={showCalls} onClick={() => setShowCalls(value => !value)}>
        {showCalls ? <ChevronUp size={14}/> : <ChevronDown size={14}/>}{showCalls ? '收起' : '查看'}调用记录 · {requestCount} 次请求
      </button>
      <button className="text-button" disabled={disabled || !shots.length || shots.some(shot => !shot.clip) || editing} onClick={() => action('compose')}><Clapperboard size={14}/>重新合成</button>
    </div>

    {showCalls && <div className="calls">
      <p className="muted">调用次数包括明确被限流的请求。金额未知，不估算费用；结果不确定的提交不会自动重发。</p>
      {!calls.length ? <p className="ledger-empty">暂无第三方调用，演示模式不产生供应商费用。</p> : calls.map(call => <div className="call" key={call.id}>
        <div className="call-heading"><b>{callKinds[call.kind] || call.kind} · {call.model}</b><Status value={call.state}/><span>{call.attempts} 次请求</span></div>
        <small className="call-meta">供应商：{call.provider}</small>
        {call.task_id && <small>任务 ID：{call.task_id}</small>}
        {call.usage != null && <><span className="ledger-usage-label">供应商用量</span><pre>{JSON.stringify(call.usage, null, 2)}</pre></>}
        {call.error && <p>{call.error}</p>}
        {['uncertain', 'submitted', 'failed'].includes(call.state) && <div className="call-resolve">
          {(call.kind === 'video' || call.provider === 'comfyui') && <button disabled={disabled} onClick={() => {
            const taskId = window.prompt('在供应商控制台找到这次调用对应的任务 ID。绑定后点“恢复执行”。');
            if (taskId) perform(() => api('/calls/' + call.id + '/resolve', send({task_id: taskId})));
          }}>绑定已有任务 ID / prompt_id</button>}
          <button disabled={disabled} onClick={() => {
            if (window.confirm('请先在供应商控制台核对：确认此请求未被受理且没有已生成的结果？解锁后恢复执行会重新调用并可能计费。')) {
              perform(() => api('/calls/' + call.id + '/resolve', send({confirmed_not_accepted: true})));
            }
          }}>已确认未受理，解锁重试</button>
        </div>}
      </div>)}
    </div>}
  </article>;
}
