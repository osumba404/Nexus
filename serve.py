#!/usr/bin/env python
"""
Production server for Epicenter Nexus — Waitress multi-process launcher.

Usage:
    python serve.py                          # 3 workers, 8 threads each, ports 8001-8003
    python serve.py --workers 5 --threads 12
    python serve.py --port 9001              # starting port
"""
import os
import sys
import signal
import argparse
import multiprocessing
import time

DEFAULT_HOST    = '127.0.0.1'
DEFAULT_PORT    = 8001
DEFAULT_WORKERS = 3
DEFAULT_THREADS = 8


def _run_worker(host: str, port: int, threads: int, settings_module: str) -> None:
    """Target function executed in each worker process."""
    os.environ['DJANGO_SETTINGS_MODULE'] = settings_module

    # Enable SQLite WAL mode for better concurrent read performance
    try:
        import django
        django.setup()
        from django.db import connection
        connection.cursor().execute('PRAGMA journal_mode=WAL;')
        connection.cursor().execute('PRAGMA synchronous=NORMAL;')
        connection.cursor().execute('PRAGMA cache_size=10000;')
        connection.cursor().execute('PRAGMA temp_store=MEMORY;')
        connection.close()
    except Exception as exc:
        print(f'[Nexus:{port}] WAL pragma warning: {exc}', flush=True)

    try:
        from waitress import serve
        from nexus.wsgi import application
    except ImportError as exc:
        print(f'[Nexus:{port}] Import error: {exc}')
        print('  Run: pip install waitress')
        sys.exit(1)

    print(f'[Nexus] Worker :{port} ready — {threads} threads', flush=True)
    serve(
        application,
        host=host,
        port=port,
        threads=threads,
        channel_timeout=30,
        cleanup_interval=10,
        connection_limit=1000,
        max_request_header_size=16384,
        max_request_body_size=10 * 1024 * 1024,  # 10 MB
        asyncore_use_poll=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Start Epicenter Nexus production server',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--host',     default=DEFAULT_HOST,    help='Bind host (use 127.0.0.1 behind Nginx)')
    parser.add_argument('--port',     default=DEFAULT_PORT,    type=int, help='Starting port (workers use port, port+1, …)')
    parser.add_argument('--workers',  default=DEFAULT_WORKERS, type=int, help='Number of worker processes')
    parser.add_argument('--threads',  default=DEFAULT_THREADS, type=int, help='Threads per worker process')
    parser.add_argument('--settings', default='nexus.settings', help='Django settings module')
    args = parser.parse_args()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', args.settings)

    # Collect static files in production
    if not os.environ.get('SKIP_COLLECTSTATIC'):
        try:
            import django
            django.setup()
            from django.core.management import call_command
            print('[Nexus] Collecting static files…', flush=True)
            call_command('collectstatic', '--noinput', '--clear', verbosity=0)
            print('[Nexus] Static files collected.', flush=True)
        except Exception as exc:
            print(f'[Nexus] collectstatic warning: {exc}', flush=True)

    procs = []
    for i in range(args.workers):
        port = args.port + i
        p = multiprocessing.Process(
            target=_run_worker,
            args=(args.host, port, args.threads, args.settings),
            name=f'nexus-{port}',
            daemon=True,
        )
        p.start()
        procs.append((port, p))
        time.sleep(0.2)   # stagger startup to avoid port conflicts

    port_range = f'{args.port}–{args.port + args.workers - 1}'
    print(
        f'\n[Nexus] {args.workers} workers running on {args.host}:{port_range} '
        f'({args.threads} threads each).\n'
        f'[Nexus] Point Nginx upstream at these ports.\n'
        f'[Nexus] Press Ctrl+C to stop all workers.\n',
        flush=True,
    )

    def _shutdown(sig, frame):
        print('\n[Nexus] Shutting down…', flush=True)
        for _, p in procs:
            p.terminate()
        for _, p in procs:
            p.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Monitor workers — restart any that die unexpectedly
    while True:
        time.sleep(5)
        for idx, (port, p) in enumerate(procs):
            if not p.is_alive():
                print(f'[Nexus] Worker :{port} died (exit {p.exitcode}) — restarting…', flush=True)
                new_p = multiprocessing.Process(
                    target=_run_worker,
                    args=(args.host, port, args.threads, args.settings),
                    name=f'nexus-{port}',
                    daemon=True,
                )
                new_p.start()
                procs[idx] = (port, new_p)


if __name__ == '__main__':
    multiprocessing.freeze_support()   # Windows: required for frozen executables
    main()
