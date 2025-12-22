"""
Flask app for viewing framed fountain scripts.

Serves framed fountain files from books/$LEVEL/$BOOK/script.fountain.framed
and renders them using screenplain with frame organization.

====

This app uses a new frame-enhanced version of the fountain file format.

MOTIVATION:
When working with screenplays, it's often useful to break the script into small,
manageable chunks (frames) of action/dialogue that represent roughly 10 seconds
of screen time each. This allows for:

1. Better organization and analysis of screenplay structure
2. Easier collaboration and review of specific script segments
3. Frame-by-frame editing and revision workflows
4. Integration with storyboarding and pre-production planning tools

FRAMED FOUNTAIN FORMAT:
This script introduces a simple XML-like syntax that extends standard fountain
format by wrapping content in <frame> tags:

    <frame frame_id="opening_scene">
    FADE IN:

    EXT. PARK - DAY

    JOHN walks his dog.
    </frame>

    <frame frame_id="first_dialogue">
    JOHN
    Good morning, Rex.

    The dog barks.
    </frame>

Each frame tag may optionally also have a reference_frame attribute.
If this attribute is present, it must be equal to the frame_id of a previous frame.
Semantically, this tells us that the animation of the current frame should continue where the animation for reference_frame stopped.
This can be used to signal that two adjacent frames form part of the same shot (without a cut), or that two non-adjacent frames are interrupted by a short cut and then the shot returns to frame_id exactly as it was at the end of reference_frame.

RENDERING APPROACH:
Rather than reimplementing fountain-to-HTML conversion, this script leverages
the existing screenplain library's robust rendering engine. Each frame's
fountain content is individually processed by screenplain, then wrapped in
HTML div elements with frame IDs for styling and JavaScript manipulation.

The output maintains all of screenplain's formatting quality while adding
frame-level organization that enables advanced workflow tools and analysis.
"""

from flask import Blueprint, render_template, abort, request, jsonify, send_file
import json
import logging
import os
import re
import shutil
import traceback
from io import StringIO
from screenplain.parsers import fountain
from screenplain.export.html import convert
from routes.git_history import commit_changes_to_git

bp = Blueprint('books', __name__, template_folder='.')


