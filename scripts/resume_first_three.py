#!/usr/bin/env python3
"""Recovery supervisor; uses unchanged, hash-verified frozen experiment code.

Supervising threads each launch one fresh Python child per task. Scientific
code, seed derivation, policy selection, and task checkpoints stay unchanged.
"""
import argparse
import fcntl
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FROZEN_SOURCE = None


def isolated_task(task):
    path = Path(task['out'])
    if path.exists():
        return json.loads(path.read_text())
    request = path.with_suffix('.request')
    request.write_text(json.dumps(task))
    log = path.with_suffix('.worker.log')
    command = [sys.executable, '-B', str(Path(__file__).resolve()),
               '--source', str(FROZEN_SOURCE), '--task', str(request)]
    for attempt in range(2):
        with log.open('ab') as handle:
            try:
                proc = subprocess.run(command, cwd=FROZEN_SOURCE, stdout=handle,
                                      stderr=subprocess.STDOUT, timeout=900)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = -999
        if code == 0 and path.exists():
            return json.loads(path.read_text())
        # A terminated child can restart once from its atomic checkpoint. Ordinary
        # Python errors fail visibly rather than being repeatedly hidden/retried.
        if code >= 0 or attempt:
            raise RuntimeError(f'Task child exited {code}; see {log}')
        with log.open('a') as handle:
            handle.write(f'\nSupervisor: retrying terminated child ({code}) from checkpoint.\n')
    raise RuntimeError('Unreachable task state')


def main():
    global FROZEN_SOURCE
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path, nargs='?')
    ap.add_argument('--source', type=Path)
    ap.add_argument('--task', type=Path)
    ap.add_argument('--workers', type=int, choices=(1, 2), default=1)
    ap.add_argument('--recover-stale', action='store_true',
                    help='Recover an abandoned running status only after obtaining the exclusive run lock.')
    args = ap.parse_args()
    if args.task:
        sys.path.insert(0, str(args.source / 'scripts'))
        from overnight_core import execute_task
        execute_task(json.loads(args.task.read_text()))
        return
    if args.run is None:
        ap.error('run directory required')
    run = args.run.resolve()
    cfg = json.loads((run / 'run.json').read_text())
    FROZEN_SOURCE = Path(cfg['source'])
    sys.path.insert(0, str(FROZEN_SOURCE / 'scripts'))
    import run_first_three_overnight as frozen
    from overnight_core import atomic
    from overnight_report import publish
    assert Path(frozen.__file__).resolve().is_relative_to(FROZEN_SOURCE)
    lock = (run / 'run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    runner = frozen.Runner(run)
    runner.verify()
    old_status = json.loads((run / 'progress.json').read_text())
    if old_status['stage'] == 'complete':
        raise ValueError('Run already complete')
    if old_status['stage'] not in ('failed', 'interrupted') and not args.recover_stale:
        raise ValueError('Recovery requires failed/interrupted status; refusing duplicate or completed run')
    remaining = max(0, cfg['budget_seconds'] - old_status['elapsed_seconds'])
    if remaining < 180:
        raise ValueError('Original wall budget exhausted')
    audit = {'resumed_epoch': time.time(), 'prior_status': old_status,
             'prior_runtime_config': cfg, 'remaining_seconds': remaining,
             'workers': args.workers, 'task_process_lifetime': 'one task',
             'recovered_abandoned_status': args.recover_stale,
             'retry': 'one retry for signal termination or 900-second timeout; checkpoint reuse',
             'scientific_source_changed': False,
             'supervisor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    atomic(run / ('recovery-' + str(int(audit['resumed_epoch'])) + '.json'), audit)
    runner.start = time.time()
    runner.deadline = runner.start + remaining
    runner.workers = args.workers
    runner.cfg.update(started_epoch=runner.start, resumed_epoch=runner.start,
                      budget_seconds=remaining, workers=args.workers)
    atomic(run / 'run.json', runner.cfg)
    runner.executor = ThreadPoolExecutor(max_workers=args.workers)
    frozen.execute_task = isolated_task
    signal.signal(signal.SIGTERM, frozen.interrupt)
    signal.signal(signal.SIGINT, frozen.interrupt)
    runner.log('recovery_started', remaining_seconds=remaining, workers=args.workers,
               fresh_process_per_task=True, scientific_source_changed=False)
    stopped = threading.Event()
    def heartbeat():
        while not stopped.is_set():
            row = {'epoch': time.time(), 'pid': os.getpid(), 'workers': args.workers,
                   'deadline_epoch': runner.deadline,
                   'supervisor_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            atomic(run / 'heartbeat.json', row)
            with (run / 'heartbeat.log').open('a') as handle:
                handle.write(json.dumps(row) + '\n')
            stopped.wait(30)
    monitor = threading.Thread(target=heartbeat, daemon=True)
    monitor.start()
    try:
        runner.run_all()
    except Exception:
        error = traceback.format_exc()
        runner.log('recovery_failed', traceback=error)
        runner.status('failed', error=error)
        publish(run, 'Stopped — partial results; inspect progress.log')
        raise
    finally:
        runner.executor.shutdown(wait=True, cancel_futures=True)
        stopped.set()
        monitor.join(timeout=5)
        lock.close()


if __name__ == '__main__':
    main()
