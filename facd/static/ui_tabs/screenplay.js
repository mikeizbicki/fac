// screenplay.js
//
// This component provides a custom tab view for screenplay projects.
// It renders 'shooting-script.xml' as a paper-like view with shots
// formatted as Fountain text, and sticky notes showing related targets.
//
// This is a standalone tab component that:
// 1. Registers a "Screenplay" tab in the main pane
// 2. Connects to /monitor_files SSE to get shooting-script.xml content
// 3. Parses the XML to extract <shot> elements
// 4. Renders each shot as Fountain HTML on a "paper" background
// 5. Creates sticky notes with shot metadata and related targets
// 6. Uses the nodes.js API for target nodes, getting overlays and build menus for free
//
// The nodes.js API handles the path/target duality automatically - when we
// create a target node, it will be converted to a path node when the file
// is created, and back to a target node when deleted.
//
// Dependencies:
// - fountain.min.js must be loaded before this script
// - nodes.js must be loaded for the node API
// - images.js and videos.js for media display
// - build.js for build menus
// - overlay.js for status overlays

(function() {
    // Container for the screenplay tab
    let container = null;
    // Store current shots data for editing operations
    let currentShots = [];
    // Track paths we've registered for this view
    let registeredPaths = new Set();

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

        const updatedShots = currentShots.map((s, i) => {
            if (i === shotIndex) {
                return { ...s, text: newText };
            }
            return s;
        });

        contentDiv.innerHTML = '<div class="status-spinner"></div>';

        saveScreenplay(updatedShots, 'edit shot_id=' + shot.shotId)
            .then(() => {
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

    function mergeShots(firstIndex, secondIndex) {
        const firstShot = currentShots[firstIndex];
        const secondShot = currentShots[secondIndex];
        if (!firstShot || !secondShot) return;

        const mergedText = firstShot.text + '\n' + secondShot.text;

        const updatedShots = [];
        for (let i = 0; i < currentShots.length; i++) {
            if (i === firstIndex) {
                updatedShots.push({ ...firstShot, text: mergedText });
            } else if (i === secondIndex) {
                continue;
            } else {
                const s = currentShots[i];
                if (s.referenceShot === secondShot.shotId) {
                    updatedShots.push({ ...s, referenceShot: firstShot.shotId });
                } else {
                    updatedShots.push(s);
                }
            }
        }

        saveScreenplay(updatedShots, 'merged shot_id=' + secondShot.shotId + ' into shot_id=' + firstShot.shotId)
            .catch(error => {
                console.error('Error merging shots:', error);
                alert('Failed to merge: ' + error.message);
            });
    }

    function addShotAbove(shotIndex) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        const existingIds = new Set(currentShots.map(s => s.shotId));
        const newShotId = generateNewShotId(shot.shotId, 'above', existingIds);

        const newShot = {
            shotId: newShotId,
            referenceShot: shot.referenceShot,
            text: '',
            isNew: true
        };

        const tempShots = [...currentShots];
        tempShots.splice(shotIndex, 0, newShot);
        tempShots[shotIndex + 1] = { ...tempShots[shotIndex + 1], referenceShot: newShotId };

        renderShotsWithNewShot(tempShots, shotIndex, newShotId);
    }

    function addShotBelow(shotIndex) {
        const shot = currentShots[shotIndex];
        if (!shot) return;

        const existingIds = new Set(currentShots.map(s => s.shotId));
        const newShotId = generateNewShotId(shot.shotId, 'below', existingIds);

        const newShot = {
            shotId: newShotId,
            referenceShot: shot.shotId,
            text: '',
            isNew: true
        };

        const tempShots = [...currentShots];
        tempShots.splice(shotIndex + 1, 0, newShot);

        for (let i = 0; i < tempShots.length; i++) {
            if (i !== shotIndex + 1 && tempShots[i].referenceShot === shot.shotId) {
                tempShots[i] = { ...tempShots[i], referenceShot: newShotId };
            }
        }

        renderShotsWithNewShot(tempShots, shotIndex + 1, newShotId);
    }

    function renderShotsWithNewShot(tempShots, newShotIndex, newShotId) {
        const paperContainer = container.querySelector('.screenplay-paper');
        if (!paperContainer) return;

        clearRegisteredPaths();
        paperContainer.innerHTML = '';

        tempShots.forEach((shot, index) => {
            const shotEl = createShotElement(shot, index, tempShots);
            paperContainer.appendChild(shotEl);

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
            renderScreenplay();
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

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                renderScreenplay();
            }
        });
    }

    function submitNewShot(tempShots, newShotIndex, newShotId, text) {
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
                renderScreenplay();
            });
    }

    function createHoverMenu(shotIndex) {
        const menu = document.createElement('div');
        menu.className = 'shot-hover-menu';

        const editBtn = document.createElement('button');
        editBtn.innerHTML = '✏️';
        editBtn.title = 'Edit shot';
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const shotDiv = menu.closest('.screenplay-shot');
            if (shotDiv) startEditingShot(shotDiv, shotIndex);
        });
        menu.appendChild(editBtn);

        const addAboveBtn = document.createElement('button');
        addAboveBtn.innerHTML = '➕⬆️';
        addAboveBtn.title = 'Add shot above';
        addAboveBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addShotAbove(shotIndex);
        });
        menu.appendChild(addAboveBtn);

        const addBelowBtn = document.createElement('button');
        addBelowBtn.innerHTML = '➕⬇️';
        addBelowBtn.title = 'Add shot below';
        addBelowBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addShotBelow(shotIndex);
        });
        menu.appendChild(addBelowBtn);

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

    function createMergeButton(shotIndex) {
        const btn = document.createElement('button');
        btn.className = 'shot-merge-button';
        btn.innerHTML = '📄📄 → 📄';
        btn.title = 'Merge with next shot';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            mergeShots(shotIndex, shotIndex + 1);
        });
        return btn;
    }

    function createStickyNote(shot) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        sticky.dataset.shotId = shot.shotId;

        const metaGrid = document.createElement('div');
        metaGrid.className = 'sticky-meta-grid';

        metaGrid.appendChild(createMetaRow('SHOT_ID', shot.shotId));
        metaGrid.appendChild(createMetaRow('REFERENCE_SHOT', shot.referenceShot || '—'));

        // Create target rows using the node API
        const shotTypePath = getTargetPath('shot_type', shot.shotId);
        metaGrid.appendChild(createTargetRow('shot_type', shotTypePath));

        const lengthPath = getTargetPath('length_seconds', shot.shotId);
        metaGrid.appendChild(createTargetRow('length_seconds', lengthPath));

        sticky.appendChild(metaGrid);

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
        // Create a container for the row
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

        // Create a node for this target - nodes.js will handle path/target duality
        // Start as target type, will be converted to path when file exists
        const nodeEl = window.createNode(targetPath, {
            type: 'target',
            isLeaf: true,
            order: 0,
            parent: null,
            label: label,
        });

        if (nodeEl) {
            // Hide the node itself - we only want the value display
            nodeEl.style.display = 'none';
            row.appendChild(nodeEl);

            // Update value display based on current state
            if (window.isFilePath(targetPath)) {
                const content = nodeEl.dataset.content;
                valueSpan.textContent = content ? content.trim() : '—';
            } else {
                valueSpan.textContent = '—';
            }
        } else {
            // Node already exists (as a path), get its content
            const existingNode = window.getNode(targetPath);
            if (existingNode) {
                const content = existingNode.dataset.content;
                valueSpan.textContent = content ? content.trim() : '—';
            } else {
                valueSpan.textContent = '—';
            }
        }

        registeredPaths.add(targetPath);

        return row;
    }

    function createMediaNode(targetPath, filename, mimeType) {
        // Create a wrapper for the media node
        const wrapper = document.createElement('div');
        wrapper.className = 'sticky-media-wrapper';

        // Use the nodes.js API to create a node
        // Start as target, nodes.js will convert to path when file exists
        const nodeEl = window.createNode(targetPath, {
            type: 'target',
            mimeType: mimeType,
            isLeaf: true,
            order: 0,
            parent: wrapper,
            label: filename,
        });

        if (nodeEl) {
            // Add expanded class so content is visible
            nodeEl.classList.add('expanded');

            // Register media container for updates
            const isImage = mimeType.startsWith('image/');
            const mediaContainer = nodeEl.querySelector(isImage ? '.image-container' : '.video-container');

            if (mediaContainer) {
                if (isImage && window.registerImageContainer) {
                    window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                    // Load image if file exists
                    if (window.isFilePath(targetPath) && window.fetchImage) {
                        window.fetchImage(targetPath, false).catch(() => {});
                    }
                } else if (!isImage && window.registerVideoContainer) {
                    window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
                    // Load video if file exists
                    if (window.isFilePath(targetPath) && window.fetchVideo) {
                        window.fetchVideo(targetPath, false).catch(() => {});
                    }
                }
            }
        } else {
            // Node already exists, find it and add to wrapper
            const existingNode = window.getNode(targetPath);
            if (existingNode && existingNode.parentElement) {
                // Clone the display but don't move the original
                const clone = existingNode.cloneNode(true);
                clone.classList.add('expanded');
                wrapper.appendChild(clone);

                // Register clone's media container
                const isImage = mimeType.startsWith('image/');
                const mediaContainer = clone.querySelector(isImage ? '.image-container' : '.video-container');
                if (mediaContainer) {
                    if (isImage && window.registerImageContainer) {
                        window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                        if (window.fetchImage) {
                            window.fetchImage(targetPath, false).catch(() => {});
                        }
                    } else if (!isImage && window.registerVideoContainer) {
                        window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
                        if (window.fetchVideo) {
                            window.fetchVideo(targetPath, false).catch(() => {});
                        }
                    }
                }
            }
        }

        registeredPaths.add(targetPath);

        return wrapper;
    }

    function clearRegisteredPaths() {
        for (const path of registeredPaths) {
            const nodeEl = window.getNode(path);
            if (nodeEl) {
                const imgContainer = nodeEl.querySelector('.image-container');
                const vidContainer = nodeEl.querySelector('.video-container');
                if (imgContainer && window.unregisterImageContainer) {
                    window.unregisterImageContainer(path, imgContainer);
                }
                if (vidContainer && window.unregisterVideoContainer) {
                    window.unregisterVideoContainer(path, vidContainer);
                }
                // Only clear from registry if the node is hidden (screenplay-owned)
                if (nodeEl.style.display === 'none') {
                    window.clearNodeFromRegistry(path);
                }
            }
        }
        registeredPaths.clear();
    }

    function createShotElement(shot, index, shotsArray) {
        const shotDiv = document.createElement('div');
        shotDiv.className = 'screenplay-shot';
        shotDiv.dataset.shotId = shot.shotId;
        shotDiv.dataset.shotIndex = index;

        shotDiv.appendChild(createHoverMenu(index));

        const content = document.createElement('div');
        content.className = 'screenplay-shot-content';
        content.innerHTML = renderFountain(shot.text);

        content.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            startEditingShot(shotDiv, index);
        });

        shotDiv.appendChild(content);

        if (!shot.isNew) {
            shotDiv.appendChild(createStickyNote(shot));
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'screenplay-sticky-note';
            placeholder.innerHTML = '<em>New shot</em>';
            shotDiv.appendChild(placeholder);
        }

        if (index < shotsArray.length - 1 && !shot.isNew) {
            shotDiv.appendChild(createMergeButton(index));
        }

        return shotDiv;
    }

    function renderScreenplay() {
        if (!container) return;

        let paperContainer = container.querySelector('.screenplay-paper');
        if (!paperContainer) {
            paperContainer = document.createElement('div');
            paperContainer.className = 'screenplay-paper';
            container.appendChild(paperContainer);
        }

        clearRegisteredPaths();
        paperContainer.innerHTML = '';

        if (currentShots.length === 0) {
            paperContainer.innerHTML = '<div class="screenplay-empty">No screenplay loaded. Waiting for shooting-script.xml...</div>';
            return;
        }

        currentShots.forEach((shot, index) => {
            paperContainer.appendChild(createShotElement(shot, index, currentShots));
        });
    }

    function handleScreenplayUpdate(content) {
        if (!content) {
            currentShots = [];
        } else {
            currentShots = parseScreenplayXml(content);
        }
        renderScreenplay();
    }

    function handleTargetUpdate(path, metadata) {
        // Update the node if it exists
        if (window.hasNode(path)) {
            window.updateNode(path, {
                status: metadata.status,
                mimeType: metadata['mime-type'],
                content: metadata.content,
            });
        }

        // Update the visible value display for text targets
        const valueSpan = document.querySelector(`.sticky-target-value[data-target-path="${path}"]`);
        if (valueSpan && metadata.content) {
            valueSpan.textContent = metadata.content.trim() || '—';
        }

        // Handle media loading
        const nodeEl = window.getNode(path);
        if (!nodeEl) return;

        const mimeType = nodeEl.dataset.mimeType || metadata['mime-type'];
        const isImage = mimeType?.startsWith('image/');
        const isVideo = mimeType?.startsWith('video/');
        const status = metadata.status;

        if (status === 'fresh' || status === 'stale') {
            if (isImage && window.fetchImage) {
                window.fetchImage(path, status === 'fresh').catch(() => {});
            } else if (isVideo && window.fetchVideo) {
                window.fetchVideo(path, status === 'fresh').catch(() => {});
            }
        } else if (status === 'deleted') {
            if (isImage && window.clearImageFromContainers) {
                window.clearImageFromContainers(path);
            } else if (isVideo && window.clearVideoFromContainers) {
                window.clearVideoFromContainers(path);
            }
        }
    }

    function isScreenplayTargetPath(path) {
        const match = path.match(/^shots\/([^/]+)\//);
        if (!match) return false;
        const shotId = match[1];
        return Object.values(SHOT_TARGETS).some(pattern =>
            path === pattern.replace('$SHOT_ID', shotId)
        );
    }

    function init(tabContainer) {
        container = document.createElement('div');
        container.className = 'screenplay-container';
        tabContainer.appendChild(container);

        // Register SSE handler for file updates
        window.registerPathHandler(function(path, metadata) {
            if (path === 'shooting-script.xml') {
                handleScreenplayUpdate(metadata.content);
                return;
            }

            if (isScreenplayTargetPath(path) && registeredPaths.has(path)) {
                handleTargetUpdate(path, metadata);
            }
        });

        // Initial render with empty state
        renderScreenplay();
    }

    // Register as a tab
    window.registerTab({
        id: 'screenplay',
        label: 'Screenplay',
        pane: 'main',
        render: init
    });
})();
