"""
FAC BUILD SYSTEM - SERVER SIDE

This Flask blueprint provides the backend API for triggering FAC builds from the web interface.
It integrates the fac.BuildSystem library with the FabulaMachina Flask application to enable
on-demand rebuilding of individual assets (images, audio, PDFs, etc.).

CONSOLE INTEGRATION:
The console system provides output to a "readonly" shell session. Standard use is to log 
commands with bash-style prompts ('$ command') followed by the exact output as it would 
appear in a terminal. This should be done for all API endpoints that run something 
equivalent to a shell command. Error output should be shown verbatim in red, success 
output should preserve original formatting without timestamps or additional annotations.
"""

import asyncio
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from io import StringIO

from flask import Blueprint, request, jsonify, Response

# Import the fac build system components
try:
    from fac.BuildSystem import BuildSystem, DirtyRepo, FACError
    from fac.Logging import logger as fac_logger, CustomFormatter
except ImportError as e:
    print(f"Error importing fac: {e}")
    print("Make sure fac is installed and accessible")
    raise

# Import console logging and git history functions
from routes.console_logging import (
    log_console_command, 
    log_console_output, 
    add_console_client, 
    remove_console_client,
    clear_console as clear_console_clients
)
from routes.console_logging import console_lock, console_clients

try:
    from routes.git_history import notify_history_clients
except ImportError:
    def notify_history_clients(event_type, data=None):
        pass

bp = Blueprint('fac', __name__)

# Global state for build management
active_builds = {}
build_lock = threading.Lock()

# Console client management
console_next_client_id = 1

class ConsoleLogHandler(logging.Handler):
    """Log handler that captures all FAC output for the console panel"""
    
    def __init__(self):
        super().__init__()
        self.setFormatter(CustomFormatter())
    
    def emit(self, record):
        try:
            formatted_msg = self.format(record)
            formatted_msg = self.convert_ansi_to_web(formatted_msg)
            
            # Send to console logging system with correct type
            if formatted_msg.startswith('$ '):
                message_type = 'console_command'
            else:
                message_type = 'console_output'
                
            # Send to console clients with proper message structure
            with console_lock:
                if not console_clients:
                    return
                    
                log_entry = {
                    'type': message_type,
                    'level': record.levelname.lower(),
                    'message': formatted_msg,
                    'timestamp': time.time()
                }
                
                for client_queue in console_clients.values():
                    try:
                        client_queue.put_nowait(log_entry)
                    except queue.Full:
                        pass
                        
        except Exception as e:
            print(f"[Console Log] Error: {e}")
    
    def convert_ansi_to_web(self, text):
        """Convert ANSI color codes to HTML-friendly format"""
        ansi_to_css = {
            '\033[31m': '<span class="ansi-red">',
            '\033[91m': '<span class="ansi-bright-red">',
            '\033[32m': '<span class="ansi-green">',
            '\033[33m': '<span class="ansi-yellow">',
            '\033[38;5;208m': '<span class="ansi-orange">',
            '\033[36m': '<span class="ansi-cyan">',
            '\033[35m': '<span class="ansi-magenta">',
            '\033[0m': '</span>',
        }
        
        for ansi_code, css_span in ansi_to_css.items():
            text = text.replace(ansi_code, css_span)
        
        return text

class BuildLogHandler(logging.Handler):
    """Custom logging handler that captures FAC build logs and queues them for SSE streaming"""

    def __init__(self, build_id):
        super().__init__()
        self.build_id = build_id
        self.log_queue = queue.Queue()
        self.setFormatter(CustomFormatter())

    def emit(self, record):
        try:
            formatted_msg = self.format(record)

            log_entry = {
                'type': 'log',
                'level': record.levelname,
                'message': formatted_msg,
                'raw_message': record.getMessage(),
                'timestamp': time.time()
            }
            self.log_queue.put_nowait(log_entry)
        except Exception as e:
            print(f"[FAC Build] Logging error: {e}")

# Add global console handler to capture all FAC logs
console_handler = ConsoleLogHandler()
fac_logger.addHandler(console_handler)

@bp.route('/api/fac/console/events')
def console_events():
    """Server-Sent Events for console log streaming"""
    def generate():
        global console_next_client_id
        
        client_id = f"console_client_{console_next_client_id}_{int(time.time())}"
        console_next_client_id += 1
        client_queue = queue.Queue(maxsize=1000)
        
        # Add client to shared console system
        add_console_client(client_id, client_queue)
        
        try:
            yield f"data: {json.dumps({'type': 'connected', 'client_id': client_id})}\n\n"
            
            while True:
                try:
                    message = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(message)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            remove_console_client(client_id)
    
    return Response(generate(), mimetype='text/event-stream')

@bp.route('/api/fac/console/clear', methods=['POST'])
def clear_console():
    """Clear console log for all clients"""
    clear_console_clients()
    return jsonify({'success': True})

