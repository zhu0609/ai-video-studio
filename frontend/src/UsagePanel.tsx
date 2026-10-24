import {useEffect, useMemo, useState} from 'react';
import {Activity, ArrowDownToLine, AudioLines, ChartNoAxesCombined, CheckCheck, ChevronDown, CircleAlert, Clock3, FileText, Image as ImageIcon, Info, LoaderCircle, RefreshCw, Video} from 'lucide-react';
import type {UsageKind, UsageModel, UsageReport, UsageSummary} from './usageTypes';
import './usage.css';

type UsageFilters = {batchId?: string; days?: string};
type UsageState = {key: string; report: UsageReport | null; error: string; refreshing: boolean};
const numberFormat = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 2});
const kindLabels: Record<UsageKind, string> = {text: '文本策划', image: '分镜图片', video: '视频片段', speech: '语音配音'};
const kindIcons = {text: FileText, image: ImageIcon, video: Video, speech: AudioLines};
const providerLabels: Record<string, string> = {ark: '火山方舟', comfyui: '自建工作流', minimax: 'MiniMax 配音'};

function formatValue(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '未提供' : numberFormat.format(value);
}

function formatTime(value: string | number | null | undefined, short = false) {
  if (value == null) return '未提供';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return '未提供';
  return date.toLocaleString('zh-CN', short
    ? {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}
    : {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});
}

function filterQuery({batchId, days}: UsageFilters) {
  const query = new URLSearchParams();
  if (batchId) query.set('batch_id', batchId);
  if (days) query.set('days', days);
  return query.size ? '?' + query.toString() : '';
}

/** A single in-flight request per scope; late responses never overwrite a new filter. */
function useUsage(filters: UsageFilters) {
  const query = filterQuery(filters);
  const [state, setState] = useState<UsageState>({key: '', report: null, error: '', refreshing: false});
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function load() {
      setState(previous => ({key: query, report: previous.key === query ? previous.report : null, error: '', refreshing: true}));
      try {
        const response = await fetch('/api/usage' + query, {signal: controller.signal, cache: 'no-store'});
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === 'string' ? body.detail : `读取用量失败（HTTP ${response.status}）`);
        }
        const report = await response.json() as UsageReport;
        if (!report?.summary || !Array.isArray(report.models)) throw new Error('用量响应格式不正确，请稍后重试。');
        if (!stopped) setState({key: query, report, error: '', refreshing: false});
      } catch (error) {
        if (!stopped && !controller.signal.aborted) {
          setState(previous => ({key: query, report: previous.key === query ? previous.report : null, error: error instanceof Error ? error.message : '读取用量失败，请稍后重试。', refreshing: false}));
        }
      } finally {
        if (!stopped) timer = setTimeout(load, 5000);
      }
    }
    void load();
    return () => {stopped = true; controller.abort(); if (timer) clearTimeout(timer);};
  }, [query, refresh]);
  const current = state.key === query ? state : {key: query, report: null, error: '', refreshing: true};
  return {...current, reload: () => setRefresh(value => value + 1), query};
}

type MetricDefinition = {field: keyof UsageSummary; title: string; unit: string; kind: UsageKind; detail: string};
const metricDefinitions: MetricDefinition[] = [
  {field: 'text_tokens', title: '文本 Token', unit: 'Token', kind: 'text', detail: '脚本策划与结构化分镜'},
  {field: 'image_tokens', title: '图片 Token', unit: 'Token', kind: 'image', detail: '分镜图片生成'},
  {field: 'video_tokens', title: '视频 Token', unit: 'Token', kind: 'video', detail: '镜头片段生成'},
  {field: 'speech_characters', title: '配音计费字符', unit: '字符', kind: 'speech', detail: '供应商返回的计费字符数'},
];

