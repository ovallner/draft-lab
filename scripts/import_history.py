#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.history import build_history

if __name__ == '__main__':
    package = build_history()
    print(package['report']['coverage'])
    print('Validation:', package['validation']['metrics'])
    print('Default model:', package['validation']['decision'])
