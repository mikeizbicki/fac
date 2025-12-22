from flask import Blueprint, render_template, abort, request, jsonify, send_file
import os

bp = Blueprint('api', __name__)

@bp.route('/pages/<page>/static/<path:filename>')
def page_static(page, filename):
    return send_file(os.path.join('pages', page, 'static', filename))

@bp.route('/api/get_target/<path:target>')
def serve_target_file(target):
    """Serve any file corresponding to a fac.yaml target."""
    # Sanitize the path to prevent directory traversal attacks
    safe_target = os.path.normpath(target)
    if safe_target.startswith('..') or os.path.isabs(safe_target):
        abort(403)  # Forbidden - potential security issue

    # Make the target path relative to the working directory where flask was launched
    target_path = os.path.join(os.getcwd(), safe_target)

    if os.path.exists(target_path):
        return send_file(target_path)
    else:
        abort(404)

def discover_items(base_dir, required_files=None):
    """Generic function to discover items in a directory structure."""
    items = []

    if not os.path.exists(base_dir):
        return items

    for item_name in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item_name)
        if os.path.isdir(item_path):
            # Check if required files exist (if specified)
            if required_files:
                has_all_required = all(
                    os.path.exists(os.path.join(item_path, req_file))
                    for req_file in required_files
                )
                if not has_all_required:
                    continue

            items.append({
                'name': item_name,
                'title': item_name.replace('_', ' ').title()
            })

    return sorted(items, key=lambda x: x['name'])

@bp.route('/')
def index():
    """List all available books, characters, and locations."""
    # Discover books (existing logic)
    books = []
    books_dir = 'books'

    if os.path.exists(books_dir):
        for level in os.listdir(books_dir):
            level_path = os.path.join(books_dir, level)
            if os.path.isdir(level_path):
                for book in os.listdir(level_path):
                    book_path = os.path.join(level_path, book)
                    script_path = os.path.join(book_path, 'script.fountain.framed')
                    if os.path.isdir(book_path) and os.path.exists(script_path):
                        books.append({
                            'level': level,
                            'book': book,
                            'title': f"{level} - {book}"
                        })

    # Discover collections with their display modes
    from flask import current_app

    collections = {}

    # Get registered blueprints and check for collection metadata
    for blueprint_name, blueprint in current_app.blueprints.items():
        if hasattr(blueprint, 'collection_metadata'):
            metadata = blueprint.collection_metadata
            collection_name = metadata['collection_name']
            display_mode = metadata['display_mode']

            if display_mode == 'list':
                collection_items = discover_items(collection_name, ['about.json'])
                collections[collection_name] = {
                    'collection_items': collection_items,  # Changed key name
                    'display_mode': 'list'
                }
            elif display_mode == 'thumbnail':
                thumbnail_items = []
                fac_dir = metadata['fac_dir']
                thumbnail_file = metadata['thumbnail_file']

                for item_name in metadata['items']:
                    thumbnail_path = os.path.join(fac_dir, collection_name, item_name, thumbnail_file)
                    item_data = {
                        'name': item_name,
                        'title': item_name.replace('_', ' ').title(),
                        'thumbnail_url': f'/{collection_name}/{item_name}/{thumbnail_file}' if os.path.exists(thumbnail_path) else None
                    }
                    thumbnail_items.append(item_data)

                collections[collection_name] = {
                    'collection_items': thumbnail_items,  # Changed key name
                    'display_mode': 'thumbnail'
                }

    return render_template('index.html',
                         books=books,
                         collections=collections)

@bp.route('/api/collections')
def get_collections():
    """Get character and location collections for autocomplete."""
    try:
        characters = discover_items('characters', ['about.json'])
        locations = discover_items('locations', ['about.json'])
        
        return jsonify({
            'success': True,
            'characters': characters,
            'locations': locations
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

