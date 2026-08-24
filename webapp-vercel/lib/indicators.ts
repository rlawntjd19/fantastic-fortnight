export function sma(values: number[], window: number): number | null {
  if (values.length < window) return null;
  const slice = values.slice(-window);
  return slice.reduce((a, b) => a + b, 0) / window;
}

export function rsi(values: number[], window = 14): number | null {
  if (values.length < window + 1) return null;
  const changes: number[] = [];
  for (let i = values.length - window; i < values.length; i++) changes.push(values[i] - values[i - 1]);
  const gains = changes.filter((c) => c > 0);
  const losses = changes.filter((c) => c < 0).map((c) => -c);
  const avgGain = gains.reduce((a, b) => a + b, 0) / window;
  const avgLoss = losses.reduce((a, b) => a + b, 0) / window;
  if (avgLoss === 0) return 100.0;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export function momentum(values: number[], window: number): number | null {
  if (values.length < window + 1) return null;
  const base = values[values.length - window - 1];
  if (base === 0) return null;
  return (values[values.length - 1] - base) / base;
}

export function sampleStdev(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / (values.length - 1));
}
