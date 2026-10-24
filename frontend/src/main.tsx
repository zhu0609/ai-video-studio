import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowLeft, ArrowRight, ArrowUpRight, AudioLines, BarChart3, ChevronRight, CircleAlert, Clapperboard, Download, FileCheck2, FileText, Film, FolderOpen, Image as ImageIcon, Layers, LayoutGrid, List, LoaderCircle, Network, Plus, RefreshCw, Search, Server, Settings2, ShieldCheck, SlidersHorizontal, WandSparkles, X} from 'lucide-react';
import {ComfyWorkspace} from './ComfyPanel';
import {CreateModal} from './CreateModal';
import {VideoCard} from './VideoCard';
import {UsageWorkspace, BatchUsage} from './UsagePanel';
import {api, send} from './api';
import {Status} from './Status';
import type {Batch, Health} from './types';
import './style.css';

type View = 'projects' | 'library' | 'settings' | 'comfy' | 'usage';
type Filter = 'all' | 'active' | 'review' | 'failed' | 'completed';
const viewTitles = {projects: '视频生产工作台', library: '成片资产库', settings: '模型与运行环境', comfy: 'ComfyUI 工作区', usage: '模型用量'};
const activeStates = ['queued', 'planning', 'generating', 'composing'];
const isActive = (b: Batch) => b.videos.some(v => !!v.active_job || activeStates.includes(v.status));
const hasStatus = (b: Batch, status: string) => b.videos.some(v => v.status === status);
const isComplete = (b: Batch) => b.videos.length > 0 && b.videos.every(v => v.status === 'completed');
const batchStatus = (b: Batch) => isComplete(b) ? 'completed' : isActive(b) ? 'generating' : hasStatus(b, 'failed') ? 'failed' : hasStatus(b, 'review') ? 'review' : hasStatus(b, 'ready') ? 'ready' : 'queued';
const dateLabel = (n: number) => new Date(n * 1000).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});

