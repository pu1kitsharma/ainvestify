"""Print safe public-research configuration status without making model calls."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.inference.runtime_status import public_runtime_status

if __name__ == '__main__':
    print(json.dumps(public_runtime_status(),indent=2))
