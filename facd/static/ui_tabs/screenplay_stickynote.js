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
        startframe: 'beats/$BEAT_ID/beat_type=standard/startframe.png',
        video: 'beats/$BEAT_ID/raw.mp4',
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

    function createMetaRow(label, value) {
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
        return row;
    }

    function createTargetRow(label, targetPath, registeredPaths) {
        const row = document.createElement('div');
        row.className = 'sticky-meta-row sticky-target-row';

        const labelSpan = document.createElement('span');
        labelSpan.className = 'sticky-meta-label';
        labelSpan.textContent = label;
        row.appendChild(labelSpan);

        const valueSpan = document.createElement('span');
        valueSpan.className = 'sticky-meta-value sticky-target-value';
        valueSpan.dataset.targetPath = targetPath;

        // Initial text content from any cached path state delivered
        // via the SSE stream so far. No tree-node is created or
        // hidden in the sticky -- the value span is the entire UI.
        const state = window.getPathState && window.getPathState(targetPath);
        if (state && state.status !== 'notbuilt' && state.content) {
            valueSpan.textContent = state.content.trim() || '—';
        } else {
            valueSpan.textContent = '—';
        }

        row.appendChild(valueSpan);
        registeredPaths.add(targetPath);
        return row;
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

        const isImage = mimeType.startsWith('image/');
        wrapper.classList.add(isImage ? 'has-image' : 'has-video');

        const mediaContainer = document.createElement('div');
        mediaContainer.className = isImage ? 'image-container' : 'video-container';
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
        } else {
            if (window.registerVideoContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
            }
            if (status !== 'notbuilt' && window.fetchVideo) {
                window.fetchVideo(targetPath, false).catch(() => {});
            }
        }
        registeredPaths.add(targetPath);
        return wrapper;
    }

    // Build a sticky note element for a given beat. The background
    // color is set inline so callers can supply per-island colors.
    function createStickyNote(beat, color, registeredPaths) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        if (color) sticky.style.background = color;
        sticky.dataset.beat_id = beat.beat_id;

        const grid = document.createElement('div');
        grid.className = 'sticky-meta-grid';
        grid.appendChild(createMetaRow('BEAT_ID', beat.beat_id));
        grid.appendChild(createMetaRow('CONTINUES_FROM',
            beat.continues_from_beat_id || '—'));
        grid.appendChild(createMetaRow('INCLUDES',
            beat.include_beat_id || '—'));
        grid.appendChild(createTargetRow('beat_type',
            getTargetPath('beat_type', beat.beat_id), registeredPaths));
        grid.appendChild(createTargetRow('length_seconds',
            getTargetPath('length_seconds', beat.beat_id), registeredPaths));
        sticky.appendChild(grid);

        const media = document.createElement('div');
        media.className = 'sticky-media-section';
        media.appendChild(createMediaNode(
            getTargetPath('startframe', beat.beat_id),
            'startframe.png', 'image/png', registeredPaths));
        media.appendChild(createMediaNode(
            getTargetPath('video', beat.beat_id),
            'raw.mp4', 'video/mp4', registeredPaths));
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
        // Update every sticky note that shows this target (both the
        // screenplay and storyboard views can be live at once).
        const valueSpans = document.querySelectorAll(
            `.sticky-target-value[data-target-path="${path}"]`);
        valueSpans.forEach(valueSpan => {
            if (metadata.status === 'notbuilt') {
                valueSpan.textContent = '—';
            } else if (metadata.content) {
                valueSpan.textContent = metadata.content.trim() || '—';
            }
        });

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
