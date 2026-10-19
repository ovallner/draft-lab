#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.history3 import build

if __name__ == '__main__':
    package = build()
    for season, cov in package['report']['coverage'].items():
        print(season, cov)
    v = package['validation']
    print('decision:', v['decision'], '| pooled choice sets:', v['n_pooled_sets'])
    print("metrics:", {k: round(m["log_loss"], 4) for k, m in v["metrics"].items()})
    print('persona - baseline log loss:', round(v['persona_minus_baseline_log_loss'], 4),
          'interval', [round(x, 4) for x in v['round_bootstrap_95_interval']])
    for pair, r in v['cross_season'].items():
        print(f'  {pair} (test pool {r["test_pool"]}, n={r["n_test"]}): '
              f'baseline {r["baseline_log_loss"]:.4f} | global {r["global_log_loss"]:.4f} | '
              f'persona_pooled {r["persona_pooled_log_loss"]:.4f} | persona_manager {r["persona_manager_log_loss"]:.4f}')
