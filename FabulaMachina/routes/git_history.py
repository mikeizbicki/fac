"""
Git History Management

Provides endpoints for fetching git commit history and managing repository state.
Integrates with the sidebar history tab to show real-time commit updates.

CONSOLE INTEGRATION:
This module logs all git operations to the console system as bash-style commands
followed by their exact output (or error output in red). This provides users with
a readonly shell session view of all git operations performed through the web interface.
"""

import json
import os
import queue
import threading
import time
from flask import Blueprint, jsonify, Response, request

try:
    import git
except ImportError:
    print("GitPython not found. Install with: pip install GitPython")
    git = None

# Import shared console logging
from routes.console_logging import log_console_command, log_console_output

bp = Blueprint('git_history', __name__)

# Global state for git history SSE
history_clients = {}
history_lock = threading.Lock()
history_next_client_id = 1

def get_repo():
    """Get GitPython repo object for current directory"""
    if not git:
        return None
    try:
        return git.Repo(os.getcwd())
    except git.exc.InvalidGitRepositoryError:
        return None

def get_current_commit_hash():
    """Get current commit hash, handling detached HEAD"""
    repo = get_repo()
    if not repo:
        return None
    try:
        return repo.head.commit.hexsha
    except:
        return None

def get_commit_history(limit=200, branch=None):
    """Get git commit history as list of dicts"""
    repo = get_repo()
    if not repo:
        return []

    commits = []
    current_commit_hash = get_current_commit_hash()

    try:
        if branch and branch in [b.name for b in repo.branches]:
            commit_iter = repo.iter_commits(branch, max_count=limit)
        else:
            commit_iter = repo.iter_commits(max_count=limit)

        for commit in commit_iter:
            commit_data = {
                'hash': commit.hexsha[:7],
                'full_hash': commit.hexsha,
                'message': commit.message.strip(),
                'author': commit.author.name,
                'date': commit.committed_date,
                'date_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(commit.committed_date)),
                'is_current': commit.hexsha == current_commit_hash
            }
            commits.append(commit_data)
    except Exception as e:
        print(f"Error getting git history: {e}")

    return commits

def get_current_branch_info():
    """Get current branch name or detached HEAD info"""
    repo = get_repo()
    if not repo:
        return None, None

    try:
        if repo.head.is_detached:
            commit_hash = repo.head.commit.hexsha[:7]
            return None, f"detached HEAD at {commit_hash}"
        else:
            return repo.active_branch.name, None
    except:
        return None, None

def notify_history_clients(event_type, data=None):
    """Send notification to all history SSE clients"""
    with history_lock:
        if not history_clients:
            return

        message = {
            'type': event_type,
            'timestamp': time.time(),
            'data': data
        }

        dead_clients = []
        for client_id, client_queue in history_clients.items():
            try:
                client_queue.put_nowait(message)
            except queue.Full:
                dead_clients.append(client_id)

        for client_id in dead_clients:
            del history_clients[client_id]

@bp.route('/api/git/history')
def git_history():
    """Get git commit history"""
    branch = request.args.get('branch', None)
    commits = get_commit_history(limit=200, branch=branch)
    current_branch, detached_info = get_current_branch_info()

    return jsonify({
        'success': True,
        'commits': commits,
        'current_branch': current_branch,
        'detached_info': detached_info
    })

