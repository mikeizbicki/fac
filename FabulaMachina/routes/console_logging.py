"""
Shared Console Logging System

This module provides output to a "readonly" shell session. Standard use is to log 
commands with bash-style prompts ('$ command') followed by the exact output as it would 
appear in a terminal. This should be done for all API endpoints that run something 
equivalent to a shell command. Error output should be shown verbatim in red, success 
output should preserve original formatting without timestamps or additional annotations.
"""

import json
import queue
import threading
import time

# Global state for console log streaming
console_clients = {}
console_lock = threading.Lock()

def log_console_command(command, level='info'):
    """Log a bash-style command to the console"""
    with console_lock:
        if not console_clients:
            return
            
        log_entry = {
            'type': 'console_command',
            'level': level,
            'message': f'$ {command}',
            'timestamp': time.time()
        }
        
        dead_clients = []
        for client_id, client_queue in console_clients.items():
            try:
                client_queue.put_nowait(log_entry)
            except queue.Full:
                dead_clients.append(client_id)
        
        for client_id in dead_clients:
            del console_clients[client_id]

def log_console_output(output, level='info'):
    """Log command output to the console without timestamps"""
    with console_lock:
        if not console_clients:
            return
            
        log_entry = {
            'type': 'console_output',
            'level': level,
            'message': output,
            'timestamp': time.time()
        }
        
        dead_clients = []
        for client_id, client_queue in console_clients.items():
            try:
                client_queue.put_nowait(log_entry)
            except queue.Full:
                dead_clients.append(client_id)
        
        for client_id in dead_clients:
            del console_clients[client_id]

def add_console_client(client_id, client_queue):
    """Add a new console client"""
    with console_lock:
        console_clients[client_id] = client_queue

def remove_console_client(client_id):
    """Remove a console client"""
    with console_lock:
        if client_id in console_clients:
            del console_clients[client_id]

def clear_console():
    """Clear console for all clients"""
    with console_lock:
        clear_message = {
            'type': 'clear_console',
            'timestamp': time.time()
        }
        
        for client_queue in console_clients.values():
            try:
                client_queue.put_nowait(clear_message)
            except queue.Full:
                pass