function UsageMetrics({summary, compact = false}: {summary: UsageSummary; compact?: boolean}) {
  return <div className={'usage-metrics' + (compact ? ' is-compact' : '')} aria-label="按模型用途统计的实际用量">
    {metricDefinitions.map(metric => {
      const Icon = kindIcons[metric.kind];
      const value = summary[metric.field];
      return <div className={'usage-metric ' + metric.kind} key={metric.kind}>
        <div className="usage-metric-heading"><span>{metric.title}</span><span className="usage-metric-icon"><Icon size={compact ? 15 : 18}/></span></div>
        <div className={'usage-metric-value' + (value == null ? ' unreported' : '')}><strong>{formatValue(value)}</strong>{value != null && <span>{metric.unit}</span>}</div>
        {!compact && <p>{metric.detail}</p>}
      </div>;
    })}
  </div>;
}

function UsageCoverage({summary, compact = false}: {summary: UsageSummary; compact?: boolean}) {
  const ratio = summary.calls > 0 ? Math.min(100, Math.max(0, summary.reported_calls / summary.calls * 100)) : 0;
  return <div className={'usage-coverage' + (compact ? ' compact' : '')}>
    <div className="usage-coverage-heading"><span><CheckCheck size={14}/>用量上报覆盖</span><b>{summary.reported_calls}<span> / {summary.calls} 条调用</span></b></div>
    <div className="usage-coverage-track" role="meter" aria-label="有供应商用量的调用占比" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio)}><span style={{width: ratio + '%'}}/></div>
    {!compact && <p>{summary.calls === 0 ? '当前范围尚无真实模型调用。' : summary.missing_usage_calls > 0 ? `${numberFormat.format(summary.missing_usage_calls)} 条调用尚无供应商用量，未上报不代表零消耗。` : '当前范围内的调用均有供应商用量记录。'}</p>}
  </div>;
}

function CallCounts({summary}: {summary: UsageSummary}) {
  return <div className="usage-call-counts" aria-label="实际调用统计">
    <span><Activity size={14}/>调用记录 <b>{formatValue(summary.calls)}</b></span>
    <span>实际请求 <b>{formatValue(summary.attempts)}</b></span>
    <span>已受理记录 <b>{formatValue(summary.succeeded_calls)}</b></span>
    <span className={summary.failed_calls > 0 ? 'has-failed' : ''}>当前失败记录 <b>{formatValue(summary.failed_calls)}</b></span>
    <span>待执行 / 响应 <b>{formatValue(summary.pending_calls)}</b></span>
    <span className={summary.uncertain_calls > 0 ? 'has-uncertain' : ''}>待确认 <b>{formatValue(summary.uncertain_calls)}</b></span>
  </div>;
}

function ModelMeasurements({model}: {model: UsageModel}) {
  let measurements: {label: string; value: number | null; unit?: string}[];
  if (model.kind === 'speech') {
    measurements = [{label: '计费字符', value: model.speech_characters, unit: '字符'}, {label: '音频时长', value: model.audio_seconds, unit: '秒'}];
  } else if (model.kind === 'image') {
    measurements = [{label: '上报 Token', value: model.total_tokens}, {label: '生成图片', value: model.generated_images, unit: '张'}];
  } else if (model.kind === 'video') {
    measurements = [{label: '上报 Token', value: model.total_tokens}, {label: '输出 Token', value: model.output_tokens}];
  } else {
    measurements = [{label: '上报 Token', value: model.total_tokens}, {label: '输入 / 输出', value: null}];
  }
  return <div className="usage-measurements">
    {measurements.map(item => <div key={item.label}><span>{item.label}</span><b className={item.value == null && item.label !== '输入 / 输出' ? 'unreported' : ''}>{item.label === '输入 / 输出' ? `${formatValue(model.input_tokens)} / ${formatValue(model.output_tokens)}` : formatValue(item.value)}{item.value != null && item.unit && <small>{item.unit}</small>}</b></div>)}
    {model.kind === 'text' && <p>缓存 {formatValue(model.cached_tokens)} · 思考 {formatValue(model.reasoning_tokens)}</p>}
  </div>;
}

