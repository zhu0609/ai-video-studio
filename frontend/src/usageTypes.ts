export type UsageKind = 'text' | 'image' | 'video' | 'speech';

/** Null means that the supplier did not report this metric. */
export type UsageSummary = {
  calls: number;
  attempts: number;
  succeeded_calls: number;
  failed_calls: number;
  pending_calls: number;
  uncertain_calls: number;
  reported_calls: number;
  missing_usage_calls: number;
  token_reported_calls: number;
  total_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  reasoning_tokens: number | null;
  generated_images: number | null;
  speech_characters: number | null;
  audio_seconds: number | null;
  text_tokens: number | null;
  image_tokens: number | null;
  video_tokens: number | null;
};

export type UsageModel = UsageSummary & {
  provider: string;
  kind: UsageKind;
  model: string;
  /** Only names explicitly returned by a provider; configured endpoint is `model`. */
  reported_models?: string[];
  last_called: string | number | null;
};

export type UsageReport = {
  scope: {
    batch_id: string | null;
    video_id: string | null;
    days: number | null;
    since: string | number | null;
  };
  summary: UsageSummary;
  models: UsageModel[];
  generated_at: string | number;
};
