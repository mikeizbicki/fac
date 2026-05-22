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
        row.appendChild(valueSpan);

        const nodeEl = window.createNode(targetPath, {
            type: 'target', isLeaf: true, order: 0, parent: null, label,
        });
        if (nodeEl) {
            nodeEl.style.display = 'none';
            row.appendChild(nodeEl);
            if (window.isFilePath && window.isFilePath(targetPath)) {
                const c = nodeEl.dataset.content;
                valueSpan.textContent = c ? c.trim() : '—';
            } else {
                valueSpan.textContent = '—';
            }
        } else {
            const existing = window.getNode(targetPath);
            valueSpan.textContent = (existing && existing.dataset.content)
                ? existing.dataset.content.trim() : '—';
        }
        registeredPaths.add(targetPath);
        return row;
    }

    function createMediaNode(targetPath, filename, mimeType, registeredPaths) {
        const wrapper = document.createElement('div');
        wrapper.className = 'sticky-media-wrapper';
        const nodeEl = window.createNode(targetPath, {
            type: 'target', mimeType, isLeaf: true, order: 0,
            parent: wrapper, label: filename,
        });
        const isImage = mimeType.startsWith('image/');
        let mediaContainer = null;
        // createNode may return an existing node that is still attached
        // to another view's wrapper. Only treat it as "ours" if it
        // actually landed inside our wrapper.
        if (nodeEl && nodeEl.parentElement === wrapper) {
            nodeEl.classList.add('expanded');
            mediaContainer = nodeEl.querySelector(
                isImage ? '.image-container' : '.video-container');
        } else {
            // Node either was not created (null) or is owned by another
            // view's wrapper. Build a standalone media container in our
            // wrapper so this sticky still shows the media; it will be
            // populated from the blob cache by registerImageContainer /
            // registerVideoContainer.
            mediaContainer = document.createElement('div');
            mediaContainer.className = isImage ? 'image-container' : 'video-container';
            wrapper.appendChild(mediaContainer);
        }
        if (mediaContainer) {
            if (isImage && window.registerImageContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                if (window.isFilePath && window.isFilePath(targetPath) && window.fetchImage) {
                    window.fetchImage(targetPath, false).catch(() => {});
                }
            } else if (!isImage && window.registerVideoContainer) {
                window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
                if (window.isFilePath && window.isFilePath(targetPath) && window.fetchVideo) {
                    window.fetchVideo(targetPath, false).catch(() => {});
                }
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
        if (beat.includes_beat_id) {
            grid.appendChild(createMetaRow('INCLUDES', beat.includes_beat_id));
        }
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

    function clearRegisteredPaths(registeredPaths) {
        for (const path of registeredPaths) {
            const nodeEl = window.getNode(path);
            if (nodeEl) {
                const img = nodeEl.querySelector('.image-container');
                const vid = nodeEl.querySelector('.video-container');
                if (img && window.unregisterImageContainer) window.unregisterImageContainer(path, img);
                if (vid && window.unregisterVideoContainer) window.unregisterVideoContainer(path, vid);
                if (nodeEl.style.display === 'none') {
                    window.clearNodeFromRegistry(path);
                }
            }
        }
        registeredPaths.clear();
    }

    function handleTargetUpdate(path, metadata) {
        if (window.hasNode(path)) {
            window.updateNode(path, {
                status: metadata.status,
                mimeType: metadata['mime-type'],
                content: metadata.content,
            });
        }
        // Update every sticky note that shows this target (both the
        // screenplay and storyboard views can be live at once).
        const valueSpans = document.querySelectorAll(
            `.sticky-target-value[data-target-path="${path}"]`);
        valueSpans.forEach(valueSpan => {
            if (metadata.content) {
                valueSpan.textContent = metadata.content.trim() || '—';
            }
        });
        const nodeEl = window.getNode(path);
        if (!nodeEl) return;
        const mimeType = nodeEl.dataset.mimeType || metadata['mime-type'];
        const isImage = mimeType?.startsWith('image/');
        const isVideo = mimeType?.startsWith('video/');
        const status = metadata.status;
        if (status === 'fresh' || status === 'stale') {
            if (isImage && window.fetchImage) window.fetchImage(path, status === 'fresh').catch(() => {});
            else if (isVideo && window.fetchVideo) window.fetchVideo(path, status === 'fresh').catch(() => {});
        } else if (status === 'deleted') {
            if (isImage && window.clearImageFromContainers) window.clearImageFromContainers(path);
            else if (isVideo && window.clearVideoFromContainers) window.clearVideoFromContainers(path);
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