function App() {
  const [health, setHealth] = useState<Health | null>(null), [batches, setBatches] = useState<Batch[]>([]);
  const [selected, setSelected] = useState<string | null>(null), [detail, setDetail] = useState<Batch | null>(null);
  const [view, setView] = useState<View>('projects'), [showNew, setShowNew] = useState(false);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [refreshing, setRefreshing] = useState(false);
  const [connected, setConnected] = useState(false), [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<{url: string; title: string} | null>(null);
  const [query, setQuery] = useState(''), [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState('newest'), [layout, setLayout] = useState<'list' | 'grid'>('list');
  async function reload() {
    const [items, environment] = await Promise.all([api<Batch[]>('/batches'), api<Health>('/health')]);
    setBatches(items); setHealth(environment); setConnected(true); setLoading(false);
  }
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const items = await api<Batch[]>('/batches'); if (alive) {setBatches(items); setConnected(true); setLoading(false); setError(e => e.startsWith('连接失败') ? '' : e);} }
      catch (e) { if (alive) {setConnected(false); setLoading(false); setError('连接失败：' + (e as Error).message);} }
    };
    tick(); api<Health>('/health').then(h => {if (alive) setHealth(h);}).catch(() => {});
    const timer = setInterval(tick, 2500); return () => {alive = false; clearInterval(timer);};
  }, []);
  useEffect(() => {
    setDetail(null); if (!selected) return;
    let alive = true;
    const tick = async () => {try {const item = await api<Batch>('/batches/' + selected); if (alive) setDetail(item);} catch (e) {if (alive) setError((e as Error).message);}};
    tick(); const timer = setInterval(tick, 2000); return () => {alive = false; clearInterval(timer);};
  }, [selected]);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true); setError('');
    try {await fn(); await reload(); if (selected) setDetail(await api<Batch>('/batches/' + selected));}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function refresh() {setRefreshing(true); try {await reload(); setError('');} catch (e) {setError((e as Error).message); setConnected(false);} finally {setRefreshing(false);}}
  function navigate(next: View) {setView(next); setSelected(null); setQuery(''); window.scrollTo({top: 0, behavior: 'auto'});}
  function openBatch(id: string) {setSelected(id); setView('projects'); setQuery(''); window.scrollTo({top: 0, behavior: 'smooth'});}
  const videos = batches.flatMap(b => b.videos);
  const completed = videos.filter(v => v.status === 'completed').length;
  const active = videos.filter(v => !!v.active_job || activeStates.includes(v.status)).length;
  const review = videos.filter(v => v.status === 'review').length, failed = videos.filter(v => v.status === 'failed').length;
  const filters: {id: Filter; title: string; count: number}[] = [
    {id: 'all', title: '全部项目', count: batches.length}, {id: 'active', title: '制作中', count: batches.filter(isActive).length},
    {id: 'review', title: '待审核', count: batches.filter(b => hasStatus(b, 'review')).length},
    {id: 'failed', title: '需处理', count: batches.filter(b => hasStatus(b, 'failed')).length},
    {id: 'completed', title: '已完成', count: batches.filter(isComplete).length},
  ];
  const filtered = batches.filter(b => `${b.theme} ${b.brief} ${b.style}`.toLowerCase().includes(query.trim().toLowerCase()) &&
    (filter === 'all' || (filter === 'active' ? isActive(b) : filter === 'completed' ? isComplete(b) : hasStatus(b, filter))))
    .sort((a, b) => sort === 'newest' ? b.created - a.created : a.created - b.created);
  const assets = batches.flatMap(b => b.videos.filter(v => v.output && v.status === 'completed').map(v => ({batch: b, video: v})));
  const visibleAssets = assets.filter(({batch, video}) => `${batch.theme} ${video.title}`.toLowerCase().includes(query.trim().toLowerCase()));
  const percent = videos.length ? Math.round(completed / videos.length * 100) : 0;
  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="#" aria-label="映序 FRAMEFLOW" onClick={e => {e.preventDefault(); navigate('projects');}}><span className="brand-icon"><Clapperboard size={24}/></span><span>映序<span className="brand-en">FRAMEFLOW</span></span></a>
      <div className="workspace-label">生产管理 <span>WORKSPACE</span></div>
      <nav aria-label="主导航">
        <button className={'nav ' + (view === 'projects' ? 'active' : '')} onClick={() => navigate('projects')}><LayoutGrid size={18}/><span className="nav-text">视频工作台</span><span className="nav-count">{batches.length}</span></button>
        <button className={'nav ' + (view === 'library' ? 'active' : '')} onClick={() => navigate('library')}><Film size={18}/><span className="nav-text">成片资产库</span><span className="nav-count">{completed}</span></button>
        <button className={'nav ' + (view === 'usage' ? 'active' : '')} onClick={() => navigate('usage')}><BarChart3 size={18}/><span className="nav-text">模型用量</span></button>
        <div className="nav-divider"/><div className="nav-group-label">配置与集成</div>
        <button className={'nav ' + (view === 'settings' ? 'active' : '')} onClick={() => navigate('settings')}><Settings2 size={18}/><span className="nav-text">模型与运行环境</span></button>
        <button className={'nav ' + (view === 'comfy' ? 'active' : '')} onClick={() => navigate('comfy')}><Network size={18}/><span className="nav-text">ComfyUI 工作区</span></button>
      </nav>
      <div className="sidebar-bottom"><div className={'connection-status ' + (connected ? 'connected' : '')}><i/>{connected ? '服务已连接' : loading ? '连接检查中' : '服务连接中断'}<span>本地部署</span></div><div className="profile"><div className="avatar"><Clapperboard size={19}/></div><div><b>AI 视频生产中心</b><small>内容生产 · 任务管理 · 交付</small></div></div></div>
    </aside>
    <main>
      <header className="topbar"><div className="breadcrumb"><span>生产工作空间</span><ChevronRight size={14}/><b>{selected ? '项目详情' : viewTitles[view]}</b></div><div className="top-right"><span className="environment-pill"><ShieldCheck size={14}/>本地部署</span><span className="topbar-divider"/><span className={'connection-mini ' + (connected ? 'online' : '')}><i/>{connected ? '服务正常' : '连接检查'}</span></div></header>
      {error && <div className="error-toast" role="alert"><CircleAlert size={18}/><span>{error}</span><button aria-label="关闭提示" onClick={() => setError('')}><X size={16}/></button></div>}
      <div className="content">
      {selected ? <>
        <button className="back-link" onClick={() => navigate('projects')}><ArrowLeft size={15}/>返回视频工作台</button>
        {detail ? <><div className="page-heading detail-heading"><div><div className="eyebrow">项目详情 <span>/ {detail.id.slice(0, 8).toUpperCase()}</span></div><h1>{detail.theme}</h1><p>{detail.count} 条视频 · {detail.duration} 秒 / 条 · {detail.ratio} · {detail.style}<span className={'mode-tag ' + detail.mode}>{detail.mode === 'demo' ? '演示项目' : '真实模型'}</span></p></div><a aria-disabled={!isComplete(detail)} className={'button dark ' + (isComplete(detail) ? '' : 'disabled')} href={isComplete(detail) ? '/api/batches/' + detail.id + '/download' : undefined}><Download size={16}/>批量下载成片</a></div>
          <div className="detail-summary"><div><span>生产进度</span><b>{detail.videos.filter(v => v.status === 'completed').length}<small> / {detail.count} 条已完成</small></b></div><div><span>分镜图片服务</span><b>{detail.image_provider === 'comfyui' ? 'ComfyUI' : 'Seedream'}</b></div><div><span>音频与字幕</span><b>{detail.voice ? '口播配音' : '无口播'} · {detail.subtitles ? '添加字幕' : '无字幕'}</b></div><div><span>执行方式</span><b>{detail.auto ? '自动执行' : '脚本审核后生成'}</b></div></div>
          {detail.comfy_workflow && <div className="source-summary"><Network size={15}/><span>{detail.comfy_workflow.name}</span><span>随机种子 {detail.seed}</span>{detail.reference_image && <img src={'/media/' + detail.reference_image} alt="项目参考图"/>}</div>}
          <div className={'notice ' + (detail.mode === 'demo' ? '' : 'subtle-notice')}>{detail.mode === 'demo' ? health?.demo_notice : '重新生成会创建新的模型调用；恢复执行复用已有结果。调用次数与供应商返回用量可在各视频的调用记录中查看。'}</div>
          {detail.mode !== 'demo' && <BatchUsage batchId={detail.id}/>}
          <div className="video-list">{detail.videos.map(v => <VideoCard key={v.id} video={v} batch={detail} busy={busy} perform={perform} preview={setPreview}/>)}</div>
        </> : <div className="loading-state"><LoaderCircle className="spin"/>正在读取项目详情…</div>}
      </> : view === 'usage' ? <UsageWorkspace batches={batches}/> : view === 'comfy' ? <ComfyWorkspace/> : view === 'settings' ? <SettingsPage health={health} onComfy={() => navigate('comfy')}/> : view === 'library' ? <>
        <div className="page-heading"><div><div className="eyebrow">资产管理 <span>/ VIDEO ASSETS</span></div><h1>成片资产库<span className="heading-count">{completed}</span></h1><p>统一预览、管理和下载已完成的视频内容。</p></div><button className="button dark" onClick={() => setShowNew(true)}><Plus size={17}/>新建视频项目</button></div>
        <div className="asset-toolbar"><div className="section-title"><h2>全部成片</h2><span>{visibleAssets.length} 条结果</span></div><SearchField value={query} onChange={setQuery} placeholder="搜索成片名称或项目主题"/></div>
        <div className="library-grid">{visibleAssets.map(({batch: b, video: v}) => <article className="library-card" key={v.id}><div className="library-video"><video preload="metadata" src={'/media/' + v.output} controls/><span className={'asset-mode ' + b.mode}>{b.mode === 'demo' ? '演示素材' : 'AI 生成'}</span></div><div className="library-body"><h3 title={v.title}>{v.title}</h3><p>{b.ratio}<span>·</span>{b.duration} 秒<span>·</span>{dateLabel(b.created)}</p><div className="library-actions"><button className="text-button" onClick={() => openBatch(b.id)}>查看项目<ArrowUpRight size={14}/></button><a className="button secondary compact" href={'/api/videos/' + v.id + '/download'}><Download size={14}/>下载</a></div></div></article>)}</div>
        {!visibleAssets.length && <Empty title={query ? '没有匹配的成片' : '暂无可交付成片'} text={query ? '尝试其他关键词，或清空搜索条件。' : '项目完成合成后，视频将自动归档至此处。'} onClick={query ? () => setQuery('') : () => setShowNew(true)} action={query ? '清空搜索' : '创建视频项目'}/>}
      </> : <>
        <div className="page-heading"><div><div className="eyebrow">生产总览 <span>/ PRODUCTION OVERVIEW</span></div><h1>视频生产工作台</h1><p>从主题策划到成片交付，集中管理每一个生产环节。</p></div><div className="heading-actions"><button className="button secondary" disabled={refreshing} onClick={refresh}><RefreshCw size={15} className={refreshing ? 'spin' : ''}/>刷新</button><button className="button dark" onClick={() => setShowNew(true)}><Plus size={17}/>新建视频项目</button></div></div>
        <div className="stats"><Stat title="项目总数" value={batches.length} sub={`${videos.length} 条视频版本`} icon={<Layers size={20}/>} tone="blue"/><Stat title="制作中" value={active} sub="策划、镜头生成及合成" icon={<Activity size={20}/>} tone="purple"/><Stat title="待审核" value={review} sub="审核脚本后开始生成" icon={<FileCheck2 size={20}/>} tone="amber"/><Stat title="已完成视频" value={completed} sub="可预览并下载交付" icon={<Film size={20}/>} tone="green"/></div>
        <section className="production-strip"><div className="production-strip-label"><span className="flow-symbol"><WandSparkles size={18}/></span><div><b>自动化生产流程</b><span>按镜头生成，按项目交付</span></div></div><div className="flow-steps">{['主题策划', '脚本审核', '分镜图片', '视频片段', '配音字幕', '成片交付'].map((step, i) => <React.Fragment key={step}><div><span>{String(i + 1).padStart(2, '0')}</span>{step}</div>{i < 5 && <ChevronRight size={13}/>}</React.Fragment>)}</div></section>
        <div className="dashboard-columns"><section className="projects-panel"><div className="panel-heading"><div><h2>项目管理</h2><p>按状态跟进生产任务，查看各版本的生成结果。</p></div><span className="live-label"><i/>{connected ? '自动更新' : '连接中断'}</span></div>
          <div className="project-toolbar"><div className="filter-tabs" role="group" aria-label="按项目状态筛选">{filters.map(f => <button key={f.id} aria-pressed={filter === f.id} className={filter === f.id ? 'selected' : ''} onClick={() => setFilter(f.id)}>{f.title}<span>{f.count}</span></button>)}</div><div className="project-tools"><SearchField value={query} onChange={setQuery}/><div className="sort-control"><SlidersHorizontal size={14}/><select aria-label="项目排序" value={sort} onChange={e => setSort(e.target.value)}><option value="newest">最新创建</option><option value="oldest">最早创建</option></select></div><div className="layout-switch" role="group" aria-label="项目展示方式"><button aria-label="列表视图" aria-pressed={layout === 'list'} className={layout === 'list' ? 'selected' : ''} onClick={() => setLayout('list')}><List size={17}/></button><button aria-label="卡片视图" aria-pressed={layout === 'grid'} className={layout === 'grid' ? 'selected' : ''} onClick={() => setLayout('grid')}><LayoutGrid size={16}/></button></div></div></div>
          {loading ? <div className="loading-state"><LoaderCircle className="spin"/>正在加载项目…</div> : filtered.length ? <div className={'project-collection ' + layout}>{layout === 'list' && <div className="project-list-header"><span>项目 / 生产规格</span><span>当前状态</span><span>完成进度</span><span>创建时间</span><span/></div>}{filtered.map(b => <ProjectItem key={b.id} batch={b} onClick={() => openBatch(b.id)}/>)}</div> : <Empty title={batches.length ? '没有符合条件的项目' : '创建第一个视频项目'} text={batches.length ? '调整状态筛选或搜索关键词后重试。' : '填写主题、数量与视觉风格，即可开始策划与分镜生产。'} onClick={batches.length ? () => {setFilter('all'); setQuery('');} : () => setShowNew(true)} action={batches.length ? '重置筛选' : '新建视频项目'}/>}
          <div className="list-footer"><span>显示 {filtered.length} / {batches.length} 个项目</span><span>每 2.5 秒同步任务状态</span></div>
        </section><aside className="overview-rail"><section className="rail-panel"><div className="rail-title"><h2>交付概况</h2><span className="icon-soft"><Film size={17}/></span></div><div className="delivery-metric"><strong>{completed}<span> / {videos.length}</span></strong><span>视频已完成</span></div><div className="delivery-progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="视频交付完成率"><span style={{width: percent + '%'}}/></div><div className="delivery-caption"><span>整体完成率</span><b>{percent}%</b></div><div className="rail-breakdown"><div><i className="dot amber"/>待审核<span>{review}</span></div><div><i className="dot red"/>需处理<span>{failed}</span></div><div><i className="dot blue"/>制作中<span>{active}</span></div></div></section><section className="rail-panel"><div className="rail-title"><h2>运行环境</h2><Server size={17}/></div><div className="runtime-row"><span>任务执行</span><b>{health ? health.execution_mode === 'local' ? '本机队列' : 'Celery 队列' : '读取中'}</b></div><div className="runtime-row"><span>数据存储</span><b>{health?.database === 'sqlite' ? 'SQLite' : health?.database === 'postgresql' ? 'PostgreSQL' : '读取中'}</b></div><div className="runtime-row"><span>合成引擎</span><b className={health?.ffmpeg ? 'text-green' : ''}>{health ? health.ffmpeg ? 'FFmpeg 已就绪' : '未就绪' : '读取中'}</b></div><button className="rail-link" onClick={() => navigate('settings')}>查看模型与配置<ArrowRight size={14}/></button></section><div className="rail-note"><ShieldCheck size={17}/><p>模型密钥保存在服务端。<br/>调用次数与返回用量可追溯。</p></div></aside></div>
      </>}
      </div>
      <footer><span>映序 FRAMEFLOW <i/>AI 视频生产中心</span><span>主题策划 · 批量生成 · 成片交付</span></footer>
    </main>
    {showNew && <CreateModal onClose={() => setShowNew(false)} busy={busy} onSubmit={data => perform(async () => {const b = await api<{id: string}>('/batches', send(data)); setSelected(b.id); setView('projects'); setShowNew(false);})}/>}
    {preview && <div className="modal-backdrop" onClick={() => setPreview(null)}><div className="preview-modal" role="dialog" aria-modal="true" aria-label={preview.title} onClick={e => e.stopPropagation()}><div className="modal-heading"><h2>{preview.title}</h2><button className="icon-button" onClick={() => setPreview(null)} aria-label="关闭预览"><X size={20}/></button></div><video src={preview.url} controls autoPlay/></div></div>}
  </div>;
}

