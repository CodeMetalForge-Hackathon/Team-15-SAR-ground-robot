"""Start a loopback-only coordinator and three SIMULATED device agents."""
import argparse
import secrets
import threading

from .adapters import Simulator
from .agent import Agent
from .protocol import NODES
from .server import make_server
from .state import Coordinator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    credentials = {role: secrets.token_urlsafe(32) for role in ('operator', *NODES)}
    state, stop = Coordinator(), threading.Event()
    server = make_server(state, credentials, port=args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    workers = []
    for node in NODES:
        agent = Agent(node, credentials[node], url, Simulator(node))
        worker = threading.Thread(target=agent.run, args=(stop,), daemon=True)
        workers.append(worker)
        worker.start()
    print(f'SIMULATED ONLY · {url}\nOperator token for this run: {credentials["operator"]}', flush=True)
    print('Paste token in the dashboard. Take control → Resume → Request action → Approve.', flush=True)
    try:
        # tick also runs on every sync, independently of the operator browser.
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        for worker in workers:
            worker.join(timeout=2)


if __name__ == '__main__':
    main()
