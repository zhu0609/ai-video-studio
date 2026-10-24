export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, {
    ...init,
    headers: {'Content-Type': 'application/json', ...init?.headers},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({detail: response.statusText}));
    throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  }
  return response.json();
}

export const send = (body: unknown): RequestInit => ({
  method: 'POST',
  body: JSON.stringify(body),
});
