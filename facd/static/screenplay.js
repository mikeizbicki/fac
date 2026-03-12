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
// 5. Integrates with the overlay and build systems for target status

(function() {
    // Track screenplay nodes and their associated target paths
    const screenplayNodes = new Map();
    // Map from target path to its DOM element for status updates
    const targetElements = new Map();
    // Cache for target content/metadata
    const targetCache = new Map();

    // Target patterns for each shot
    const SHOT_TARGETS = {
        shot_type: 'shots/$SHOT_ID/shot_type',
        length_seconds: 'shots/$SHOT_ID/length_seconds',
        startframe: 'shots/$SHOT_ID/shot_type=standard/startframe.png',
        video: 'shots/$SHOT_ID/shot_type=standard/raw.mp4'
    };

    function getTargetPath(targetKey, shotId) {
        return SHOT_TARGETS[targetKey].replace('$SHOT_ID', shotId);
    }

    function parseScreenplayXml(xmlContent) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(xmlContent, 'text/xml');
        const shots = [];
        const shotElements = doc.querySelectorAll('shot');
        shotElements.forEach(shotEl => {
            const shotId = shotEl.getAttribute('shot_id');
            const referenceId = shotEl.getAttribute('reference_id') || '';
            const text = shotEl.textContent || '';
            if (shotId) {
                shots.push({ shotId, referenceId, text });
            }
        });
        return shots;
    }

    function renderFountain(text) {
        if (typeof fountain === 'undefined') {
            console.warn('fountain.js not loaded, displaying raw text');
            const escaped = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\n/g, '<br>\n')
                .replace(/  /g, '&nbsp;&nbsp;');
            return `<pre class="fountain-fallback">${escaped}</pre>`;
        }
        const output = fountain.parse(text);
        return output.html.script || '';
    }

    function createStickyNote(shot) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        sticky.dataset.shotId = shot.shotId;

        // Metadata grid
        const metaGrid = document.createElement('div');
        metaGrid.className = 'sticky-meta-grid';

        // SHOT_ID row
        const shotIdRow = createMetaRow('SHOT_ID', shot.shotId);
        metaGrid.appendChild(shotIdRow);

        // REFERENCE_ID row
        const refIdRow = createMetaRow('REFERENCE_ID', shot.referenceId || '—');
        metaGrid.appendChild(refIdRow);

        // shot_type target row
        const shotTypePath = getTargetPath('shot_type', shot.shotId);
        const shotTypeRow = createTargetRow('shot_type', shotTypePath);
        metaGrid.appendChild(shotTypeRow);

        // length_seconds target row
        const lengthPath = getTargetPath('length_seconds', shot.shotId);
        const lengthRow = createTargetRow('length_seconds', lengthPath);
        metaGrid.appendChild(lengthRow);

        sticky.appendChild(metaGrid);

        // Media section
        const mediaSection = document.createElement('div');
        mediaSection.className = 'sticky-media-section';

        // startframe.png
        const startframePath = getTargetPath('startframe', shot.shotId);
        const imageContainer = createMediaContainer(startframePath, 'image');
        mediaSection.appendChild(imageContainer);

        // raw.mp4
        const videoPath = getTargetPath('video', shot.shotId);
        const videoContainer = createMediaContainer(videoPath, 'video');
        mediaSection.appendChild(videoContainer);

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

        const labelSpan = document.createElement('span');
        labelSpan.className = 'sticky-meta-label';
        labelSpan.textContent = label;
        row.appendChild(labelSpan);

        const valueSpan = document.createElement('span');
        valueSpan.className = 'sticky-meta-value sticky-target-value';
        valueSpan.dataset.targetPath = targetPath;
        valueSpan.textContent = '—';
        row.appendChild(valueSpan);

        // Register for tracking
        targetElements.set(targetPath, row);

        // Trigger build.js to add header menu
        notifyComponentsNewNode(row);

        return row;
    }

    function createMediaContainer(targetPath, mediaType) {
        const container = document.createElement('div');
        container.className = `sticky-media-container tree-node path leaf has-${mediaType === 'image' ? 'image' : 'video'} expanded`;
        container.dataset.path = targetPath;
        container.dataset.mimeType = mediaType === 'image' ? 'image/png' : 'video/mp4';

        // Header with label - build.js will add the menu
        const header = document.createElement('div');
        header.className = 'tree-header';

        const toggle = document.createElement('button');
        toggle.className = 'tree-toggle';
        toggle.innerHTML = '&#9654;';
        header.appendChild(toggle);

        const label = document.createElement('span');
        label.className = 'tree-label';
        label.textContent = mediaType === 'image' ? 'startframe.png' : 'raw.mp4';
        header.appendChild(label);

        container.appendChild(header);

        // Media container - matches image-container/video-container pattern
        const mediaWrapper = document.createElement('div');
        mediaWrapper.className = mediaType === 'image' ? 'image-container' : 'video-container';
        mediaWrapper.dataset.targetPath = targetPath;
        mediaWrapper.dataset.mediaType = mediaType;
        container.appendChild(mediaWrapper);

        // Register for tracking
        targetElements.set(targetPath, container);

        // Trigger build.js to add header menu (isNew=true)
        notifyComponentsNewNode(container);

        return container;
    }

    function notifyComponentsNewNode(nodeEl) {
        // Defer to next tick so all components are registered
        setTimeout(() => {
            for (const callback of window._componentCallbacks || []) {
                callback(nodeEl, nodeEl.dataset.status || 'unknown', true);
            }
        }, 0);
    }

    function createShotElement(shot) {
        const shotDiv = document.createElement('div');
        shotDiv.className = 'screenplay-shot';
        shotDiv.dataset.shotId = shot.shotId;

        // Shot content (the paper)
        const content = document.createElement('div');
        content.className = 'screenplay-shot-content';
        content.innerHTML = renderFountain(shot.text);
        shotDiv.appendChild(content);

        // Sticky note (margin)
        const sticky = createStickyNote(shot);
        shotDiv.appendChild(sticky);

        return shotDiv;
    }

    function transformToScreenplay(nodeEl) {
        const path = nodeEl.dataset.path;
        if (path !== 'shooting-script.xml') return;

        // Prevent collapsing
        nodeEl.classList.add('screenplay-node');
        nodeEl.classList.add('expanded');

        // Get the XML content
        const content = nodeEl.dataset.content;
        if (!content) return;

        // Parse XML and extract shots
        const shots = parseScreenplayXml(content);
        if (shots.length === 0) return;

        // Create screenplay container
        let screenplayContainer = nodeEl.querySelector('.screenplay-container');
        if (!screenplayContainer) {
            screenplayContainer = document.createElement('div');
            screenplayContainer.className = 'screenplay-container';
            
            // Insert after header
            const header = nodeEl.querySelector('.tree-header');
            if (header) {
                header.after(screenplayContainer);
            } else {
                nodeEl.appendChild(screenplayContainer);
            }
        }

        // Clear and rebuild
        screenplayContainer.innerHTML = '';
        const shotPaths = [];

        shots.forEach(shot => {
            const shotEl = createShotElement(shot);
            screenplayContainer.appendChild(shotEl);

            // Collect all target paths for this shot
            Object.keys(SHOT_TARGETS).forEach(key => {
                shotPaths.push(getTargetPath(key, shot.shotId));
            });
        });

        // Store association
        screenplayNodes.set(path, { nodeEl, shotPaths });

        // Hide the default metadata display
        const metadata = nodeEl.querySelector(':scope > .metadata');
        if (metadata) {
            metadata.style.display = 'none';
        }
    }

    function updateTargetContent(path, content, status, mimeType) {
        targetCache.set(path, { content, status, mimeType });

        const element = targetElements.get(path);
        if (!element) return;

        // Update status attribute for styling
        element.dataset.status = status;

        // For text targets, update the value display
        const valueSpan = element.querySelector('.sticky-target-value');
        if (valueSpan && content) {
            valueSpan.textContent = content.trim() || '—';
        }

        // For media targets, update the media container
        const mediaContainer = element.querySelector('.image-container, .video-container');
        if (mediaContainer) {
            updateMediaContainer(mediaContainer, path, content, status, mimeType);
        }
    }

    function updateMediaContainer(container, path, content, status, mimeType) {
        const mediaType = container.dataset.mediaType;

        // If status indicates content exists, load it
        if (status === 'fresh' || status === 'stale') {
            if (mediaType === 'image' && !container.querySelector('img')) {
                loadImage(container, path);
            } else if (mediaType === 'video' && !container.querySelector('video')) {
                loadVideo(container, path);
            }
        }
    }

    function loadImage(container, path) {
        fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const img = document.createElement('img');
                img.src = url;
                img.className = 'leaf-image';
                container.innerHTML = '';
                container.appendChild(img);
            })
            .catch(() => {
                // Keep container empty for missing files
            });
    }

    function loadVideo(container, path) {
        fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const video = document.createElement('video');
                video.src = url;
                video.className = 'leaf-video';
                video.controls = true;
                video.preload = 'metadata';
                container.innerHTML = '';
                container.appendChild(video);
            })
            .catch(() => {
                // Keep container empty for missing files
            });
    }

    function refreshScreenplayIfNeeded(nodeEl) {
        const path = nodeEl.dataset.path;
        if (path !== 'shooting-script.xml') return;

        // Re-transform if content changed
        transformToScreenplay(nodeEl);
    }

    // Check if a path is a target we care about for screenplay
    function isScreenplayTargetPath(path) {
        // Check if path matches any of our target patterns
        const match = path.match(/^shots\/([^/]+)\//);
        if (!match) return false;

        const shotId = match[1];
        return Object.values(SHOT_TARGETS).some(pattern => {
            const expectedPath = pattern.replace('$SHOT_ID', shotId);
            return path === expectedPath;
        });
    }

    // Store reference to all component callbacks for notifying sticky elements
    window._componentCallbacks = window._componentCallbacks || [];

    // Wrap registerComponent to capture all callbacks
    const originalRegister = window.registerComponent;
    window.registerComponent = function(callback) {
        window._componentCallbacks.push(callback);
        originalRegister(callback);
    };

    window.registerComponent(function(nodeEl, status, isNew) {
        const nodePath = nodeEl.dataset.path;
        if (!nodePath) return;
        const path = nodePath;

        // Handle shooting-script.xml
        if (path === 'shooting-script.xml') {
            if (isNew) {
                transformToScreenplay(nodeEl);
            } else if (status === 'fresh') {
                refreshScreenplayIfNeeded(nodeEl);
            }
            return;
        }

        // Handle screenplay target paths - update sticky note elements
        if (isScreenplayTargetPath(path)) {
            const content = nodeEl.dataset.content || '';
            const mimeType = nodeEl.dataset.mimeType || '';
            updateTargetContent(path, content, status, mimeType);
        }
    });
})();
