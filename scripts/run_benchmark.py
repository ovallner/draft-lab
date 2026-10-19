#!/usr/bin/env python3
"""Resume/reproduce a saved benchmark request without the browser."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.benchmark_worker import main

if __name__=='__main__':main()
