#!/usr/bin/env python3
from io import StringIO
import json
import os
import re
import shutil
import tempfile

from flask import Flask, render_template, abort, request, jsonify, send_file
from screenplain.parsers import fountain
from screenplain.export.html import convert

app = Flask(__name__)
app.static_folder = 'static'
app.static_url_path = '/static'

import routes.api
app.register_blueprint(routes.api.bp)

import routes.auto_updater
app.register_blueprint(routes.auto_updater.bp)

import pages.book.routes
app.register_blueprint(pages.book.routes.bp)

import routes.fac
app.register_blueprint(routes.fac.bp)

import routes.git_history
app.register_blueprint(routes.git_history.bp)

# Import the generic target collection system
from routes.target_collection import create_collection_routes

# Register collection routes
fac_yaml_path = 'fac.yaml'

# Characters collection with custom file order
characters_bp = create_collection_routes(
    fac_yaml_path=fac_yaml_path,
    collection_name='characters',
    file_order=['character_sheet.png', 'about.json', 'voice.json'],
    blueprint_name='characters',
    display_mode='thumbnail',
    thumbnail_file='character_sheet.png',
)
app.register_blueprint(characters_bp)

# Locations collection
locations_bp = create_collection_routes(
    fac_yaml_path=fac_yaml_path,
    collection_name='locations',
    file_order=['reference.png', 'about.json'],
    blueprint_name='locations',
    display_mode='thumbnail',
    thumbnail_file='reference.png',
)
app.register_blueprint(locations_bp)

if __name__ == '__main__':
    app.run(debug=True)

