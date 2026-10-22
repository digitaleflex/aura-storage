/**
 * Sliding-window throughput. Average rate over the last `windowMs`, from
 * (time, cumulative bytes) samples, so pauses, files already on the server and
 * server-side verification time do not drag the figure down the way
 * "bytes / time since the start" does.
 */
export class ThroughputWindow {
  private samples: Array<{ at: number; bytes: number }> = [];

  constructor(private readonly windowMs = 20_000) {}

  reset(): void {
    this.samples = [];
  }

  push(at: number, bytes: number): void {
    const last = this.samples[this.samples.length - 1];
    // A restart (retry, new batch) can lower the cumulative count: start over.
    if (last && bytes < last.bytes) this.samples = [];
    this.samples.push({ at, bytes });
    const cutoff = at - this.windowMs;
    while (this.samples.length > 2 && this.samples[1]!.at <= cutoff) this.samples.shift();
  }

  /** Bytes per second, or 0 until the window spans at least one second of progress. */
  rate(): number {
    const first = this.samples[0];
    const last = this.samples[this.samples.length - 1];
    if (!first || !last) return 0;
    const seconds = (last.at - first.at) / 1000;
    if (seconds < 1 || last.bytes <= first.bytes) return 0;
    return (last.bytes - first.bytes) / seconds;
  }
}
