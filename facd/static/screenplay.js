// screenplay.js
//
// This component provides custom rendering for screenplay projects.
// It transforms the display of 'shooting-script.xml' into a paper-like
// view with shots rendered as Fountain-formatted text, and sticky notes
// attached to the right margin showing related targets for each shot.
//
// Dependencies:
// - fountain.min.js must be loaded before this script
// - build.js must be loaded after this script for build menus
//
// The component:
// 1. Detects nodes with path 'shooting-script.xml'
// 2. Parses the XML to extract <shot> elements
// 3. Renders each shot as Fountain HTML on a "paper" background
// 4. Creates sticky notes with shot metadata and related targets
// 5. Uses the standard node/component system for overlays and build menus

(function() {
    // Track screenplay nodes
    const screenplayNodes = new Map();
    // Map from target path to its DOM element
    const targetElements = new Map();
    // Cache for target content/metadata
    const targetCache = new Map();
    // Track paths we've created to avoid re-notifying on our own updates
    const ownedPaths = new Set();

    // Target patterns for each shot
    const SHOT_TARGETS = {
        shot_type: 'shots/$SHOT_ID/shot_type',
        length_seconds: 'shots/$SHOT_ID/length_seconds',
        startframe: 'shots/$SHOT_ID/shot_type=standard/startframe.png',
        video: 'shots/$SHOT_ID/shot_type=standard/raw.mp4'
    };

    function getTargetPath(key, shotId) {
        return SHOT_TARGETS[key].replace('$SHOT_ID', shotId);
    }

    function parseScreenplayXml(xmlContent) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(xmlContent, 'text/xml');
        const shots = [];
        doc.querySelectorAll('shot').forEach(el => {
            const shotId = el.getAttribute('shot_id');
            const referenceId = el.getAttribute('reference_id') || '';
            const text = el.textContent || '';
            if (shotId) shots.push({ shotId, referenceId, text });
        });
        return shots;
    }

    function renderFountain(text) {
        if (typeof fountain === 'undefined') {
            const escaped = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\n/g, '<br>\n');
            return `<pre class="fountain-fallback">${escaped}</pre>`;
        }
        return fountain.parse(text).html.script || '';
    }

    function createStickyNote(shot) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        sticky.dataset.shotId = shot.shotId;

        const metaGrid = document.createElement('div');
        metaGrid.className = 'sticky-meta-grid';

        // Static metadata rows
        metaGrid.appendChild(createMetaRow('SHOT_ID', shot.shotId));
        metaGrid.appendChild(createMetaRow('REFERENCE_ID', shot.referenceId || '—'));

        // Target rows - these are tree nodes that get component callbacks
        const shotTypePath = getTargetPath('shot_type', shot.shotId);
        metaGrid.appendChild(createTargetRow('shot_type', shotTypePath));

        const lengthPath = getTargetPath('length_seconds', shot.shotId);
        metaGrid.appendChild(createTargetRow('length_seconds', lengthPath));

        sticky.appendChild(metaGrid);

        // Media section
        const mediaSection = document.createElement('div');
        mediaSection.className = 'sticky-media-section';

        const startframePath = getTargetPath('startframe', shot.shotId);
        mediaSection.appendChild(createMediaNode(startframePath, 'startframe.png', 'image/png'));

        const videoPath = getTargetPath('video', shot.shotId);
        mediaSection.appendChild(createMediaNode(videoPath, 'raw.mp4', 'video/mp4'));

        sticky.appendChild(mediaSection);
        return sticky;
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

    function createTargetRow(label, targetPath) {
        const row = document.createElement('div');
        row.className = 'sticky-meta-row sticky-target-row tree-node path leaf';
        row.dataset.path = targetPath;
        row.dataset.isTarget = 'true';

        const labelSpan = document.createElement('span');
        labelSpan.className = 'sticky-meta-label';
        labelSpan.textContent = label;
        row.appendChild(labelSpan);

        const valueSpan = document.createElement('span');
        valueSpan.className = 'sticky-meta-value sticky-target-value';
        valueSpan.textContent = '—';
        row.appendChild(valueSpan);

        targetElements.set(targetPath, row);
        ownedPaths.add(targetPath);

        // Apply cached data if available
        const cached = targetCache.get(targetPath);
        if (cached) {
            if (cached.content) valueSpan.textContent = cached.content.trim() || '—';
            row.dataset.status = cached.status;
        }

        // Notify components (deferred to ensure all are registered)
        setTimeout(() => {
            window.notifyComponents(row, row.dataset.status || 'unknown', true);
        }, 0);

        return row;
    }

    function createMediaNode(targetPath, filename, mimeType) {
        const container = document.createElement('div');
        container.className = 'sticky-media-container tree-node path leaf expanded';
        container.dataset.path = targetPath;
        container.dataset.isTarget = 'true';
        container.dataset.mimeType = mimeType;

        const header = document.createElement('div');
        header.className = 'tree-header';

        const toggle = document.createElement('button');
        toggle.className = 'tree-toggle';
        toggle.innerHTML = '&#9654;';
        header.appendChild(toggle);

        const label = document.createElement('span');
        label.className = 'tree-label';
        label.textContent = filename;
        header.appendChild(label);

        container.appendChild(header);

        // Media wrapper - matches standard image/video container pattern
        const isImage = mimeType.startsWith('image/');
        const mediaWrapper = document.createElement('div');
        mediaWrapper.className = isImage ? 'image-container' : 'video-container';
        container.appendChild(mediaWrapper);

        if (isImage) {
            container.classList.add('has-image');
        } else {
            container.classList.add('has-video');
        }

        targetElements.set(targetPath, container);
        ownedPaths.add(targetPath);

        // Load media if cached and available
        const cached = targetCache.get(targetPath);
        if (cached && (cached.status === 'fresh' || cached.status === 'stale')) {
            container.dataset.status = cached.status;
            loadMedia(mediaWrapper, targetPath, isImage);
        }

        setTimeout(() => {
            window.notifyComponents(container, container.dataset.status || 'unknown', true);
        }, 0);

        return container;
    }

    function loadMedia(container, path, isImage) {
        fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                container.innerHTML = '';
                if (isImage) {
                    const img = document.createElement('img');
                    img.src = url;
                    img.className = 'leaf-image';
                    container.appendChild(img);
                } else {
                    const video = document.createElement('video');
                    video.src = url;
                    video.className = 'leaf-video';
                    video.controls = true;
                    video.preload = 'metadata';
                    container.appendChild(video);
                }
            })
            .catch(() => {});
    }

    function createShotElement(shot) {
        const shotDiv = document.createElement('div');
        shotDiv.className = 'screenplay-shot';
        shotDiv.dataset.shotId = shot.shotId;

        const content = document.createElement('div');
        content.className = 'screenplay-shot-content';
        content.innerHTML = renderFountain(shot.text);
        shotDiv.appendChild(content);

        shotDiv.appendChild(createStickyNote(shot));
        return shotDiv;
    }

    function transformToScreenplay(nodeEl) {
        const path = nodeEl.dataset.path;
        if (path !== 'shooting-script.xml') return;

        nodeEl.classList.add('screenplay-node', 'expanded');

        const content = nodeEl.dataset.content;
        if (!content) return;

        const shots = parseScreenplayXml(content);
        if (shots.length === 0) return;

        let container = nodeEl.querySelector('.screenplay-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'screenplay-container';
            const header = nodeEl.querySelector('.tree-header');
            if (header) header.after(container);
            else nodeEl.appendChild(container);
        }

        // Clear old registrations
        const oldData = screenplayNodes.get(path);
        if (oldData) {
            for (const p of oldData.shotPaths) {
                targetElements.delete(p);
                ownedPaths.delete(p);
            }
        }

        container.innerHTML = '';
        const shotPaths = [];

        shots.forEach(shot => {
            container.appendChild(createShotElement(shot));
            Object.keys(SHOT_TARGETS).forEach(key => {
                shotPaths.push(getTargetPath(key, shot.shotId));
            });
        });

        screenplayNodes.set(path, { nodeEl, shotPaths });

        const metadata = nodeEl.querySelector(':scope > .metadata');
        if (metadata) metadata.style.display = 'none';
    }

    function updateTargetElement(path, content, status, mimeType) {
        const element = targetElements.get(path);
        if (!element) return;

        element.dataset.status = status;

        // Update text value display
        const valueSpan = element.querySelector('.sticky-target-value');
        if (valueSpan && content) {
            valueSpan.textContent = content.trim() || '—';
        }

        // Update media container
        const mediaContainer = element.querySelector('.image-container, .video-container');
        if (mediaContainer && (status === 'fresh' || status === 'stale')) {
            const isImage = element.dataset.mimeType?.startsWith('image/');
            if (status === 'fresh' || !mediaContainer.querySelector('img, video')) {
                loadMedia(mediaContainer, path, isImage);
            }
        }

        // Notify other components (overlay, build) about status change
        // but don't trigger ourselves again
        window.notifyComponents(element, status, false);
    }

    function isScreenplayTargetPath(path) {
        const match = path.match(/^shots\/([^/]+)\//);
        if (!match) return false;
        const shotId = match[1];
        return Object.values(SHOT_TARGETS).some(pattern => 
            path === pattern.replace('$SHOT_ID', shotId)
        );
    }

    // Register component callback
    window.registerComponent(function(nodeEl, status, isNew) {
        const path = nodeEl.dataset.path;
        if (!path) return;

        // Handle shooting-script.xml
        if (path === 'shooting-script.xml') {
            if (isNew) transformToScreenplay(nodeEl);
            else if (status === 'fresh') transformToScreenplay(nodeEl);
            return;
        }

        // Skip if this is one of our own nodes - we handle them via SSE
        if (ownedPaths.has(path)) return;

        // Handle screenplay target paths from the main tree
        if (isScreenplayTargetPath(path)) {
            targetCache.set(path, {
                content: nodeEl.dataset.content || '',
                status: status,
                mimeType: nodeEl.dataset.mimeType || ''
            });
            updateTargetElement(path, nodeEl.dataset.content || '', status, nodeEl.dataset.mimeType || '');
        }
    });

    // Register SSE handler for screenplay targets
    window.registerPathHandler(function(path, metadata, isNew) {
        if (!isScreenplayTargetPath(path)) return;

        targetCache.set(path, {
            content: metadata.content || '',
            status: metadata.status,
            mimeType: metadata['mime-type'] || ''
        });
        updateTargetElement(path, metadata.content || '', metadata.status, metadata['mime-type'] || '');
    });
})();
