"""
AUTO-UPDATER SERVER-SIDE IMPLEMENTATION

This module provides real-time file change notifications to web clients using Server-Sent Events (SSE)
and filesystem watching via the watchdog library.

WHAT IS WORKING:
- Basic file modification detection and client notification
- Server-Sent Events (SSE) communication with clients
- Client subscription/unsubscription to specific file paths
- File deletion detection
- Multiple client support with proper cleanup on disconnect

FIXME: This implementation is not horizontally scalable. All state (client connections, subscriptions,
file watchers) is stored in memory within the Flask process. In a multi-server deployment, clients
would only receive notifications from the specific server instance they're connected to, and file
changes on other servers would not be detected. For production use, this would need to be redesigned
with external state storage (Redis, database) and inter-server communication.

FIXME: Client ID generation is not cryptographically secure. Currently uses predictable counters
and timestamps (f"client_{counter}_{timestamp}"). In a security-sensitive environment, this could
allow client impersonation or prediction of client IDs. Should use cryptographically secure random
generation (e.g., secrets.token_urlsafe()).

FIXME: No authentication or authorization. Any client can subscribe to watch any file path on the
server filesystem. This could be a security risk in production environments.
"""

from flask import Blueprint, render_template, abort, request, jsonify, send_file
from flask import Response
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import json
import os
import queue
import threading
import time

bp = Blueprint('auto_updater', __name__, template_folder='.')

# Global state for auto_updater
auto_updater_clients = {}  # client_id -> queue
auto_updater_subscriptions = {}  # path -> set of client_ids
auto_updater_observer = None  # Single recursive observer
auto_updater_lock = threading.Lock()
auto_updater_next_client_id = 1


class AutoUpdaterHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()

    def on_modified(self, event):
        if not event.is_directory:
            self.notify_clients('file_updated', event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.notify_clients('file_deleted', event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self.notify_clients('file_updated', event.src_path)

    def notify_clients(self, event_type, file_path):
        # Convert absolute path back to URL path
        rel_path = os.path.relpath(file_path, os.getcwd())
        url_path = '/' + rel_path.replace(os.sep, '/')

        with auto_updater_lock:
            if url_path in auto_updater_subscriptions:
                message = {
                    'type': event_type,
                    'path': url_path,
                    'timestamp': time.time()
                }

                for client_id in list(auto_updater_subscriptions[url_path]):
                    if client_id in auto_updater_clients:
                        try:
                            auto_updater_clients[client_id]['queue'].put_nowait(message)
                        except queue.Full:
                            cleanup_client(client_id)
                    else:
                        auto_updater_subscriptions[url_path].discard(client_id)

def cleanup_client(client_id):
    """Remove client and clean up subscriptions"""
    with auto_updater_lock:
        if client_id in auto_updater_clients:
            del auto_updater_clients[client_id]

        # Remove client from all subscriptions
        for path in list(auto_updater_subscriptions.keys()):
            if client_id in auto_updater_subscriptions[path]:
                auto_updater_subscriptions[path].discard(client_id)
                if not auto_updater_subscriptions[path]:
                    del auto_updater_subscriptions[path]

def ensure_global_watcher():
    """Ensure the global recursive watcher is running."""
    global auto_updater_observer

    if auto_updater_observer is None:
        auto_updater_observer = Observer()
        auto_updater_observer.schedule(AutoUpdaterHandler(), os.getcwd(), recursive=True)
        auto_updater_observer.start()

@bp.route('/api/auto_updater/events')
def auto_updater_events():
    def generate():
        global auto_updater_next_client_id

        with auto_updater_lock:
            client_id = f"client_{auto_updater_next_client_id}_{int(time.time())}"
            auto_updater_next_client_id += 1
            client_queue = queue.Queue(maxsize=100)
            auto_updater_clients[client_id] = {
                'queue': client_queue,
                'subscriptions': set()
            }

        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'client_id': client_id})}\n\n"

            while True:
                try:
                    message = client_queue.get(timeout=30)  # 30 second timeout
                    yield f"data: {json.dumps(message)}\n\n"
                except queue.Empty:
                    # Send heartbeat
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            cleanup_client(client_id)

    return Response(generate(), mimetype='text/event-stream')

@bp.route('/api/auto_updater/subscribe', methods=['POST'])
def auto_updater_subscribe():
    data = request.get_json()
    path = data.get('path')
    client_id = data.get('client_id')

    if not path:
        return jsonify({'success': False, 'error': 'Path required'}), 400

    if not client_id:
        return jsonify({'success': False, 'error': 'Client ID required'}), 400

    # Convert URL path to filesystem path for validation
    if path.startswith('/'):
        file_path = os.path.join(os.getcwd(), path.lstrip('/'))
    else:
        return jsonify({'success': False, 'error': 'Invalid path'}), 400

    with auto_updater_lock:
        if client_id not in auto_updater_clients:
            return jsonify({'success': False, 'error': 'Unknown client'}), 400

        if path not in auto_updater_subscriptions:
            auto_updater_subscriptions[path] = set()
        auto_updater_subscriptions[path].add(client_id)
        auto_updater_clients[client_id]['subscriptions'].add(path)

        # Ensure the global watcher is running
        ensure_global_watcher()

    return jsonify({'success': True})

@bp.route('/api/auto_updater/unsubscribe', methods=['POST'])
def auto_updater_unsubscribe():
    data = request.get_json()
    path = data.get('path')
    client_id = data.get('client_id')

    if not path or not client_id:
        return jsonify({'success': False, 'error': 'Path and client ID required'}), 400

    with auto_updater_lock:
        if path in auto_updater_subscriptions:
            auto_updater_subscriptions[path].discard(client_id)
            if not auto_updater_subscriptions[path]:
                del auto_updater_subscriptions[path]

        if client_id in auto_updater_clients:
            auto_updater_clients[client_id]['subscriptions'].discard(path)

    return jsonify({'success': True})
