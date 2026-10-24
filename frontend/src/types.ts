import type {UsageReport} from './usageTypes';

export type Shot = {
  id: string;
  position: number;
  duration: number;
  narration: string;
  prompt: string;
  image: string | null;
  clip: string | null;
  audio: string | null;
  image_status: string;
  clip_status: string;
  task_id: string | null;
  error: string;
};

export type Call = {
  id: string;
  provider: string;
  kind: string;
  model: string;
  attempts: number;
  state: string;
  usage: unknown;
  error: string;
  task_id: string | null;
};

export type Video = {
  id: string;
  number: number;
  title: string;
  status: string;
  revision: number;
  active_job: string | null;
  output: string | null;
  error: string;
  shots: Shot[];
  calls: Call[];
  usage_summary?: Pick<UsageReport, 'summary' | 'models'>;
};

export type Batch = {
  id: string;
  theme: string;
  brief: string;
  duration: number;
  count: number;
  ratio: string;
  style: string;
  voice: boolean;
  subtitles: boolean;
  auto: boolean;
  mode: string;
  created: number;
  videos: Video[];
  image_provider?: string;
  workflow_id?: string | null;
  reference_image?: string | null;
  seed?: number;
  comfy_workflow?: {id: string; name: string} | null;
};

export type Health = {
  execution_mode: string;
  database: string;
  ffmpeg: boolean;
  missing_config: string[];
  demo_notice: string;
  providers: Record<string, string>;
};
