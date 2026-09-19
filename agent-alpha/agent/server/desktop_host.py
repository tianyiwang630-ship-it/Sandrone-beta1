"""Desktop-owned backend launcher with OS-level lifetime guards."""
from __future__ import annotations

import argparse
import multiprocessing

from agent.core.windows_job import WindowsJob


def serve(connection):
    connection.recv()  # No backend initialization before ownership assignment.
    connection.close()
    from agent.server.app import main
    main()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-pid", type=int, required=True)
    args = parser.parse_args()
    application_job = WindowsJob()
    application_job.transfer_to_owner(args.owner_pid)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=serve, args=(child,))
    with WindowsJob() as backend_job:
        try:
            process.start()
            child.close()
            backend_job.assign(process.sentinel)
            parent.send("start")
            process.join()
        finally:
            backend_job.terminate()
            if process.pid is not None:
                process.join(timeout=2)
            parent.close()
    raise SystemExit(process.exitcode or 0)


if __name__ == "__main__":
    main()