@bp.route('/books/<level>/<book>/update_reference_frame', methods=['POST'])
def update_reference_frame(level, book):
    """Update the reference_frame for a specific frame."""
    script_path = os.path.join('books', level, book, 'script.fountain.framed')
    content_path = os.path.join('books', level, book, 'content.json')

    data = request.get_json()
    frame_id = data.get('frame_id')
    new_reference_frame = data.get('reference_frame')

    try:
        files_modified = []

        # Update the fountain file first
        if os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find and update the specific frame's reference_frame attribute
            def update_frame_reference(match):
                full_match = match.group(0)
                current_frame_id = match.group(1)
                current_reference_frame = match.group(3) if match.group(3) else ""
                frame_content = match.group(4)

                if current_frame_id == frame_id:
                    # Update this frame's reference_frame
                    if new_reference_frame and new_reference_frame.strip():
                        return f'<frame frame_id="{frame_id}" reference_frame="{new_reference_frame}">{frame_content}</frame>'
                    else:
                        return f'<frame frame_id="{frame_id}">{frame_content}</frame>'
                else:
                    # Return unchanged
                    return full_match

            # Apply the update using regex substitution
            frame_pattern = r'<frame\s+frame_id="([^"]+)"(\s+reference_frame="([^"]+)")?>(.*?)</frame>'
            updated_content = re.sub(frame_pattern, update_frame_reference, content, flags=re.DOTALL)

            # Atomic write to fountain file
            temp_path = script_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            shutil.move(temp_path, script_path)
            files_modified.append(script_path)

        # Update the JSON file if it exists
        if os.path.exists(content_path):
            with open(content_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            # Update the specific frame
            for frame in json_data['frames']:
                if frame['frame_id'] == frame_id:
                    frame['reference_frame'] = new_reference_frame
                    break

            # Atomic write to JSON file
            temp_path = content_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            shutil.move(temp_path, content_path)
            files_modified.append(content_path)

        # Commit changes to git using helper function
        ref_display = new_reference_frame if new_reference_frame else "none"
        commit_message = f"[human] set reference_frame={ref_display} for frame_id={frame_id}"
        commit_changes_to_git(files_modified, commit_message)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/books/<level>/<book>/delete_frame', methods=['POST'])
def delete_frame(level, book):
    """Delete a frame from both fountain and JSON files."""
    script_path = os.path.join('books', level, book, 'script.fountain.framed')

    if not os.path.exists(script_path):
        abort(404)

    data = request.get_json()
    frame_id = data.get('frame_id')

    try:
        files_modified = []

        # Delete from fountain file
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Remove the frame block completely
        pattern = f'<frame\\s+frame_id="{re.escape(frame_id)}".*?</frame>'
        updated_content = re.sub(pattern, '', content, flags=re.DOTALL)

        # Clean up extra whitespace
        updated_content = re.sub(r'\n{3,}', '\n\n', updated_content)

        # Atomic write
        temp_path = script_path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        shutil.move(temp_path, script_path)
        files_modified.append(script_path)

        # Delete from JSON file if it exists
        content_path = os.path.join('books', level, book, 'content.json')
        if os.path.exists(content_path):
            with open(content_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            # Remove the frame from the frames array
            json_data['frames'] = [f for f in json_data['frames'] if f['frame_id'] != frame_id]

            # Atomic write
            temp_path = content_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            shutil.move(temp_path, content_path)
            files_modified.append(content_path)

        # Delete frame assets directory if it exists
        frame_dir = os.path.join('books', level, book, 'frames', frame_id)
        if os.path.exists(frame_dir):
            shutil.rmtree(frame_dir)

        # Commit changes to git
        commit_message = f"[human] delete frame_id={frame_id}"
        commit_changes_to_git(files_modified, commit_message)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/books/<level>/<book>/add_frame', methods=['POST'])
def add_frame(level, book):
    """Add a new empty frame after the specified frame."""
    script_path = os.path.join('books', level, book, 'script.fountain.framed')

    if not os.path.exists(script_path):
        abort(404)

    data = request.get_json()
    new_frame_id = data.get('frame_id')
    after_frame_id = data.get('after_frame')

    try:
        files_modified = []
        new_frame_content = '*insert new frame content here*'
        
        # Add to fountain file
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the position after the specified frame
        if after_frame_id:
            pattern = f'(<frame\\s+frame_id="{re.escape(after_frame_id)}".*?</frame>)'
            replacement = f'\\1\n\n<frame frame_id="{new_frame_id}">\n{new_frame_content}\n</frame>'
            updated_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        else:
            # If no after_frame specified, add at the end
            updated_content = content + f'\n\n<frame frame_id="{new_frame_id}">\n{new_frame_content}\n</frame>'

        # Atomic write
        temp_path = script_path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        shutil.move(temp_path, script_path)
        files_modified.append(script_path)

        # Add to JSON file if it exists
        content_path = os.path.join('books', level, book, 'content.json')
        if os.path.exists(content_path):
            with open(content_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            # Create new frame JSON entry
            new_frame_json = {
                "frame_id": new_frame_id,
                "title": "New Scene",
                "description": "New scene description",
                "characters": [],
                "location": "New Location",
                "time_of_day": "day"
            }

            # Find position to insert
            if after_frame_id:
                insert_index = next((i + 1 for i, f in enumerate(json_data['frames'])
                                   if f['frame_id'] == after_frame_id), len(json_data['frames']))
            else:
                insert_index = len(json_data['frames'])

            json_data['frames'].insert(insert_index, new_frame_json)

            # Atomic write
            temp_path = content_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            shutil.move(temp_path, content_path)
            files_modified.append(content_path)

        # Create frame assets directory
        frame_dir = os.path.join('books', level, book, 'frames', new_frame_id)
        os.makedirs(frame_dir, exist_ok=True)

        # Commit changes to git
        commit_message = f"[human] add frame_id={new_frame_id}"
        if after_frame_id:
            commit_message += f" after frame_id={after_frame_id}"
        commit_changes_to_git(files_modified, commit_message)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/books/<level>/<book>/get_frame_json/<frame_id>')
def get_frame_json(level, book, frame_id):
    """Get JSON data for a specific frame."""
    content_path = os.path.join('books', level, book, 'content.json')

    try:
        with open(content_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        frame_data = next((f for f in content['frames'] if f['frame_id'] == frame_id), None)
        if frame_data:
            return jsonify({'success': True, 'frame_data': frame_data})
        else:
            return jsonify({'success': False, 'error': 'Frame not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@bp.route('/books/<level>/<book>/save_frame', methods=['POST'])
def save_frame(level, book):
    """Save both fountain and JSON content atomically."""
    script_path = os.path.join('books', level, book, 'script.fountain.framed')

    if not os.path.exists(script_path):
        abort(404)

    data = request.get_json()
    frame_id = data.get('frame_id')
    fountain_content = data.get('fountain_content', data.get('content'))
    json_content = data.get('json_content')

    try:
        files_modified = []

        # Save fountain file
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace the specific frame content
        pattern = f'(<frame\\s+frame_id="{re.escape(frame_id)}")(.*?)(</frame>)'
        replacement = f'\\1>{fountain_content.strip()}\n\\3'
        updated_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        # Atomic write using temporary file
        temp_path = script_path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        shutil.move(temp_path, script_path)
        files_modified.append(script_path)

        # Save JSON file if provided
        if json_content:
            content_path = os.path.join('books', level, book, 'content.json')
            if os.path.exists(content_path):
                with open(content_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)

                # Update the specific frame
                for i, frame in enumerate(json_data['frames']):
                    if frame['frame_id'] == frame_id:
                        json_data['frames'][i] = json.loads(json_content)
                        break

                # Atomic write
                temp_path = content_path + '.tmp'
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, indent=2, ensure_ascii=False)
                shutil.move(temp_path, content_path)
                files_modified.append(content_path)

        # Commit changes to git
        commit_message = f"[human] edit frame_id={frame_id}"
        commit_changes_to_git(files_modified, commit_message)

        # Return rendered HTML for this frame
        rendered_html = render_frame_html(fountain_content)
        return jsonify({'success': True, 'html': rendered_html})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



def parse_framed_fountain(content):
    """Parse the framed fountain format and extract frames."""
    frames = []
    
    # Find all frame blocks
    frame_pattern = r'<frame\s+frame_id="([^"]+)"(\s+reference_frame="([^"]+)")?>(.*?)</frame>'
    matches = re.findall(frame_pattern, content, re.DOTALL)

    
    for match in matches:
        frame_id = match[0]
        reference_frame = match[2]
        content = match[3].strip()
        frames.append({
            'frame_id': frame_id,
            'reference_frame': reference_frame,
            'content': content
        })
    
    return frames

def render_frame_html(frame_content):
    """Convert a single frame's fountain content to HTML."""

    # Load character and location names for processing
    characters = []
    locations = []
    try:
        from routes.api import discover_items
        characters = [item['name'] for item in discover_items('characters', ['about.json'])]
        locations = [item['name'] for item in discover_items('locations', ['about.json'])]
    except Exception as e:
        print(f"Error loading collections: {e}")

    # Process @ and # symbols
    processed_content = frame_content

    # Remove @ and # symbols but preserve the names for processing
    import re

    # Find all @CHARACTER and #LOCATION patterns
    character_pattern = r'@([A-Za-z0-9_]+)'
    location_pattern = r'#([A-Za-z0-9_]+)'

    # Replace @ symbols but keep track of characters
    def replace_character(match):
        name = match.group(1)
        return name  # Remove the @ symbol

    def replace_location(match):
        name = match.group(1)
        return name  # Remove the # symbol

    processed_content = re.sub(character_pattern, replace_character, processed_content)
    processed_content = re.sub(location_pattern, replace_location, processed_content)

    # NOTE: screenplain always renders underscores as markdown underlines,
    # and it does not respect normal escapes like "\_".
    # Therefore, we create our own special escape code that is unlikely to conflict with anything,
    # and manually replace underscores before/after calling screenplain.
    underscore_escape = 'UNDERSCORE'*5
    processed_content = processed_content.replace('_', underscore_escape)
    start_string = 'FADE IN: \n\n\n'
    screenplay = fountain.parse(StringIO(start_string + processed_content))
    html_buffer = StringIO()
    convert(screenplay, html_buffer, bare=True)
    html_content = html_buffer.getvalue().replace(underscore_escape, '_')[41:]

    # Post-process HTML to make character/location names clickable and uppercase
    def make_clickable(text, names, collection_type):
        # Sort names by length (longest first) to prevent shorter names from matching parts of longer names
        sorted_names = sorted(names, key=len, reverse=True)

        for name in sorted_names:
            # Create pattern that matches the name case-insensitively as a whole word
            # Use word boundaries but also handle underscores as word characters
            pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)

            def replacement(match):
                original = match.group(0)
                upper_name = original.upper()
                return f'<a href="/{collection_type}/{name}" class="character-location-link" data-name="{name}" data-type="{collection_type}">{upper_name}</a>'

            text = pattern.sub(replacement, text)
        return text

    # Apply clickable links for characters and locations
    html_content = make_clickable(html_content, characters, 'characters')
    html_content = make_clickable(html_content, locations, 'locations')

    return html_content


@bp.route('/books/<level>/<book>')
def view_script(level, book):
    """View a framed fountain script."""
    script_path = os.path.join('books', level, book, 'script.fountain.framed')
    content_path = os.path.join('books', level, book, 'content.json')

    if not os.path.exists(script_path):
        abort(404)

    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()

    frames = parse_framed_fountain(content)

    if not frames:
        return render_template('template.html',
                             level=level,
                             book=book,
                             frames=[],
                             error="No frames found in script")

    # Load JSON data if it exists
    json_data = {}
    if os.path.exists(content_path):
        with open(content_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

    # Create a lookup for frame metadata
    frame_metadata = {}
    for frame_info in json_data.get('frames', []):
        frame_id = frame_info.get('frame_id')
        frame_metadata[frame_id] = frame_info
        # DEBUG: Print frame info
        print(f"Frame {frame_id}: reference_frame = {frame_info.get('reference_frame', 'NOT FOUND')}")

    # Render each frame with metadata
    rendered_frames = []
    for frame in frames:
        metadata = frame_metadata.get(frame['frame_id'], {})
        rendered_frames.append({
            'id': frame['frame_id'],
            'html': render_frame_html(frame['content']),
            'content': frame['content'],
            'reference_frame': frame.get('reference_frame')
        })

    return render_template('template.html',
                         level=level,
                         book=book,
                         frames=rendered_frames)