@bp.route('/api/fac/build', methods=['POST'])
def trigger_build():
    """Main endpoint for triggering FAC builds"""
    global active_builds

    data = request.get_json()
    if not data or 'target' not in data:
        return jsonify({'error': 'Missing target parameter'}), 400

    target = data['target']
    overwrite = data.get('overwrite', False)
    notes = data.get('notes')

    # Build the equivalent fac command for console output
    fac_command = f"fac '{target}'"
    if overwrite:
        fac_command += " --overwrite"
    if notes:
        # Escape quotes in notes for display
        escaped_notes = notes.replace('"', '\\"')
        fac_command += f' --include_chat="{escaped_notes}"'
    
    # Log the command to console
    log_console_command(fac_command)

    with build_lock:
        # Check if a build is already in progress
        active_build_ids = [bid for bid, info in active_builds.items()
                          if info['status'] in ['queued', 'running']]

        if active_build_ids:
            error_msg = "A build is already in progress"
            log_console_output(f"fac: error: {error_msg}", 'error')
            return jsonify({
                'error': error_msg,
                'active_build_id': active_build_ids[0]
            }), 409

        # Create new build record
        build_id = str(uuid.uuid4())
        active_builds[build_id] = {
            'target': target,
            'overwrite': overwrite,
            'notes': notes,
            'status': 'queued',
            'created_at': time.time(),
            'log_handler': None
        }

    # Start build in background thread
    def run_build():
        build_info = None
        log_handler = None

        try:
            with build_lock:
                if build_id not in active_builds:
                    return

                active_builds[build_id]['status'] = 'running'
                log_handler = BuildLogHandler(build_id)
                active_builds[build_id]['log_handler'] = log_handler
                build_info = active_builds[build_id]

            # Configure build system
            build_system = BuildSystem(
                project_dir=os.getcwd(),
                overwrite=overwrite,
                include_chat=notes if notes else None,
                allow_dirty=True,
                auto_commit=True,
                print_dependencies=True,
            )
            log_handler.log_queue.put({
                'type': 'build_started',
                'target': target,
                'timestamp': time.time(),
                'display_type': 'permanent',
            })

            fac_logger.addHandler(log_handler)

            try:
                with build_system:
                    build_system.build_targets([target])

                with build_lock:
                    if build_id in active_builds:
                        active_builds[build_id]['status'] = 'completed'
                        log_handler.log_queue.put({
                            'type': 'build_completed',
                            'target': target,
                            'timestamp': time.time(),
                            'display_type': 'flash',
                        })

                # Notify git history of new commits
                try:
                    import git
                    repo = git.Repo(os.getcwd())
                    if repo.head.commit:
                        notify_history_clients('new_commit', {
                            'commit_hash': repo.head.commit.hexsha[:7],
                            'message': repo.head.commit.message.strip()
                        })
                except Exception as git_error:
                    print(f"Git notification error: {git_error}")

            except (FACError, DirtyRepo) as e:
                error_msg = str(e)
                log_console_output(error_msg, 'error')

                with build_lock:
                    if build_id in active_builds:
                        active_builds[build_id]['status'] = 'error'
                        active_builds[build_id]['error'] = error_msg
                        log_handler.log_queue.put({
                            'type': 'build_error',
                            'target': target,
                            'error': error_msg,
                            'timestamp': time.time(),
                            'display_type': 'permanent',
                        })

            except Exception as e:
                error_msg = str(e)
                log_console_output(f"Unexpected error: {error_msg}", 'error')

                with build_lock:
                    if build_id in active_builds:
                        active_builds[build_id]['status'] = 'error'
                        active_builds[build_id]['error'] = error_msg
                        log_handler.log_queue.put({
                            'type': 'build_error',
                            'target': target,
                            'error': error_msg,
                            'timestamp': time.time(),
                            'display_type': 'permanent',
                        })

            finally:
                if log_handler:
                    fac_logger.removeHandler(log_handler)

        except Exception as e:
            error_msg = f"Build setup error: {str(e)}"
            log_console_output(error_msg, 'error')

            with build_lock:
                if build_id in active_builds:
                    active_builds[build_id]['status'] = 'error'
                    active_builds[build_id]['error'] = error_msg

    build_thread = threading.Thread(target=run_build, daemon=True)
    build_thread.start()

    return jsonify({
        'build_id': build_id,
        'message': 'Build started',
        'target': target
    })

@bp.route('/api/fac/build/logs/<build_id>')
def build_logs(build_id):
    """Server-Sent Events endpoint for streaming real-time build logs"""
    def generate_logs():
        build_info = active_builds.get(build_id)
        if not build_info:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Build not found'})}\n\n"
            return

        log_handler = build_info.get('log_handler')
        if not log_handler:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Log handler not available'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'connected', 'build_id': build_id})}\n\n"

        last_heartbeat = time.time()
        while True:
            try:
                try:
                    log_entry = log_handler.log_queue.get(timeout=5)
                    yield f"data: {json.dumps(log_entry)}\n\n"

                    if log_entry.get('type') in ['build_completed', 'build_error']:
                        break

                except queue.Empty:
                    current_time = time.time()
                    if current_time - last_heartbeat > 30:
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': current_time})}\n\n"
                        last_heartbeat = current_time

                    if build_id not in active_builds:
                        break

            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break

        # Cleanup old builds
        with build_lock:
            current_time = time.time()
            builds_to_remove = [
                bid for bid, info in active_builds.items()
                if current_time - info['created_at'] > 3600
            ]
            for bid in builds_to_remove:
                del active_builds[bid]

    return Response(generate_logs(), mimetype='text/event-stream')

@bp.route('/api/fac/build/status/<build_id>')
def build_status(build_id):
    """Get the current status of a specific build"""
    build_info = active_builds.get(build_id)
    if not build_info:
        return jsonify({'error': 'Build not found'}), 404

    return jsonify({
        'build_id': build_id,
        'target': build_info['target'],
        'status': build_info['status'],
        'created_at': build_info['created_at'],
        'error': build_info.get('error')
    })

@bp.route('/api/fac/builds')
def list_builds():
    """List all current build records"""
    with build_lock:
        builds = []
        for build_id, info in active_builds.items():
            builds.append({
                'build_id': build_id,
                'target': info['target'],
                'status': info['status'],
                'created_at': info['created_at'],
                'error': info.get('error')
            })

    return jsonify({'builds': builds})

