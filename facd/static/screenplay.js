// screenplay.js
//
// This component provides custom rendering for screenplay projects.
// It transforms the display of 'shooting-script.xml' into a paper-like
// view with shots rendered as Fountain-formatted text, and sticky notes
// attached to the right margin showing related targets for each shot.
//
// Dependencies:
// - fountain.min.js must be loaded before this script
// - images.js and videos.js must be loaded before this script for media APIs
// - build.js must be loaded after this script for build menus
//
// The component:
// 1. Detects nodes with path 'shooting-script.xml'
// 2. Parses the XML to extract <shot> elements
// 3. Renders each shot as Fountain HTML on a "paper" background
// 4. Creates sticky notes with shot metadata and related targets
// 5. Uses the standard node/component system for overlays and build menus
// 6. Supports inline editing of shot text with double-click
// 7. Provides hover menu for edit, delete, add above/below operations

(function() {
    // Track screenplay nodes
    const screenplayNodes = new Map();
    // Map from target path to its DOM element
    const targetElements = new Map();
    // Cache for target content/metadata
    const targetCache = new Map();
    // Track paths we've created to avoid re-notifying on our own updates
    const ownedPaths = new Set();
    // Store current shots data for reconstruction
    let currentShots = [];
    // Store the screenplay node element
    let screenplayNodeEl = null;

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
            const referenceShot = el.getAttribute('reference_shot') || '';
            const text = el.textContent || '';
            if (shotId) shots.push({ shotId, referenceShot, text });
        });
        return shots;
    }

    function reconstructXml(shots) {
        let xml = '<shooting-script>\n';
        shots.forEach(shot => {
            const refAttr = shot.referenceShot ? ` reference_shot="${escapeXmlAttr(shot.referenceShot)}"` : '';
            xml += `  <shot shot_id="${escapeXmlAttr(shot.shotId)}"${refAttr}>${escapeXmlText(shot.text)}</shot>\n`;
        });
        xml += '</shooting-script>\n';
        return xml;
    }

    function escapeXmlAttr(str) {
        return str.replace(/&/g, '&amp;')
                  .replace(/"/g, '&quot;')
                  .replace(/'/g, '&apos;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;');
    }

    function escapeXmlText(str) {
        return str.replace(/&/g, '&amp;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;');
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

    function generateNewShotId(baseShotId, direction, existingIds) {
        const suffix = direction === 'above' ? '-' : '+';
        let counter = 1;
        let newId = baseShotId + suffix + counter;
        while (existingIds.has(newId)) {
            counter++;
            newId = baseShotId + suffix + counter;
        }
        return newId;
    }

    function saveScreenplay(shots, message) {
        const xmlContent = reconstructXml(shots);
        return fetch('/edit_file/' + encodeURIComponent('shooting-script.xml'), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: xmlContent, message: message })
        })
        .then(response => {
            if (!response.ok) throw new Error('Failed to save screenplay');
            return response.json();
        });
    }

    function startEditingShot(shotDiv, shotIndex) {
        const contentDiv = shotDiv.querySelector('.screenplay-shot-content');
        if (!contentDiv || contentDiv.classList.contains('editing')) return;

        const shot = currentShots[shotIndex];
        if (!shot) return;

        shotDiv.classList.add('editing');
        contentDiv.classList.add('editing');
        const originalHtml = contentDiv.innerHTML;

        const textarea = document.createElement('textarea');
        textarea.className = 'shot-edit-textarea';
        textarea.value = shot.text;

        const actions = document.createElement('div');
        actions.className = 'shot-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'shot-edit-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            cancelEditing(shotDiv, contentDiv, originalHtml);
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'shot-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitShotEdit(shotDiv, contentDiv, shotIndex, textarea.value, originalHtml);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);

        contentDiv.innerHTML = '';
        contentDiv.appendChild(textarea);
        contentDiv.appendChild(actions);
        textarea.focus();

        // Handle escape key
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                cancelEditing(shotDiv, contentDiv, originalHtml);
            }
        });
    }

    function cancelEditing(shotDiv, contentDiv, originalHtml) {
        shotDiv.classList.remove('editing');
        contentDiv.classList.remove('editing');
        contentDiv.innerHTML = originalHtml;
    }

    function submitShotEdit(shotDiv, contentDiv, shotIndex, newText, originalHtml) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        // Update the shot data
        const updatedShots = currentShots.map((s, i) => {
            if (i === shotIndex) {
                return { ...s, text: newText };
            }
            return s;
        });

        // Show loading state
        contentDiv.innerHTML = '<div class="status-spinner"></div>';

        saveScreenplay(updatedShots, 'edit shot_id=' + shot.shotId)
            .then(() => {
                // Success - SSE will trigger re-render
                shotDiv.classList.remove('editing');
                contentDiv.classList.remove('editing');
            })
            .catch(error => {
                console.error('Error saving shot edit:', error);
                alert('Failed to save: ' + error.message);
                cancelEditing(shotDiv, contentDiv, originalHtml);
            });
    }

    function deleteShot(shotIndex) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        if (!confirm('Are you sure you want to delete shot "' + shot.shotId + '"?')) return;

        // Find shots that reference this one and update them
        const deletedRefShot = shot.referenceShot;
        const updatedShots = currentShots
            .filter((s, i) => i !== shotIndex)
            .map(s => {
                if (s.referenceShot === shot.shotId) {
                    return { ...s, referenceShot: deletedRefShot };
                }
                return s;
            });

        saveScreenplay(updatedShots, 'deleted shot_id=' + shot.shotId)
            .catch(error => {
                console.error('Error deleting shot:', error);
                alert('Failed to delete: ' + error.message);
            });
    }

    function addShotAbove(shotIndex) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        const existingIds = new Set(currentShots.map(s => s.shotId));
        const newShotId = generateNewShotId(shot.shotId, 'above', existingIds);

        // Create temporary shot for editing
        const newShot = {
            shotId: newShotId,
            referenceShot: shot.referenceShot,
            text: '',
            isNew: true
        };

        // Insert temporary shot and update original's reference
        const tempShots = [...currentShots];
        tempShots.splice(shotIndex, 0, newShot);
        // Update original shot's reference to point to new shot
        tempShots[shotIndex + 1] = { ...tempShots[shotIndex + 1], referenceShot: newShotId };

        // Render with new shot in edit mode
        renderShotsWithNewShot(tempShots, shotIndex, newShotId);
    }

    function addShotBelow(shotIndex) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        const existingIds = new Set(currentShots.map(s => s.shotId));
        const newShotId = generateNewShotId(shot.shotId, 'below', existingIds);

        // Create temporary shot for editing
        const newShot = {
            shotId: newShotId,
            referenceShot: shot.shotId,
            text: '',
            isNew: true
        };

        // Insert temporary shot after current
        const tempShots = [...currentShots];
        tempShots.splice(shotIndex + 1, 0, newShot);

        // Update any shots that referenced the original to reference the new shot
        for (let i = 0; i < tempShots.length; i++) {
            if (i !== shotIndex + 1 && tempShots[i].referenceShot === shot.shotId) {
                tempShots[i] = { ...tempShots[i], referenceShot: newShotId };
            }
        }

        // Render with new shot in edit mode
        renderShotsWithNewShot(tempShots, shotIndex + 1, newShotId);
    }

    function renderShotsWithNewShot(tempShots, newShotIndex, newShotId) {
        const container = screenplayNodeEl.querySelector('.screenplay-container');
        if (!container) return;

        // Clear and re-render
        clearTargetRegistrations();
        container.innerHTML = '';

        tempShots.forEach((shot, index) => {
            const shotEl = createShotElement(shot, index, tempShots);
            container.appendChild(shotEl);

            // If this is the new shot, start editing immediately
            if (index === newShotIndex && shot.isNew) {
                shotEl.classList.add('new-shot');
                startEditingNewShot(shotEl, tempShots, newShotIndex, newShotId);
            }
        });
    }

    function startEditingNewShot(shotDiv, tempShots, newShotIndex, newShotId) {
        const contentDiv = shotDiv.querySelector('.screenplay-shot-content');
        if (!contentDiv) return;

        shotDiv.classList.add('editing');
        contentDiv.classList.add('editing');

        const textarea = document.createElement('textarea');
        textarea.className = 'shot-edit-textarea';
        textarea.placeholder = 'Enter shot text...';

        const actions = document.createElement('div');
        actions.className = 'shot-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'shot-edit-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Re-render without the new shot
            transformToScreenplay(screenplayNodeEl);
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'shot-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitNewShot(tempShots, newShotIndex, newShotId, textarea.value);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);

        contentDiv.innerHTML = '';
        contentDiv.appendChild(textarea);
        contentDiv.appendChild(actions);
        textarea.focus();

        // Handle escape key
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                transformToScreenplay(screenplayNodeEl);
            }
        });
    }

    function submitNewShot(tempShots, newShotIndex, newShotId, text) {
        // Update the text and remove isNew flag
        const finalShots = tempShots.map((s, i) => {
            if (i === newShotIndex) {
                const { isNew, ...rest } = s;
                return { ...rest, text: text };
            }
            return s;
        });

        saveScreenplay(finalShots, 'added shot_id=' + newShotId)
            .catch(error => {
                console.error('Error adding shot:', error);
                alert('Failed to add shot: ' + error.message);
                transformToScreenplay(screenplayNodeEl);
            });
    }

    function createHoverMenu(shotIndex) {
        const menu = document.createElement('div');
        menu.className = 'shot-hover-menu';

        // Edit button
        const editBtn = document.createElement('button');
        editBtn.innerHTML = '✏️';
        editBtn.title = 'Edit shot';
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const shotDiv = menu.closest('.screenplay-shot');
            if (shotDiv) startEditingShot(shotDiv, shotIndex);
        });
        menu.appendChild(editBtn);

        // Add above button
        const addAboveBtn = document.createElement('button');
        addAboveBtn.innerHTML = '➕⬆️';
        addAboveBtn.title = 'Add shot above';
        addAboveBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addShotAbove(shotIndex);
        });
        menu.appendChild(addAboveBtn);

        // Add below button
        const addBelowBtn = document.createElement('button');
        addBelowBtn.innerHTML = '➕⬇️';
        addBelowBtn.title = 'Add shot below';
        addBelowBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addShotBelow(shotIndex);
        });
        menu.appendChild(addBelowBtn);

        // Delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = 'Delete shot';
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteShot(shotIndex);
        });
        menu.appendChild(deleteBtn);

        return menu;
    }

    function createStickyNote(shot) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        sticky.dataset.shotId = shot.shotId;

        const metaGrid = document.createElement('div');
        metaGrid.className = 'sticky-meta-grid';

        // Static metadata rows
        metaGrid.appendChild(createMetaRow('SHOT_ID', shot.shotId));
        metaGrid.appendChild(createMetaRow('REFERENCE_SHOT', shot.referenceShot || '—'));

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
        // Do not set data-is-target here - these are path nodes that may or may not exist yet

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
            // If we have cached data with a real status, this is a path not a target
            if (cached.status && cached.status !== 'unknown') {
                delete row.dataset.isTarget;
            }
        } else {
            // No cached data means this is a target (file doesn't exist yet)
            row.dataset.isTarget = 'true';
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
        container.dataset.mimeType = mimeType;
        // Start as a target (file may not exist); will be updated when we get status

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
            // Register with global image system
            window.registerImageContainer(targetPath, mediaWrapper, 'leaf-image');
        } else {
            container.classList.add('has-video');
            // Register with global video system
            window.registerVideoContainer(targetPath, mediaWrapper, 'leaf-video');
        }

        targetElements.set(targetPath, container);
        ownedPaths.add(targetPath);

        // Load media if cached and available
        const cached = targetCache.get(targetPath);
        if (cached && (cached.status === 'fresh' || cached.status === 'stale')) {
            container.dataset.status = cached.status;
            // File exists, so this is a path not a target
            delete container.dataset.isTarget;
            loadMedia(targetPath, isImage);
        } else {
            // No data or unknown status - treat as target
            container.dataset.isTarget = 'true';
        }

        setTimeout(() => {
            window.notifyComponents(container, container.dataset.status || 'unknown', true);
        }, 0);

        return container;
    }

    function loadMedia(path, isImage) {
        if (isImage) {
            window.fetchImage(path, false).catch(() => {});
        } else {
            window.fetchVideo(path, false).catch(() => {});
        }
    }

    function createShotElement(shot, index, shotsArray) {
        const shotDiv = document.createElement('div');
        shotDiv.className = 'screenplay-shot';
        shotDiv.dataset.shotId = shot.shotId;
        shotDiv.dataset.shotIndex = index;

        // Add hover menu
        shotDiv.appendChild(createHoverMenu(index));

        const content = document.createElement('div');
        content.className = 'screenplay-shot-content';
        content.innerHTML = renderFountain(shot.text);

        // Double-click to edit
        content.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            startEditingShot(shotDiv, index);
        });

        shotDiv.appendChild(content);

        // Only add sticky note for non-new shots
        if (!shot.isNew) {
            shotDiv.appendChild(createStickyNote(shot));
        } else {
            // Placeholder sticky for new shots
            const placeholder = document.createElement('div');
            placeholder.className = 'screenplay-sticky-note';
            placeholder.innerHTML = '<em>New shot</em>';
            shotDiv.appendChild(placeholder);
        }

        return shotDiv;
    }

    function clearTargetRegistrations() {
        const oldData = screenplayNodes.get('shooting-script.xml');
        if (oldData) {
            for (const p of oldData.shotPaths) {
                const el = targetElements.get(p);
                if (el) {
                    const imgContainer = el.querySelector('.image-container');
                    const vidContainer = el.querySelector('.video-container');
                    if (imgContainer) window.unregisterImageContainer(p, imgContainer);
                    if (vidContainer) window.unregisterVideoContainer(p, vidContainer);
                }
                targetElements.delete(p);
                ownedPaths.delete(p);
            }
        }
    }

    function transformToScreenplay(nodeEl) {
        const path = nodeEl.dataset.path;
        if (path !== 'shooting-script.xml') return;

        screenplayNodeEl = nodeEl;
        nodeEl.classList.add('screenplay-node', 'expanded');

        const content = nodeEl.dataset.content;
        if (!content) return;

        const shots = parseScreenplayXml(content);
        if (shots.length === 0) return;

        // Store current shots for editing operations
        currentShots = shots;

        let container = nodeEl.querySelector('.screenplay-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'screenplay-container';
            const header = nodeEl.querySelector('.tree-header');
            if (header) header.after(container);
            else nodeEl.appendChild(container);
        }

        // Clear old registrations
        clearTargetRegistrations();

        container.innerHTML = '';
        const shotPaths = [];

        shots.forEach((shot, index) => {
            container.appendChild(createShotElement(shot, index, shots));
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

        // Determine if this is a target (doesn't exist) or a path (exists)
        // Files with status fresh/stale/building/queued exist or are being built
        const isExistingPath = status === 'fresh' || status === 'stale';
        if (isExistingPath) {
            // This is an existing path, not a target
            delete element.dataset.isTarget;
        } else if (status === 'deleted' || status === 'unknown') {
            // File doesn't exist, treat as target
            element.dataset.isTarget = 'true';
        }
        // For building/queued, keep current state

        // Update text value display
        const valueSpan = element.querySelector('.sticky-target-value');
        if (valueSpan && content) {
            valueSpan.textContent = content.trim() || '—';
        }

        // Handle media updates - use global fetch functions which handle container refresh
        const isImage = element.dataset.mimeType?.startsWith('image/');
        const isVideo = element.dataset.mimeType?.startsWith('video/');
        
        if (status === 'fresh') {
            // Force refresh media
            if (isImage) {
                window.fetchImage(path, true).catch(() => {});
            } else if (isVideo) {
                window.fetchVideo(path, true).catch(() => {});
            }
        } else if (status === 'deleted') {
            // Clear media from containers
            if (isImage) {
                window.clearImageFromContainers(path);
            } else if (isVideo) {
                window.clearVideoFromContainers(path);
            }
        } else if (isExistingPath) {
            // Load media if not already loaded
            if (isImage) {
                window.fetchImage(path, false).catch(() => {});
            } else if (isVideo) {
                window.fetchVideo(path, false).catch(() => {});
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