function ModelTable({models}: {models: UsageModel[]}) {
  return <div className="usage-model-table-wrap"><table className="usage-model-table">
    <thead><tr><th scope="col">用途与模型接入点</th><th scope="col">调用 / 实际请求</th><th scope="col">供应商上报用量</th><th scope="col">用量覆盖</th><th scope="col">最近调用</th></tr></thead>
    <tbody>{models.map(model => {
      const Icon = kindIcons[model.kind] ?? Activity;
      return <tr key={[model.provider, model.kind, model.model].join(':')}>
        <td data-label="用途与接入点"><div className="usage-model-identity"><span className={'usage-model-icon ' + model.kind}><Icon size={17}/></span><div><div><b>{kindLabels[model.kind] ?? model.kind}</b><span>{providerLabels[model.provider] ?? model.provider}</span></div>{!!model.reported_models?.length && <p className="usage-reported-model" title="供应商明确返回的模型名称">{model.reported_models.join(' · ')}</p>}<code title={model.model}>{model.model || '未记录模型标识'}</code></div></div></td>
        <td data-label="调用 / 实际请求"><div className="usage-model-calls"><b>{formatValue(model.calls)}<span> / {formatValue(model.attempts)}</span></b><p>当前失败 {model.failed_calls} · 待确认 {model.uncertain_calls}</p></div></td>
        <td data-label="供应商上报用量"><ModelMeasurements model={model}/></td>
        <td data-label="用量覆盖"><div className="usage-model-coverage"><b>{model.reported_calls}<span> / {model.calls} 条</span></b><small>{model.missing_usage_calls > 0 ? `${model.missing_usage_calls} 条未上报` : '已上报'}</small></div></td>
        <td data-label="最近调用"><span className="usage-last-called">{formatTime(model.last_called)}</span></td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function UsageError({error, hasReport, onRetry}: {error: string; hasReport: boolean; onRetry: () => void}) {
  return <div className="usage-error" role="alert"><CircleAlert size={17}/><div><b>{hasReport ? '自动更新暂未成功' : '用量数据暂时无法读取'}</b><p>{error}{hasReport ? ' 当前保留上一次成功读取的数据。' : ''}</p></div><button className="button secondary compact" onClick={onRetry}>重试</button></div>;
}

function UsageLoading() {
  return <div className="usage-loading" role="status"><LoaderCircle size={22} className="spin"/><div><b>正在读取模型用量</b><p>从实际调用记录汇总供应商返回的数据。</p></div></div>;
}

function UsageEmpty() {
  return <div className="usage-empty"><span><ChartNoAxesCombined size={27}/></span><h3>当前范围暂无真实模型调用</h3><p>真实生成产生调用后，将在这里显示各模型用量。<br/>演示素材不会计入真实消耗。</p></div>;
}

function UsageNotes({compact = false}: {compact?: boolean}) {
  return <div className={'usage-note' + (compact ? ' compact' : '')}><Info size={15}/><p>依据供应商实际返回统计，未上报不代表零；Token、图片张数与配音字符分别记录，不能直接视为费用。{!compact && <><br/>包含重做、旧修订和失败调用中已上报的用量。实际请求统计 POST 提交尝试，含限流重试，不含状态轮询和素材下载，用量不按重试次数倍增；状态按调用记录当前提交状态统计，缓存与思考 Token 是输入 / 输出的子项。</>}</p></div>;
}

export function UsageWorkspace({batches}: {batches: {id: string; theme: string; mode?: string}[]}) {
  const [batchId, setBatchId] = useState('');
  const [days, setDays] = useState('');
  const {report, error, refreshing, reload, query} = useUsage({batchId, days});
  const summary = report?.summary;
  const sortedModels = useMemo(() => report ? [...report.models].sort((a, b) => {
    const order: UsageKind[] = ['text', 'image', 'video', 'speech'];
    return order.indexOf(a.kind) - order.indexOf(b.kind) || b.calls - a.calls || a.model.localeCompare(b.model);
  }) : [], [report]);
  return <div className="usage-workspace">
    <div className="page-heading"><div><div className="eyebrow">PRODUCTION / MODEL USAGE</div><h1>模型用量</h1><p>核对每个项目的实际模型调用，分别查看文本、图片、视频和配音消耗。</p></div><div className="heading-actions"><button className="button secondary" onClick={reload} disabled={refreshing}><RefreshCw size={15} className={refreshing ? 'spin' : ''}/>刷新数据</button><a className="button dark" href={'/api/usage/export.csv' + query} download><ArrowDownToLine size={15}/>导出 CSV</a></div></div>
    <section className="usage-filter-panel" aria-label="用量筛选"><div className="usage-filters"><label>统计项目<select aria-label="用量统计项目" value={batchId} onChange={event => setBatchId(event.target.value)}><option value="">全部项目</option>{batches.map(batch => <option key={batch.id} value={batch.id}>{batch.theme} · {batch.mode === 'live' ? '真实' : batch.mode === 'demo' ? '演示' : '模式未记录'} · {batch.id.slice(0, 6)}</option>)}</select></label><label>调用时间<select aria-label="用量调用时间" value={days} onChange={event => setDays(event.target.value)}><option value="">全部时间</option><option value="7">近 7 天</option><option value="30">近 30 天</option></select></label></div><div className="usage-sync"><span className={error ? 'has-error' : ''}><i/>{error ? '更新异常' : refreshing ? '正在更新' : '每 5 秒自动更新'}</span>{report && <small><Clock3 size={11}/>更新于 {formatTime(report.generated_at, true)}</small>}</div></section>
    {error && <UsageError error={error} hasReport={!!report} onRetry={reload}/>}
    {!report && !error && <UsageLoading/>}
    {summary && <>
      <UsageMetrics summary={summary}/>
      <div className="usage-summary-strip"><CallCounts summary={summary}/><UsageCoverage summary={summary}/></div>
      <section className="usage-model-panel"><div className="usage-section-heading"><div><h2>各模型用量明细</h2><p>按供应商、用途和实际模型标识分别汇总。</p></div><span>{sortedModels.length} 个接入点</span></div>{summary.calls === 0 ? <UsageEmpty/> : <ModelTable models={sortedModels}/>}</section>
      <UsageNotes/>
    </>}
  </div>;
}

export function BatchUsage({batchId}: {batchId: string}) {
  const {report, error, refreshing, reload, query} = useUsage({batchId});
  return <section className="usage-batch-panel" aria-label="本项目模型用量">
    <div className="usage-section-heading"><div><h2><ChartNoAxesCombined size={17}/>本项目模型用量</h2><p>包括本项目所有视频、重做记录与旧修订的实际调用。</p></div><button className="usage-refresh-button" aria-label="刷新本项目用量" title="刷新用量" onClick={reload} disabled={refreshing}><RefreshCw size={15} className={refreshing ? 'spin' : ''}/></button></div>
    {error && <UsageError error={error} hasReport={!!report} onRetry={reload}/>}
    {!report && !error && <UsageLoading/>}
    {report && <>
      <UsageMetrics summary={report.summary} compact/>
      <div className="usage-batch-summary"><CallCounts summary={report.summary}/><UsageCoverage summary={report.summary} compact/></div>
      {report.summary.calls > 0 ? <details className="usage-batch-details"><summary><span>查看各模型明细 <small>{report.models.length} 个接入点</small></span><ChevronDown size={15}/></summary><ModelTable models={report.models}/><div className="usage-batch-export"><span>更新于 {formatTime(report.generated_at, true)}</span><a href={'/api/usage/export.csv' + query} download><ArrowDownToLine size={13}/>导出本项目 CSV</a></div></details> : <p className="usage-batch-empty">暂无真实模型调用，演示素材不计入消耗。</p>}
      <UsageNotes compact/>
    </>}
  </section>;
}
