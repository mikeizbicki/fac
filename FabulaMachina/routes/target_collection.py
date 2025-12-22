"""
Generic Target Collection System

This module provides a reusable system for creating Flask routes for any "collection"
of "targets" defined in a fac.yaml file. A target is a top-level entry in the fac.yaml
file, and a collection is a subfolder that contains many targets with variables.
"""

import os
import re
from flask import Blueprint, render_template, abort, request, jsonify, send_file
import json
import shutil
from routes.git_history import commit_changes_to_git

# FIXME:
# both of these functions should come from the fac library
def extract_variables(template_string):
    """Fallback implementation if fac.utils not available"""
    return re.findall(r'\$([A-Z_][A-Z0-9_]*)', template_string)

def load_config(fac_yaml_path):
    """Fallback implementation if fac.BuildSystem not available"""
    import yaml
    with open(fac_yaml_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def discover_targets_for_collection(fac_yaml_path, collection_name):
    """
    Scan fac.yaml and return all targets that belong to the specified collection.

    Returns:
        dict: {
            'target_templates': [list of target template paths from yaml],
            'variable': variable name (e.g., 'CHARACTER', 'LOCATION'),
            'items': [list of actual item names found on filesystem],
            'schemas': {target_path: schema_info}
        }
    """
    fac_config = load_config(fac_yaml_path)

    target_templates = []
    schemas = {}
    variable = None

    # Find all targets that start with collection_name/
    for target_path, target_config in fac_config.items():
        if target_path.startswith(f"{collection_name}/"):
            target_templates.append(target_path)

            # Store schema information if available
            if isinstance(target_config, dict) and 'schema_file' in target_config:
                schemas[target_path] = {
                    'schema_file': target_config['schema_file'],
                    'description': target_config.get('description', '')
                }

            # Extract variable from the first target we find
            if variable is None:
                variables = extract_variables(target_path)
                if variables:
                    variable = variables[0]  # Take the first variable

    # Discover actual items by scanning filesystem relative to fac.yaml
    items = []
    if variable:
        fac_dir = os.path.dirname(os.path.abspath(fac_yaml_path))
        collection_dir = os.path.join(fac_dir, collection_name)

        if os.path.exists(collection_dir):
            for item_name in os.listdir(collection_dir):
                item_path = os.path.join(collection_dir, item_name)
                if os.path.isdir(item_path):
                    items.append(item_name)

    return {
        'target_templates': sorted(target_templates),
        'variable': variable,
        'items': sorted(items),
        'schemas': schemas
    }

def get_actual_targets_for_item(target_templates, variable, item_name):
    """
    Convert target templates to actual file paths for a specific item.

    Args:
        target_templates: List of target templates from yaml (e.g., "characters/$CHARACTER/about.json")
        variable: Variable name (e.g., "CHARACTER")
        item_name: Actual item name (e.g., "Didaskalos")

    Returns:
        List of actual target paths that should exist for this item
    """
    actual_targets = []

    for template in target_templates:
        if variable:
            # Replace variable with actual item name
            actual_path = template.replace(f'${variable}', item_name)
            actual_targets.append(actual_path)
        else:
            # No variable, use template as-is
            actual_targets.append(template)

    return actual_targets

def get_file_type(filename):
    """Determine file type for rendering purposes."""
    ext = filename.lower().split('.')[-1]
    if ext in ['json']:
        return 'json'
    elif ext in ['md', 'txt']:
        return 'markdown'
    elif ext in ['png', 'jpg', 'jpeg', 'gif', 'svg']:
        return 'image'
    elif ext in ['mp4', 'mov', 'avi']:
        return 'video'
    elif ext in ['wav', 'mp3', 'ogg']:
        return 'audio'
    else:
        return 'text'

def create_collection_routes(fac_yaml_path, collection_name, file_order=None, blueprint_name=None, display_mode='list', thumbnail_file=None):
    """
    Create Flask routes for a target collection.

    Args:
        fac_yaml_path (str): Path to the fac.yaml file
        collection_name (str): Name of the collection (e.g., 'characters', 'locations')
        file_order (list, optional): Custom order for files in collection pages
        blueprint_name (str, optional): Custom blueprint name, defaults to collection_name

    Returns:
        Blueprint: Flask blueprint with all routes registered
    """

    if blueprint_name is None:
        blueprint_name = collection_name

    if display_mode == 'thumbnail' and not thumbnail_file:
        raise ValueError(f"thumbnail_file is required when display_mode='thumbnail' for collection {collection_name}")

    bp = Blueprint(blueprint_name, __name__, template_folder='.')

    # Get the directory containing the fac.yaml file
    fac_dir = os.path.dirname(os.path.abspath(fac_yaml_path))

    # Discover targets for this collection
    collection_info = discover_targets_for_collection(fac_yaml_path, collection_name)
    target_templates = collection_info['target_templates']
    variable = collection_info['variable']
    items = collection_info['items']
    schemas = collection_info['schemas']

    # Store collection metadata for use by routes.api
    bp.collection_metadata = {
        'display_mode': display_mode,
        'thumbnail_file': thumbnail_file,
        'collection_name': collection_name,
        'fac_dir': fac_dir,
        'items': items
    }
    @bp.route(f'/{collection_name}/<item_name>')
    @bp.route(f'/{collection_name}/<item_name>/')
    def view_collection_item(item_name):
        """View a specific item in the collection."""
        item_path = os.path.join(fac_dir, collection_name, item_name)

        print(f"DEBUG: Viewing {collection_name} item: {item_name} at {item_path}")

        if not os.path.exists(item_path):
            abort(404)

        # Get actual target paths for this specific item
        actual_targets = get_actual_targets_for_item(target_templates, variable, item_name)

        print(f"DEBUG: Actual targets for {item_name}: {actual_targets}")

        # Process only the files that correspond to actual targets
        files = []

        # Sort according to custom order or alphabetically
        if file_order:
            # Sort by custom order, with unspecified files at the end
            def sort_key(target_path):
                filename = os.path.basename(target_path)
                try:
                    return file_order.index(filename)
                except ValueError:
                    return len(file_order)  # Put at end if not in order list
            actual_targets.sort(key=sort_key)
        else:
            actual_targets.sort(key=lambda x: os.path.basename(x))

        # Process each target file
        for target_path in actual_targets:
            filename = os.path.basename(target_path)
            file_path = os.path.join(fac_dir, collection_name, item_name, filename)

            print(f"DEBUG: Checking target file: {target_path} -> {file_path}")

            if os.path.exists(file_path):
                file_type = get_file_type(filename)

                file_info = {
                    'name': filename,
                    'type': file_type,
                    'title': filename,  # Use literal filename instead of prettified version
                    'path': f'/{target_path}',
                    'fac_target': target_path  # All files we show are FAC targets
                }

                # Add schema information if available
                template_path = None
                for template in target_templates:
                    if variable and template.replace(f'${variable}', item_name) == target_path:
                        template_path = template
                        break

                if template_path and template_path in schemas:
                    schema_info = schemas[template_path]
                    file_info['schema_file'] = schema_info['schema_file']
                    file_info['description'] = schema_info['description']

                # Load content for text files
                if file_type in ['json', 'markdown', 'text']:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            file_info['content'] = f.read()
                    except Exception as e:
                        print(f"DEBUG: Error loading {file_path}: {e}")
                        continue

                files.append(file_info)
                print(f"DEBUG: Added file: {filename} ({file_type})")
            else:
                print(f"DEBUG: Target file does not exist: {file_path}")

        breadcrumbs = [
            {'title': 'Home', 'url': '/'},
            {'title': collection_name.title(), 'url': f'/#{collection_name}'},
            {'title': item_name.replace('_', ' ').title(), 'url': None}
        ]

        return render_template('target_collection.html',
                             collection_name=collection_name,
                             item_name=item_name,
                             item_title=item_name.replace('_', ' ').title(),
                             files=files,
                             breadcrumbs=breadcrumbs)

    @bp.route(f'/{collection_name}/<item_name>/schema/<path:schema_file>')
    def serve_schema_file(item_name, schema_file):
        """Serve JSON schema files."""
        schema_path = os.path.join(fac_dir, schema_file)
        if os.path.exists(schema_path):
            return send_file(schema_path)
        else:
            abort(404)

    @bp.route(f'/{collection_name}/<item_name>/<path:filename>')
    def serve_collection_file(item_name, filename):
        """Serve files from collection items."""
        # Build file path relative to fac.yaml location
        file_path = os.path.join(fac_dir, collection_name, item_name, filename)

        if os.path.exists(file_path):
            return send_file(file_path)
        else:
            abort(404)

    @bp.route(f'/{collection_name}/<item_name>/save', methods=['POST'])
    def save_collection_file(item_name):
        """Save text files in collection items."""
        item_path = os.path.join(fac_dir, collection_name, item_name)

        if not os.path.exists(item_path):
            abort(404)

        data = request.get_json()
        filename = data.get('filename')
        content = data.get('content')

        if not filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        # Verify this file corresponds to a valid target
        actual_targets = get_actual_targets_for_item(target_templates, variable, item_name)
        target_filenames = [os.path.basename(target) for target in actual_targets]

        if filename not in target_filenames:
            return jsonify({'success': False, 'error': 'File is not a valid target'}), 400

        file_path = os.path.join(item_path, filename)

        try:
            # Validate JSON if it's a JSON file
            if filename.endswith('.json'):
                json.loads(content)

            # Atomic write
            temp_path = file_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            shutil.move(temp_path, file_path)

            # Commit to git
            commit_message = f"[human] edit {filename} for {collection_name} {item_name}"
            commit_changes_to_git([file_path], commit_message)

            return jsonify({'success': True})

        except json.JSONDecodeError as e:
            return jsonify({'success': False, 'error': f'Invalid JSON: {str(e)}'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    return bp

