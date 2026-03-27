// screenplay.js
//
// This component provides a custom tab view for screenplay projects.
// It renders 'shooting-script.xml' as a paper-like view with beats
// formatted as Fountain text, and sticky notes showing related targets.
//
// This is a standalone tab component that:
// 1. Registers a "Screenplay" tab in the main pane
// 2. Connects to /monitor_files SSE to get shooting-script.xml content
// 3. Parses the XML to extract <beat> elements
// 4. Renders each beat as Fountain HTML on a "paper" background
// 5. Creates sticky notes with beat metadata and related targets
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
    // Store current beats data for editing operations
    let currentBeats = [];
    // Track paths we've registered for this view
    let registeredPaths = new Set();

    // Target patterns for each beat
    const BEAT_TARGETS = {
        beat_type: 'beats/$BEAT_ID/beat_type',
        length_seconds: 'beats/$BEAT_ID/length_seconds',
        startframe: 'beats/$BEAT_ID/beat_type=standard/startframe.png',
        video: 'beats/$BEAT_ID/raw.mp4'
    };

    function getTargetPath(key, beat_id) {
        return BEAT_TARGETS[key].replace('$BEAT_ID', beat_id);
    }

    function parseScreenplayXml(xmlContent) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(xmlContent, 'text/xml');
        const beats = [];
        doc.querySelectorAll('beat').forEach(el => {
            const beat_id = el.getAttribute('beat_id');
            const continues_from_beat_id = el.getAttribute('continues_from_beat_id') || '';
            const text = el.textContent || '';
            if (beat_id) beats.push({ beat_id, continues_from_beat_id, text });
        });
        return beats;
    }

    function reconstructXml(beats) {
        let xml = '<shooting-script>\n';
        beats.forEach(beat => {
            const refAttr = beat.continues_from_beat_id ? ` continues_from_beat_id="${escapeXmlAttr(beat.continues_from_beat_id)}"` : '';
            xml += `<beat beat_id="${escapeXmlAttr(beat.beat_id)}"${refAttr}>${escapeXmlText(beat.text)}</beat>\n`;
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

    function generateNewBeatId(baseBeatId, direction, existingIds) {
        const suffix = direction === 'above' ? '-' : '+';
        let counter = 1;
        let newId = baseBeatId + suffix + counter;
        while (existingIds.has(newId)) {
            counter++;
            newId = baseBeatId + suffix + counter;
        }
        return newId;
    }

    function saveScreenplay(beats, message) {
        const xmlContent = reconstructXml(beats);
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

    function startEditingBeat(beatDiv, beatIndex) {
        const contentDiv = beatDiv.querySelector('.screenplay-beat-content');
        if (!contentDiv || contentDiv.classList.contains('editing')) return;

        const beat = currentBeats[beatIndex];
        if (!beat) return;

        beatDiv.classList.add('editing');
        contentDiv.classList.add('editing');
        const originalHtml = contentDiv.innerHTML;

        const textarea = document.createElement('textarea');
        textarea.className = 'beat-edit-textarea';
        textarea.value = beat.text;

        const actions = document.createElement('div');
        actions.className = 'beat-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'beat-edit-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            cancelEditing(beatDiv, contentDiv, originalHtml);
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'beat-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitBeatEdit(beatDiv, contentDiv, beatIndex, textarea.value, originalHtml);
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
                cancelEditing(beatDiv, contentDiv, originalHtml);
            }
        });
    }

    function cancelEditing(beatDiv, contentDiv, originalHtml) {
        beatDiv.classList.remove('editing');
        contentDiv.classList.remove('editing');
        contentDiv.innerHTML = originalHtml;
    }

    function submitBeatEdit(beatDiv, contentDiv, beatIndex, newText, originalHtml) {
        const beat = currentBeats[beatIndex];
        if (!beat) return;

        const updatedBeats = currentBeats.map((s, i) => {
            if (i === beatIndex) {
                return { ...s, text: newText };
            }
            return s;
        });

        contentDiv.innerHTML = '<div class="status-spinner"></div>';

        saveScreenplay(updatedBeats, 'edit beat_id=' + beat.beat_id)
            .then(() => {
                beatDiv.classList.remove('editing');
                contentDiv.classList.remove('editing');
            })
            .catch(error => {
                console.error('Error saving beat edit:', error);
                alert('Failed to save: ' + error.message);
                cancelEditing(beatDiv, contentDiv, originalHtml);
            });
    }

    function deleteBeat(beatIndex) {
        const beat = currentBeats[beatIndex];
        if (!beat) return;

        if (!confirm('Are you sure you want to delete beat "' + beat.beat_id + '"?')) return;

        const deletedRefBeat = beat.continues_from_beat_id;
        const updatedBeats = currentBeats
            .filter((s, i) => i !== beatIndex)
            .map(s => {
                if (s.continues_from_beat_id === beat.beat_id) {
                    return { ...s, continues_from_beat_id: deletedRefBeat };
                }
                return s;
            });

        saveScreenplay(updatedBeats, 'deleted beat_id=' + beat.beat_id)
            .catch(error => {
                console.error('Error deleting beat:', error);
                alert('Failed to delete: ' + error.message);
            });
    }

    function mergeBeats(firstIndex, secondIndex) {
        const firstBeat = currentBeats[firstIndex];
        const secondBeat = currentBeats[secondIndex];
        if (!firstBeat || !secondBeat) return;

        const mergedText = firstBeat.text + '\n' + secondBeat.text;

        const updatedBeats = [];
        for (let i = 0; i < currentBeats.length; i++) {
            if (i === firstIndex) {
                updatedBeats.push({ ...firstBeat, text: mergedText });
            } else if (i === secondIndex) {
                continue;
            } else {
                const s = currentBeats[i];
                if (s.continues_from_beat_id === secondBeat.beat_id) {
                    updatedBeats.push({ ...s, continues_from_beat_id: firstBeat.beat_id });
                } else {
                    updatedBeats.push(s);
                }
            }
        }

        saveScreenplay(updatedBeats, 'merged beat_id=' + secondBeat.beat_id + ' into beat_id=' + firstBeat.beat_id)
            .catch(error => {
                console.error('Error merging beats:', error);
                alert('Failed to merge: ' + error.message);
            });
    }

    function addBeatAbove(beatIndex) {
        const beat = currentBeats[beatIndex];
        if (!beat) return;

        const existingIds = new Set(currentBeats.map(s => s.beat_id));
        const newBeatId = generateNewBeatId(beat.beat_id, 'above', existingIds);

        const newBeat = {
            beat_id: newBeatId,
            continues_from_beat_id: beat.continues_from_beat_id,
            text: '',
            isNew: true
        };

        const tempBeats = [...currentBeats];
        tempBeats.splice(beatIndex, 0, newBeat);
        tempBeats[beatIndex + 1] = { ...tempBeats[beatIndex + 1], continues_from_beat_id: newBeatId };

        renderBeatsWithNewBeat(tempBeats, beatIndex, newBeatId);
    }

    function addBeatBelow(beatIndex) {
        const beat = currentBeats[beatIndex];
        if (!beat) return;

        const existingIds = new Set(currentBeats.map(s => s.beat_id));
        const newBeatId = generateNewBeatId(beat.beat_id, 'below', existingIds);

        const newBeat = {
            beat_id: newBeatId,
            continues_from_beat_id: beat.beat_id,
            text: '',
            isNew: true
        };

        const tempBeats = [...currentBeats];
        tempBeats.splice(beatIndex + 1, 0, newBeat);

        for (let i = 0; i < tempBeats.length; i++) {
            if (i !== beatIndex + 1 && tempBeats[i].continues_from_beat_id === beat.beat_id) {
                tempBeats[i] = { ...tempBeats[i], continues_from_beat_id: newBeatId };
            }
        }

        renderBeatsWithNewBeat(tempBeats, beatIndex + 1, newBeatId);
    }

    function renderBeatsWithNewBeat(tempBeats, newBeatIndex, newBeatId) {
        const paperContainer = container.querySelector('.screenplay-paper');
        if (!paperContainer) return;

        clearRegisteredPaths();
        paperContainer.innerHTML = '';

        tempBeats.forEach((beat, index) => {
            const beatEl = createBeatElement(beat, index, tempBeats);
            paperContainer.appendChild(beatEl);

            if (index === newBeatIndex && beat.isNew) {
                beatEl.classList.add('new-beat');
                startEditingNewBeat(beatEl, tempBeats, newBeatIndex, newBeatId);
            }
        });
    }

    function startEditingNewBeat(beatDiv, tempBeats, newBeatIndex, newBeatId) {
        const contentDiv = beatDiv.querySelector('.screenplay-beat-content');
        if (!contentDiv) return;

        beatDiv.classList.add('editing');
        contentDiv.classList.add('editing');

        const textarea = document.createElement('textarea');
        textarea.className = 'beat-edit-textarea';
        textarea.placeholder = 'Enter beat text...';

        const actions = document.createElement('div');
        actions.className = 'beat-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'beat-edit-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            renderScreenplay();
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'beat-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitNewBeat(tempBeats, newBeatIndex, newBeatId, textarea.value);
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

    function submitNewBeat(tempBeats, newBeatIndex, newBeatId, text) {
        const finalBeats = tempBeats.map((s, i) => {
            if (i === newBeatIndex) {
                const { isNew, ...rest } = s;
                return { ...rest, text: text };
            }
            return s;
        });

        saveScreenplay(finalBeats, 'added beat_id=' + newBeatId)
            .catch(error => {
                console.error('Error adding beat:', error);
                alert('Failed to add beat: ' + error.message);
                renderScreenplay();
            });
    }

    function createHoverMenu(beatIndex) {
        const menu = document.createElement('div');
        menu.className = 'beat-hover-menu';

        const editBtn = document.createElement('button');
        editBtn.innerHTML = '✏️';
        editBtn.title = 'Edit beat';
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const beatDiv = menu.closest('.screenplay-beat');
            if (beatDiv) startEditingBeat(beatDiv, beatIndex);
        });
        menu.appendChild(editBtn);

        const addAboveBtn = document.createElement('button');
        addAboveBtn.innerHTML = '➕⬆️';
        addAboveBtn.title = 'Add beat above';
        addAboveBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addBeatAbove(beatIndex);
        });
        menu.appendChild(addAboveBtn);

        const addBelowBtn = document.createElement('button');
        addBelowBtn.innerHTML = '➕⬇️';
        addBelowBtn.title = 'Add beat below';
        addBelowBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            addBeatBelow(beatIndex);
        });
        menu.appendChild(addBelowBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = 'Delete beat';
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteBeat(beatIndex);
        });
        menu.appendChild(deleteBtn);

        return menu;
    }

    function createMergeButton(beatIndex) {
        const btn = document.createElement('button');
        btn.className = 'beat-merge-button';
        btn.innerHTML = '📄📄 → 📄';
        btn.title = 'Merge with next beat';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            mergeBeats(beatIndex, beatIndex + 1);
        });
        return btn;
    }

    function createStickyNote(beat) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        sticky.dataset.beat_id = beat.beat_id;

        const metaGrid = document.createElement('div');
        metaGrid.className = 'sticky-meta-grid';

        metaGrid.appendChild(createMetaRow('BEAT_ID', beat.beat_id));
        metaGrid.appendChild(createMetaRow('CONTINUES_FROM_BEAT_ID', beat.continues_from_beat_id || '—'));

        // Create target rows using the node API
        const beatTypePath = getTargetPath('beat_type', beat.beat_id);
        metaGrid.appendChild(createTargetRow('beat_type', beatTypePath));

        const lengthPath = getTargetPath('length_seconds', beat.beat_id);
        metaGrid.appendChild(createTargetRow('length_seconds', lengthPath));

        sticky.appendChild(metaGrid);

        const mediaSection = document.createElement('div');
        mediaSection.className = 'sticky-media-section';

        const startframePath = getTargetPath('startframe', beat.beat_id);
        mediaSection.appendChild(createMediaNode(startframePath, 'startframe.png', 'image/png'));

        const videoPath = getTargetPath('video', beat.beat_id);
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

    function createBeatElement(beat, index, beatsArray) {
        const beatDiv = document.createElement('div');
        beatDiv.className = 'screenplay-beat';
        beatDiv.dataset.beat_id = beat.beat_id;
        beatDiv.dataset.beatIndex = index;

        beatDiv.appendChild(createHoverMenu(index));

        const content = document.createElement('div');
        content.className = 'screenplay-beat-content';
        content.innerHTML = renderFountain(beat.text);

        content.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            startEditingBeat(beatDiv, index);
        });

        beatDiv.appendChild(content);

        if (!beat.isNew) {
            beatDiv.appendChild(createStickyNote(beat));
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'screenplay-sticky-note';
            placeholder.innerHTML = '<em>New beat</em>';
            beatDiv.appendChild(placeholder);
        }

        if (index < beatsArray.length - 1 && !beat.isNew) {
            beatDiv.appendChild(createMergeButton(index));
        }

        return beatDiv;
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

        if (currentBeats.length === 0) {
            paperContainer.innerHTML = '<div class="screenplay-empty">No screenplay loaded. Waiting for shooting-script.xml...</div>';
            return;
        }

        currentBeats.forEach((beat, index) => {
            paperContainer.appendChild(createBeatElement(beat, index, currentBeats));
        });
    }

    function handleScreenplayUpdate(content) {
        if (!content) {
            currentBeats = [];
        } else {
            currentBeats = parseScreenplayXml(content);
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
        const match = path.match(/^beats\/([^/]+)\//);
        if (!match) return false;
        const beat_id = match[1];
        return Object.values(BEAT_TARGETS).some(pattern =>
            path === pattern.replace('$BEAT_ID', beat_id)
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
