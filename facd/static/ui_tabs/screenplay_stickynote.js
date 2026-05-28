// screenplay_stickynote.js
//
// Shared sticky-note rendering for screenplay-like views (screenplay.js,
// storyboard.js, screenplay_view.js). Each sticky note shows metadata
// for one beat plus its related build targets (beat_type,
// length_seconds, startframe.png, raw.mp4) using the nodes.js API.
//
// All registered paths for a view are tracked in a Set that the caller
// owns, so the view can unregister cleanly on re-render.

(function() {
    const BEAT_TARGETS = {
        beat_type: 'beats/$BEAT_ID/beat_type',
        length_seconds: 'beats/$BEAT_ID/length_seconds',
        dialog_duration_with_padding: 'beats/$BEAT_ID/processed_config/dialog_duration_with_padding',
        truncate_video: 'beats/$BEAT_ID/processed_config/truncate_video',
        add_sfx: 'beats/$BEAT_ID/sfx/add_sfx',
        sfx_model: 'beats/$BEAT_ID/sfx/model',
        startframe: 'beats/$BEAT_ID/beat_type=standard/startframe.png',
        video: 'beats/$BEAT_ID/raw.mp4',
        debug_video: 'beats/$BEAT_ID/debug.mp4',
    };

    function getTargetPath(key, beat_id) {
        return BEAT_TARGETS[key].replace('$BEAT_ID', beat_id);
    }

    function isBeatTargetPath(path) {
        const match = path.match(/^beats\/([^/]+)\//);
        if (!match) return false;
        const beat_id = match[1];
        return Object.values(BEAT_TARGETS).some(pattern =>
            path === pattern.replace('$BEAT_ID', beat_id)
        );
    }

    function createMetaRow(label, value, options) {
        const row = document.createElement('div');
        row.className = 'sticky-meta-row';
        const labelSpan = document.createElement('span');
        labelSpan.className = 'sticky-meta-label';
        labelSpan.textContent = label;
        row.appendChild(labelSpan);
        const valueSpan = document.createElement('span');
        valueSpan.className = 'sticky-meta-value';
        valueSpan.textContent = value;
        row.appendChild(valueSpan);
        if (options && options.editable) {
            row.classList.add('sticky-meta-editable');
            attachBeatRefDropdown(row, options);
        }
        return row;
    }

    // Attach a hover-activated dropdown menu to a meta row that lets
    // the user reassign a beat reference field (continues_from_beat_id
    // or include_beat_id). The dropdown lists all previous beats (plus
    // a "no beat_id" option at the top) with their startframe.png
    // thumbnails. Clicking an entry rewrites the XML; the SSE update
    // triggers the re-render.
    function attachBeatRefDropdown(row, opts) {
        // opts: { field, currentValue, beat, beats, orientation,
        //         onSelect(newValue) }
        const { field, currentValue, beat, beats, orientation, onSelect } = opts;

        let menu = null;
        let outsideClickHandler = null;

        function closeMenu() {
            if (menu && menu.parentElement) menu.parentElement.removeChild(menu);
            menu = null;
            if (outsideClickHandler) {
                document.removeEventListener('mousedown', outsideClickHandler, true);
                outsideClickHandler = null;
            }
        }

        function buildMenu() {
            const m = document.createElement('div');
            m.className = 'sticky-beatref-menu';
            m.dataset.orientation = orientation || 'vertical';

            // Build entry list: "none" first, then all beats that come
            // before `beat` in the beats array.
            const entries = [{ beat_id: '', label: '— (no beat_id)' }];
            const myIdx = beats.findIndex(b => b.beat_id === beat.beat_id);
            for (let i = 0; i < myIdx; i++) {
                entries.push({ beat_id: beats[i].beat_id, label: beats[i].beat_id });
            }

            let selectedEl = null;
            entries.forEach(entry => {
                const item = document.createElement('div');
                item.className = 'sticky-beatref-item';
                if (entry.beat_id === (currentValue || '')) {
                    item.classList.add('selected');
                    selectedEl = item;
                }

                const idLabel = document.createElement('div');
                idLabel.className = 'sticky-beatref-id';
                idLabel.textContent = entry.beat_id || '—';
                item.appendChild(idLabel);

                const thumb = document.createElement('div');
                thumb.className = 'sticky-beatref-thumb';
                if (!entry.beat_id) {
                    thumb.classList.add('sticky-beatref-thumb-empty');
                    thumb.textContent = 'no beat_id';
                } else {
                    const targetPath = getTargetPath('startframe', entry.beat_id);
                    thumb.dataset.path = targetPath;
                    const imgContainer = document.createElement('div');
                    imgContainer.className = 'image-container';
                    thumb.appendChild(imgContainer);

                    const overlay = document.createElement('div');
                    overlay.className = 'node-status-overlay';
                    const overlayText = document.createElement('div');
                    overlayText.className = 'node-status-overlay-text';
                    overlay.appendChild(overlayText);
                    thumb.appendChild(overlay);

                    const state = window.getPathState && window.getPathState(targetPath);
                    const status = (state && state.status) || 'notbuilt';
                    thumb.dataset.status = status;
                    overlayText.textContent = status.toUpperCase();

                    if (window.registerImageContainer) {
                        window.registerImageContainer(targetPath, imgContainer, 'leaf-image');
                    }
                    if (status !== 'notbuilt' && window.fetchImage) {
                        window.fetchImage(targetPath, false).catch(() => {});
                    }
                }
                item.appendChild(thumb);

                item.addEventListener('click', e => {
                    e.stopPropagation();
                    if (entry.beat_id === (currentValue || '')) return;
                    onSelect(entry.beat_id);
                    closeMenu();
                });
                m.appendChild(item);
            });

            row.appendChild(m);

            // Center the selected entry within the menu's scroll area.
            if (selectedEl) {
                if (m.dataset.orientation === 'horizontal') {
                    m.scrollLeft = selectedEl.offsetLeft
                        - (m.clientWidth / 2) + (selectedEl.offsetWidth / 2);
                } else {
                    m.scrollTop = selectedEl.offsetTop
                        - (m.clientHeight / 2) + (selectedEl.offsetHeight / 2);
                }
            }
            clampMenuToViewport(m);
            return m;
    // After the menu has been appended and its centering transform
    // applied, measure where it actually sits in the viewport and
    // nudge it (via an additional inline translate) so it is fully
    // visible. This may shift it off-center but ensures it isn't
    // clipped against any edge of the viewport.
    function clampMenuToViewport(m) {
        // Defer one frame so layout is settled.
        requestAnimationFrame(() => {
            const rect = m.getBoundingClientRect();
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const margin = 4;
            let dx = 0, dy = 0;
            if (rect.left < margin) {
                dx = margin - rect.left;
            } else if (rect.right > vw - margin) {
                dx = (vw - margin) - rect.right;
            }
            if (rect.top < margin) {
                dy = margin - rect.top;
            } else if (rect.bottom > vh - margin) {
                dy = (vh - margin) - rect.bottom;
            }
            if (dx === 0 && dy === 0) return;
            // Preserve the existing centering transform from the
            // stylesheet by appending a new translate. We read the
            // computed transform so we can compose, but since the
            // centering is a pure translate set via CSS, we instead
            // detect orientation and re-apply the right composition.
            const orient = m.dataset.orientation;
            if (orient === 'horizontal') {
                // Original: translateX(-50%). Add pixel offsets.
                m.style.transform =
                    `translateX(-50%) translate(${dx}px, ${dy}px)`;
            } else {
                // Original: translateY(-50%). Add pixel offsets.
                m.style.transform =
                    `translateY(-50%) translate(${dx}px, ${dy}px)`;
            }
        });
    }

        }

        row.addEventListener('click', e => {
            e.stopPropagation();
            if (menu) {
                closeMenu();
                return;
            }
            menu = buildMenu();
            // Install an outside-click handler that closes the menu
            // whenever the user clicks anywhere that isn't the menu
            // or this row.
            outsideClickHandler = (ev) => {
                if (!menu) return;
                if (menu.contains(ev.target) || row.contains(ev.target)) return;
                closeMenu();
            };
            document.addEventListener('mousedown', outsideClickHandler, true);
        });
        return row;
    }

    // Build a header bar with filename + build/delete buttons for a
    // sticky-media-wrapper. This duplicates the relevant bits of
    // build.js's tree-node header menu without depending on the
    // tree-node DOM, because sticky wrappers intentionally don't
    // reuse tree-nodes (see comment in createMediaNode).
    function createMediaHeader(targetPath, filename, mimeType) {
        const header = document.createElement('div');
        header.className = 'sticky-media-header';

        const label = document.createElement('span');
        label.className = 'sticky-media-label';
        label.textContent = filename;
        header.appendChild(label);

        const menu = document.createElement('div');
        menu.className = 'sticky-media-menu';

        const buildBtn = document.createElement('button');
        buildBtn.innerHTML = '🔨';
        buildBtn.title = 'Build';
        buildBtn.addEventListener('click', e => {
            e.stopPropagation();
            // Optimistic state update on every sticky wrapper for this path.
            document.querySelectorAll(
                `.sticky-media-wrapper[data-path="${targetPath}"]`)
                .forEach(w => { w.dataset.status = 'command_sent(build)'; });
            fetch('/add_target', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: targetPath }),
            }).then(r => {
                if (!r.ok) throw new Error('Failed to queue build');
                return r.json();
            }).catch(err => {
                console.error('Error queuing build:', err);
                alert('Failed to queue build: ' + err.message);
            });
        });
        menu.appendChild(buildBtn);

        // Edit button for text-backed targets. The actual edit UI is
        // wired up in createMediaNode (which owns the text container)
        // via the data-edit-trigger attribute.
        if (mimeType && mimeType.startsWith('text/')) {
            const editBtn = document.createElement('button');
            editBtn.innerHTML = '✏️';
            editBtn.title = 'Edit';
            editBtn.dataset.editTrigger = targetPath;
            editBtn.addEventListener('click', e => {
                e.stopPropagation();
                startStickyTextEdit(targetPath, editBtn);
            });
            menu.appendChild(editBtn);
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = 'Delete';
        deleteBtn.addEventListener('click', e => {
            e.stopPropagation();
            if (!confirm(`Are you sure you want to delete "${targetPath}"?`)) return;
            document.querySelectorAll(
                `.sticky-media-wrapper[data-path="${targetPath}"]`)
                .forEach(w => { w.dataset.status = 'command_sent(delete)'; });
            fetch(`/delete_file/${encodeURIComponent(targetPath)}`, { method: 'DELETE' })
                .then(r => {
                    if (!r.ok) throw new Error('Failed to delete file');
                    return r.json();
                }).catch(err => {
                    console.error('Error deleting file:', err);
                    alert('Failed to delete file: ' + err.message);
                });
        });
        menu.appendChild(deleteBtn);

        header.appendChild(menu);
        return header;
    }

    // Inline-edit a text-backed sticky-media wrapper. Mirrors the
    // flow in build.js for tree-node text editing, but operates on
    // the .sticky-text-content element inside the wrapper. Edits
    // the specific wrapper containing the edit button that was
    // clicked (located via closest()), so clicking the button in
    // either view edits that view's wrapper.
    function startStickyTextEdit(targetPath, triggerEl) {
        const wrapper = triggerEl
            && triggerEl.closest('.sticky-media-wrapper');
        if (!wrapper) return;
        const textContainer = wrapper.querySelector('.sticky-text-content');
        if (!textContainer) return;
        if (wrapper.dataset.editing === 'true') return;
        wrapper.dataset.editing = 'true';

        const originalText = textContainer.textContent === '—'
            ? '' : textContainer.textContent;

        const textarea = document.createElement('textarea');
        textarea.className = 'sticky-text-editor';
        textarea.value = originalText;

        const actions = document.createElement('div');
        actions.className = 'sticky-text-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'sticky-text-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', e => {
            e.stopPropagation();
            textarea.remove();
            actions.remove();
            textContainer.style.display = '';
            wrapper.dataset.editing = 'false';
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'sticky-text-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', e => {
            e.stopPropagation();
            submitBtn.disabled = true;
            cancelBtn.disabled = true;
            wrapper.dataset.status = 'command_sent(edit)';
            fetch(`/edit_file/${encodeURIComponent(targetPath)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: textarea.value }),
            }).then(r => {
                if (!r.ok) throw new Error('Failed to edit file');
                return r.json();
            }).then(() => {
                // SSE-driven handleTargetUpdate will repaint content.
                textarea.remove();
                actions.remove();
                textContainer.style.display = '';
                wrapper.dataset.editing = 'false';
            }).catch(err => {
                console.error('Error editing file:', err);
                alert('Failed to edit file: ' + err.message);
                submitBtn.disabled = false;
                cancelBtn.disabled = false;
            });
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        textContainer.style.display = 'none';
        textContainer.parentElement.insertBefore(textarea, textContainer.nextSibling);
        textContainer.parentElement.insertBefore(actions, textarea.nextSibling);
        textarea.focus();
    }

    function createMediaNode(targetPath, filename, mimeType, registeredPaths) {
        // Build a self-contained sticky-media display: a media
        // container (image/video) plus a status overlay that mirrors
        // the tree-node overlay system. We deliberately do NOT use
        // createNode / cloneNode here -- earlier versions tried to
        // reuse the tree-node from the targets tab so they could share
        // the build/edit/delete header menu, but this caused three
        // related bugs:
        //   1. The first sticky view (vertical) registered as the
        //      "real" node; later views (horizontal) cloned the DOM
        //      with cloneNode(true), which doesn't copy event
        //      handlers and doesn't get future updateNode() updates.
        //      That left the horizontal view with a permanent stale
        //      status overlay and broken header buttons.
        //   2. The cloned tree-node carried a clickable expand/
        //      collapse header which broke screenplay layout (and
        //      moved sticky positions out from under arrow anchors).
        //   3. The display:none hidden tree-nodes inside meta rows
        //      added complexity for no UI benefit.
        // The new wrapper is purely a media+overlay surface, with no
        // tree-node coupling.
        const wrapper = document.createElement('div');
        wrapper.className = 'sticky-media-wrapper';
        wrapper.dataset.path = targetPath;
        wrapper.dataset.mimeType = mimeType;

        // Header (filename + build/delete buttons).
        wrapper.appendChild(createMediaHeader(targetPath, filename, mimeType));

        const isImage = mimeType.startsWith('image/');
        const isVideo = mimeType.startsWith('video/');
        const isText = mimeType.startsWith('text/');
        if (isImage) wrapper.classList.add('has-image');
        else if (isVideo) wrapper.classList.add('has-video');
        else if (isText) wrapper.classList.add('has-text');

        const mediaContainer = document.createElement('div');
        mediaContainer.className = isImage
            ? 'image-container'
            : (isVideo ? 'video-container' : 'text-container');
        wrapper.appendChild(mediaContainer);

        // Status overlay. data-status on .sticky-media-wrapper drives
        // its visibility via overlay.css, matching the tree-node UX.
        const overlay = document.createElement('div');
        overlay.className = 'node-status-overlay';
        const overlayText = document.createElement('div');
        overlayText.className = 'node-status-overlay-text';
        overlay.appendChild(overlayText);
        wrapper.appendChild(overlay);

        const state = window.getPathState && window.getPathState(targetPath);
        const status = (state && state.status) || 'notbuilt';
        wrapper.dataset.status = status;
        overlayText.textContent = status.toUpperCase();

        // Register the media container so any blob-cache refresh
        // (typically triggered by the targets tab when an SSE event
        // arrives) repaints us automatically.
        if (isImage) {
            if (window.registerImageContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
            }
            if (status !== 'notbuilt' && window.fetchImage) {
                window.fetchImage(targetPath, false).catch(() => {});
            }
        } else if (isVideo) {
            if (window.registerVideoContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
            }
            if (status !== 'notbuilt' && window.fetchVideo) {
                window.fetchVideo(targetPath, false).catch(() => {});
            }
        } else if (isText) {
            // Text targets: render the file content (or em-dash if
            // not yet built) directly in the container. The
            // monitor_files SSE will repaint this via
            // handleTargetUpdate when content arrives.
            mediaContainer.classList.add('sticky-text-content');
            const state = window.getPathState && window.getPathState(targetPath);
            const content = (state && state.content) ? state.content.trim() : '';
            mediaContainer.textContent = content || '—';
        }
        registeredPaths.add(targetPath);
        return wrapper;
    }

    // Build a sticky note element for a given beat. The background
    // color is set inline so callers can supply per-island colors.
    function createStickyNote(beat, color, registeredPaths, context) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        if (color) sticky.style.background = color;
        sticky.dataset.beat_id = beat.beat_id;

        const grid = document.createElement('div');
        grid.className = 'sticky-meta-grid';
        grid.appendChild(createMetaRow('BEAT_ID', beat.beat_id));
        const ctxBeats = (context && context.beats) || [];
        const ctxOrient = (context && context.orientation) || 'vertical';
        const onSelectFactory = (field) => (newValue) => {
            if (context && typeof context.onUpdateBeatRef === 'function') {
                context.onUpdateBeatRef(beat.beat_id, field, newValue);
            }
        };
        grid.appendChild(createMetaRow(
            'CONTINUES_FROM',
            beat.continues_from_beat_id || '—',
            {
                editable: !!context,
                field: 'continues_from_beat_id',
                currentValue: beat.continues_from_beat_id || '',
                beat, beats: ctxBeats, orientation: ctxOrient,
                onSelect: onSelectFactory('continues_from_beat_id'),
            }));
        grid.appendChild(createMetaRow(
            'INCLUDES',
            beat.include_beat_id || '—',
            {
                editable: !!context,
                field: 'include_beat_id',
                currentValue: beat.include_beat_id || '',
                beat, beats: ctxBeats, orientation: ctxOrient,
                onSelect: onSelectFactory('include_beat_id'),
            }));
        sticky.appendChild(grid);

        const media = document.createElement('div');
        media.className = 'sticky-media-section';
        // Text-backed targets first, so they appear above images/videos.
        const textTargets = [
            ['beat_type',                     'beat_type'],
            ['length_seconds',                'length_seconds'],
            ['dialog_duration_with_padding',  'dialog_duration_with_padding'],
            ['truncate_video',                'truncate_video'],
            ['add_sfx',                       'add_sfx'],
            ['sfx_model',                     'sfx_model'],
        ];
        textTargets.forEach(([key, label]) => {
            media.appendChild(createMediaNode(
                getTargetPath(key, beat.beat_id),
                label, 'text/plain', registeredPaths));
        });
        media.appendChild(createMediaNode(
            getTargetPath('startframe', beat.beat_id),
            'startframe.png', 'image/png', registeredPaths));
        media.appendChild(createMediaNode(
            getTargetPath('video', beat.beat_id),
            'raw.mp4', 'video/mp4', registeredPaths));
        media.appendChild(createMediaNode(
            getTargetPath('debug_video', beat.beat_id),
            'debug.mp4', 'video/mp4', registeredPaths));
        sticky.appendChild(media);

        return sticky;
    }

    function clearRegisteredPaths(board, registeredPaths) {
        // Unregister every media container we attached to sticky
        // notes before the board is torn down, so the blob-cache
        // doesn't keep trying to repaint into orphaned DOM nodes.
        if (board) {
            board.querySelectorAll('.sticky-media-wrapper').forEach(w => {
                const path = w.dataset.path;
                if (!path) return;
                const img = w.querySelector('.image-container');
                const vid = w.querySelector('.video-container');
                if (img && window.unregisterImageContainer) {
                    window.unregisterImageContainer(path, img);
                }
                if (vid && window.unregisterVideoContainer) {
                    window.unregisterVideoContainer(path, vid);
                }
            });
        }
        registeredPaths.clear();
    }

    function handleTargetUpdate(path, metadata) {
        // Update every sticky-media-wrapper for this path: refresh
        // data-status (which the overlay CSS keys off), set the
        // overlay text, and re-trigger the flash animation.
        const wrappers = document.querySelectorAll(
            `.sticky-media-wrapper[data-path="${path}"]`);
        wrappers.forEach(wrapper => {
            const status = metadata.status || 'notbuilt';
            wrapper.dataset.status = status;
            const overlayText = wrapper.querySelector('.node-status-overlay-text');
            if (overlayText) overlayText.textContent = status.toUpperCase();

            // For text-backed wrappers, also refresh the textual content.
            const textContainer = wrapper.querySelector('.sticky-text-content');
            if (textContainer) {
                if (status === 'notbuilt' || !metadata.content) {
                    textContainer.textContent = '—';
                } else {
                    textContainer.textContent = metadata.content.trim() || '—';
                }
            }

            const overlay = wrapper.querySelector('.node-status-overlay');
            if (overlay) {
                overlay.classList.remove('status-flash');
                // Force a reflow so the animation restarts even on
                // back-to-back status changes.
                void overlay.offsetWidth;
                overlay.classList.add('status-flash');
            }
        });

        // When the targets tab already has a tree-node for this path
        // its updateNode -> images.js/videos.js callback chain
        // refreshes the blob cache (and thus every container, sticky
        // or otherwise, registered for that path). When no tree-node
        // exists yet -- e.g. the screenplay rendered before the
        // targets tab finished its initial build -- we kick off the
        // refresh ourselves so the sticky still shows the right thing.
        if (!window.hasNode || !window.hasNode(path)) {
            const mimeType = metadata['mime-type'] || '';
            if (metadata.status === 'built') {
                if (mimeType.startsWith('image/') && window.fetchImage) {
                    window.fetchImage(path, true).then(url => {
                        if (window._refreshImageContainers) {
                            window._refreshImageContainers(path, url);
                        }
                    }).catch(() => {});
                } else if (mimeType.startsWith('video/') && window.fetchVideo) {
                    window.fetchVideo(path, true).then(url => {
                        if (window._refreshVideoContainers) {
                            window._refreshVideoContainers(path, url);
                        }
                    }).catch(() => {});
                }
            } else if (metadata.status === 'notbuilt') {
                if (mimeType.startsWith('image/') && window.clearImageFromContainers) {
                    window.clearImageFromContainers(path);
                } else if (mimeType.startsWith('video/') && window.clearVideoFromContainers) {
                    window.clearVideoFromContainers(path);
                }
            }
        }
    }

    window.ScreenplayStickyNote = {
        createStickyNote,
        clearRegisteredPaths,
        handleTargetUpdate,
        isBeatTargetPath,
        getTargetPath,
    };
})();