function SearchField({value, onChange, placeholder = '搜索项目主题'}: {value: string; onChange: (value: string) => void; placeholder?: string}) {
  return <div className="search-field"><Search size={16}/><input aria-label={placeholder} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}/>{value && <button aria-label="清空搜索" onClick={() => onChange('')}><X size={13}/></button>}</div>;
}
function Stat({title, value, sub, icon, tone}: {title: string; value: number; sub: string; icon: React.ReactNode; tone: string}) {
  return <div className={'stat ' + tone}><div className="stat-icon">{icon}</div><div className="stat-label">{title}</div><strong>{String(value).padStart(2, '0')}</strong><small>{sub}</small></div>;
}
function ProjectItem({batch: b, onClick}: {batch: Batch; onClick: () => void}) {
  const done = b.videos.filter(v => v.status === 'completed').length, ratio = b.count ? Math.min(100, Math.round(done / b.count * 100)) : 0;
  return <button className="project-item" onClick={onClick} aria-label={`打开项目：${b.theme}`}><div className="project-identity"><span className={'project-symbol ' + (b.mode === 'demo' ? 'demo' : '')}><Clapperboard size={23}/></span><div><div className="project-name"><h3 title={b.theme}>{b.theme}</h3><span className={'mode-tag ' + b.mode}>{b.mode === 'demo' ? '演示' : 'AI 生成'}</span></div><p>{b.count} 条视频<span>·</span>{b.duration} 秒 / 条<span>·</span>{b.ratio}<span className="project-style">{b.style}</span></p></div></div><div className="project-state"><Status value={batchStatus(b)}/></div><div className="project-completion"><div><b>{done}<span> / {b.count}</span></b><small>{ratio}%</small></div><div className="project-progress"><span style={{width: ratio + '%'}}/></div></div><time className="project-date" dateTime={new Date(b.created * 1000).toISOString()}>{dateLabel(b.created)}</time><ChevronRight className="project-open" size={17}/></button>;
}
function Empty({title, text, onClick, action}: {title: string; text: string; onClick: () => void; action: string}) {
  return <div className="empty"><span className="empty-icon"><FolderOpen size={26}/></span><h3>{title}</h3><p>{text}</p><button className="button secondary" onClick={onClick}>{action}<ArrowRight size={14}/></button></div>;
}
function SettingsPage({health, onComfy}: {health: Health | null; onComfy: () => void}) {
  const meta: Record<string, {title: string; service: string; icon: React.ReactNode}> = {text: {title: '脚本策划', service: '火山方舟 · 文本模型', icon: <FileText size={20}/>}, image: {title: '分镜图片', service: 'Seedream', icon: <ImageIcon size={20}/>}, video: {title: '视频片段', service: 'Seedance', icon: <Clapperboard size={20}/>}, speech: {title: '口播配音', service: 'MiniMax', icon: <AudioLines size={20}/>}};
  return <><div className="page-heading"><div><div className="eyebrow">配置管理 <span>/ SYSTEM SETTINGS</span></div><h1>模型与运行环境</h1><p>查看模型配置与任务运行环境，密钥由服务端统一管理。</p></div><span className="secure-label"><ShieldCheck size={16}/>服务端密钥保护</span></div><div className="provider-grid">{Object.entries(meta).map(([key, item]) => {const value = health?.providers[key], configured = !!value && value !== '未配置'; return <section className="provider-card" key={key}><div className="provider-card-head"><span className="provider-icon">{item.icon}</span><span className={'config-status ' + (configured ? 'ready' : '')}><i/>{health ? configured ? '已配置模型' : '待配置' : '读取中'}</span></div><h2>{item.title}</h2><p>{item.service}</p><div className="provider-model"><small>模型 / 接入点</small><code>{value || '读取中'}</code></div></section>;})}</div><div className="settings-grid"><section className="panel"><div className="panel-title"><h2>任务运行环境</h2><Server size={18}/></div><div className="setting-row"><span>任务执行</span><b>{health ? health.execution_mode === 'local' ? '本机持久化任务队列' : 'Celery + Redis' : '读取中'}</b></div><div className="setting-row"><span>业务数据库</span><b>{health?.database === 'sqlite' ? 'SQLite' : health?.database === 'postgresql' ? 'PostgreSQL' : '读取中'}</b></div><div className="setting-row"><span>视频合成</span><b>{health ? health.ffmpeg ? 'FFmpeg 已就绪' : 'FFmpeg 未就绪' : '读取中'}</b></div><p className="muted settings-note">“已配置模型”仅表示已填写模型项；服务可用性以实际调用结果为准。修改配置文件后需要重启服务。</p>{!!health?.missing_config.length && <div className="notice">待填写配置：{health.missing_config.join('、')}。演示模式不需要模型密钥。</div>}</section><section className="panel integration-panel"><span className="integration-icon"><Network size={26}/></span><span className="eyebrow">工作流集成</span><h2>ComfyUI 分镜生成</h2><p>接入已部署的图片工作流，配置参考图与随机种子，再使用现有视频生产流程完成交付。</p><div className="integration-tags"><span>原生 API</span><span>自定义工作流</span><span>参考图</span></div><button className="button secondary" onClick={onComfy}>管理 ComfyUI 集成<ArrowRight size={15}/></button></section></div><div className="security-note"><ShieldCheck size={18}/><div><b>配置与用量记录</b><p>在项目根目录 .env 中维护服务地址、模型与密钥。前端只展示配置状态；实际调用次数与供应商返回用量可在项目详情中查看。</p></div></div></>;
}

createRoot(document.getElementById('root')!).render(<App/>);
