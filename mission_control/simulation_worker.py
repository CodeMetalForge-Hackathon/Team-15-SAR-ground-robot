"""Private child process. Its only backend is the simulated fleet."""
import json
import os
import tempfile
from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'team15_starter'))
    from fleet.web import Dashboard
    original_start = Dashboard.start

    def start(dashboard):
        dashboard.host = '127.0.0.1'
        result = original_start(dashboard)
        print(json.dumps({'port': dashboard.server.server_port}), flush=True)
        sys.stdout = sys.stderr
        return result

    Dashboard.start = start
    import homebase
    sys.argv = ['homebase.py', '--sim', '--web', '--web-port', '0', '--quiet']
    with tempfile.TemporaryDirectory(prefix="team15-sim-") as work:
        os.chdir(work)
        homebase.main()


if __name__ == '__main__':
    main()
