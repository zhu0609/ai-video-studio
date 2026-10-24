const labels: Record<string, string> = {
  queued: '排队中',
  planning: '策划中',
  review: '待审核',
  generating: '生成镜头',
  composing: '合成中',
  completed: '已完成',
  failed: '需处理',
  ready: '素材就绪',
  pending: '待生成',
  running: '处理中',
  done: '已完成',
  succeeded: '成功',
  uncertain: '待核实',
  submitted: '提交中',
};

export function Status({value}: {value: string}) {
  return <span className={'status ' + value}><i aria-hidden="true"/>{labels[value] || value}</span>;
}
