import { BENCHMARK_MODES, type BenchmarkMetrics, type BenchmarkMode } from '../../api/types';

export function categoryWinner(modes: Record<BenchmarkMode, BenchmarkMetrics>): BenchmarkMode {
  return BENCHMARK_MODES.reduce((winner, mode) => {
    const score = (candidate: BenchmarkMode) => {
      const metrics = modes[candidate];
      return metrics.schema_pass_rate * 0.5 + metrics.field_f1 * 0.3 + metrics.stream_stability_rate * 0.2;
    };
    return score(mode) > score(winner) ? mode : winner;
  }, BENCHMARK_MODES[0]);
}
