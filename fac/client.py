#!/usr/bin/env python3
"""
'''
`fac` is a build system for LLM-based agentic projects.
'''

from dataclasses import fields
import typing
import requests


def main():
    import fac.Config
    import fac.Fac
    import argcomplete
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*').completer = fac.Config.fac_targets_completer
    parser.add_argument('--config-file', default='fac.yaml')
    parser.add_argument('--server', default="http://127.0.0.1:8000")
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--include-prompt', type=str, default=None)
    parser.add_argument('--include-old', action='store_true')
    
    argcomplete.autocomplete(parser)
    args = parser.parse_args()
    
    # Add targets
    for target in args.targets:
        r = requests.post(f"{args.server}/add_target", params={
            "target": target,
            #"overwrite": args.overwrite,
            #"include_prompt": args.include_prompt,
            #"include_old": args.include_old,
        })
        print(r.status_code, r.text)
        r.raise_for_status()
    
    # Build
    r = requests.post(f"{args.server}/build_all")
    r.raise_for_status()
    #print(f"Built: {r.json()['built_paths']}")

if __name__ == '__main__':
    main()
"""

from dataclasses import fields
import typing
import requests
import threading


def stream_logs(server: str, stop_event: threading.Event):
    """Stream logs from server until stop_event is set."""
    try:
        with requests.get(f"{server}/logs/stream", stream=True, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if stop_event.is_set():
                    break
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        print(line[6:])
    except requests.exceptions.RequestException:
        pass  # Server closed or connection lost


def main():
    import fac.Config
    import fac.Fac
    import argcomplete
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*').completer = fac.Config.fac_targets_completer
    parser.add_argument('--config-file', default='fac.yaml')
    parser.add_argument('--server', default="http://127.0.0.1:8000")
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--include-prompt', type=str, default=None)
    parser.add_argument('--include-old', action='store_true')

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    # Start log streaming in background thread
    stop_event = threading.Event()
    log_thread = threading.Thread(target=stream_logs, args=(args.server, stop_event), daemon=True)
    log_thread.start()

    try:
        # Add targets
        for target in args.targets:
            r = requests.post(f"{args.server}/add_target", params={
                "target": target,
                #"overwrite": args.overwrite,
                #"include_prompt": args.include_prompt,
                #"include_old": args.include_old,
            })
            print(r.status_code, r.text)
            r.raise_for_status()

        # Build
        r = requests.post(f"{args.server}/build_all")
        r.raise_for_status()
        #print(f"Built: {r.json()['built_paths']}")
    finally:
        stop_event.set()
        log_thread.join(timeout=1.0)

if __name__ == '__main__':
    main()