@bp.route('/api/git/branches')
def git_branches():
    """Get list of git branches"""
    repo = get_repo()
    if not repo:
        return jsonify({'success': False, 'error': 'Not a git repository'}), 400

    try:
        branches = []
        current_branch, detached_info = get_current_branch_info()

        for branch in repo.branches:
            branches.append(branch.name)

        return jsonify({
            'success': True,
            'branches': sorted(branches),
            'current_branch': current_branch,
            'detached_info': detached_info
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/git/switch-branch', methods=['POST'])
def git_switch_branch():
    """Switch to a different branch"""
    repo = get_repo()
    if not repo:
        return jsonify({'success': False, 'error': 'Not a git repository'}), 400

    data = request.get_json()
    branch_name = data.get('branch_name')

    if not branch_name:
        return jsonify({'success': False, 'error': 'branch_name required'}), 400

    log_console_command(f'git checkout {branch_name}')

    try:
        result = repo.git.checkout(branch_name)

        if result:
            log_console_output(result)
        else:
            log_console_output(f"Switched to branch '{branch_name}'")

        notify_history_clients('branch_switched', {
            'branch': branch_name,
            'message': f'Switched to branch {branch_name}'
        })

        return jsonify({
            'success': True,
            'message': f'Switched to branch {branch_name}'
        })
    except Exception as e:
        error_msg = str(e)
        log_console_output(error_msg, 'error')

        return jsonify({
            'success': False,
            'error': f'Branch switch failed: {error_msg}'
        }), 400

@bp.route('/api/git/create-branch', methods=['POST'])
def git_create_branch():
    """Create and switch to a new branch"""
    repo = get_repo()
    if not repo:
        return jsonify({'success': False, 'error': 'Not a git repository'}), 400

    data = request.get_json()
    branch_name = data.get('branch_name')

    if not branch_name:
        return jsonify({'success': False, 'error': 'branch_name required'}), 400

    log_console_command(f'git checkout -b {branch_name}')

    try:
        result = repo.git.checkout('-b', branch_name)

        if result:
            log_console_output(result)
        else:
            log_console_output(f"Switched to a new branch '{branch_name}'")

        notify_history_clients('branch_switched', {
            'branch': branch_name,
            'message': f'Created and switched to branch {branch_name}'
        })

        return jsonify({
            'success': True,
            'message': f'Created and switched to branch {branch_name}'
        })
    except Exception as e:
        error_msg = str(e)
        log_console_output(error_msg, 'error')

        return jsonify({
            'success': False,
            'error': f'Branch creation failed: {error_msg}'
        }), 400

@bp.route('/api/git/checkout', methods=['POST'])
def git_checkout():
    """Checkout a specific commit"""
    repo = get_repo()
    if not repo:
        return jsonify({'success': False, 'error': 'Not a git repository'}), 400

    data = request.get_json()
    commit_hash = data.get('commit_hash')

    if not commit_hash:
        return jsonify({'success': False, 'error': 'commit_hash required'}), 400

    log_console_command(f'git checkout {commit_hash}')

    try:
        result = repo.git.checkout(commit_hash)

        if result:
            log_console_output(result)
        else:
            log_console_output(f"HEAD is now at {commit_hash[:7]}")

        notify_history_clients('checkout', {
            'commit_hash': commit_hash,
            'message': f'Checked out commit {commit_hash[:7]}'
        })

        return jsonify({
            'success': True,
            'message': f'Checked out commit {commit_hash[:7]}'
        })
    except Exception as e:
        error_msg = str(e)
        log_console_output(error_msg, 'error')

        return jsonify({
            'success': False,
            'error': f'Checkout failed: {error_msg}'
        }), 400

@bp.route('/api/git/history/events')
def git_history_events():
    """Server-Sent Events for git history updates"""
    def generate():
        global history_next_client_id

        with history_lock:
            client_id = f"history_client_{history_next_client_id}_{int(time.time())}"
            history_next_client_id += 1
            client_queue = queue.Queue(maxsize=100)
            history_clients[client_id] = client_queue

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
            with history_lock:
                if client_id in history_clients:
                    del history_clients[client_id]

    return Response(generate(), mimetype='text/event-stream')

def on_commit_created(commit_hash, message):
    """Called when a new commit is created"""
    notify_history_clients('new_commit', {
        'commit_hash': commit_hash,
        'message': message
    })


def commit_changes_to_git(files_to_commit, commit_message):
    """Helper function to commit changes to git with console logging"""
    try:
        import git
        repo = git.Repo(os.getcwd())

        # Stage the modified files
        existing_files = [f for f in files_to_commit if os.path.exists(f)]
        if existing_files:
            # Log the git add commands to console
            from routes.console_logging import log_console_command, log_console_output
            for file_path in existing_files:
                log_console_command(f'git add {file_path}')

            repo.index.add(existing_files)

            # Commit the changes
            commit = repo.index.commit(commit_message)

            # Log the git commit command to console
            log_console_command(f'git commit -m "{commit_message}"')
            log_console_output(f"[{commit.hexsha[:7]}] {commit_message}")

            # Notify git history clients of the new commit
            try:
                from routes.git_history import notify_history_clients
                notify_history_clients('new_commit', {
                    'commit_hash': commit.hexsha[:7],
                    'message': commit_message
                })
            except ImportError:
                pass

            return True
    except Exception as git_error:
        print(f"Git commit failed: {git_error}")
        return False
