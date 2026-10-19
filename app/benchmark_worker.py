"""Separate process so season batches don't block live pick recording."""
import argparse
import traceback
import fcntl
from pathlib import Path
from .benchmark import BenchmarkRunner,atomic_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    queue=(args.directory.parent/'.active.lock').open('a')
    job=(args.directory/'worker.lock').open('a')
    try:
        fcntl.flock(job,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        queue.close();job.close();return
    try:
        fcntl.flock(queue,fcntl.LOCK_EX|fcntl.LOCK_NB)
        BenchmarkRunner(args.directory).run()
    except Exception as exc:
        traceback.print_exc()
        atomic_json(args.directory/'status.json',{'state':'failed','error':str(exc),'run_id':args.directory.name})
    finally:queue.close();job.close()


if __name__=='__main__':main()
