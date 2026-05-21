// storyboard.js
//
// Horizontal storyboard view of shooting-script.xml. Each beat occupies a
// fixed-width column, with the fountain script at the top and a colored
// sticky note below. Adjacent beats whose continues_from_beat_id chains
// share a single "paper" (white card) with a dotted divider; otherwise
// the paper edge shows.
//
// Sticky notes are color-coded per connected-component "island" in the
// beat DAG (continues_from_beat_id and includes_beat_id). Non-adjacent
// continues_from references draw taxicab-routed arrows underneath the
// sticky notes; their depth is staggered to make overlapping arrows easy
// to follow, and they share the island color.
//
// All XML parsing, save/load, beat mutation, and island computation lives
// in screenplay_common.js so this tab and screenplay.js stay in sync.

(function() {
    const C = window.ScreenplayCommon;

    // Tuning knobs for arrow routing -- kept all in one place so they're
    // easy to tweak when arrows render poorly in a given project.
    const ARROW_BASE_OFFSET    = 30;  // px below sticky bottom for the first arrow lane
    const ARROW_LANE_HEIGHT    = 14;  // px between successive arrow lanes
    const ARROW_HORIZONTAL_PAD = 12;  // px the arrow extends past the sticky edge before going down
    const ARROW_HEAD_SIZE      = 6;   // arrow-head leg length

    let container = null;
    let board = null;
    let arrowLayer = null;
    let currentBeats = [];
    let registeredPaths = new Set();

    const BEAT_TARGETS = {
        beat_type: 'beats/$BEAT_ID/beat_type',
        length_seconds: 'beats/$BEAT_ID/length_seconds',
        startframe: 'beats/$BEAT_ID/beat_type=standard/startframe.png',
        video: 'beats/$BEAT_ID/raw.mp4',
    };

    function getTargetPath(key, beat_id) {
        return BEAT_TARGETS[key].replace('$BEAT_ID', beat_id);
    }

    function isStoryboardTargetPath(path) {
        const match = path.match(/^beats\/([^/]+)\//);
        if (!match) return false;
        const beat_id = match[1];
        return Object.values(BEAT_TARGETS).some(pattern =>
            path === pattern.replace('$BEAT_ID', beat_id)
        );
    }

    // --- Beat editing wrappers ---

    function saveAndCatch(beats, message) {
        return C.saveScreenplay(beats, message).catch(err => {
            console.error('storyboard save failed:', err);
            alert('Save failed: ' + err.message);
        });
    }

    function deleteBeat(idx) {
        const beat = currentBeats[idx];
        if (!beat) return;
        if (!confirm('Delete beat "' + beat.beat_id + '"?')) return;
        const updated = C.deleteBeatFromArray(currentBeats, idx);
        if (updated) saveAndCatch(updated, 'deleted beat_id=' + beat.beat_id);
    }

    function mergeBeats(firstIdx, secondIdx) {
        const first = currentBeats[firstIdx];
        const second = currentBeats[secondIdx];
        const updated = C.mergeBeatsInArray(currentBeats, firstIdx, secondIdx);
        if (updated) saveAndCatch(updated, 'merged beat_id=' + second.beat_id + ' into beat_id=' + first.beat_id);
    }

    function startEditingBeat(beatDiv, idx) {
        const contentDiv = beatDiv.querySelector('.storyboard-beat-content');
        if (!contentDiv || contentDiv.classList.contains('editing')) return;
        const beat = currentBeats[idx];
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
        cancelBtn.addEventListener('click', e => {
            e.stopPropagation();
            beatDiv.classList.remove('editing');
            contentDiv.classList.remove('editing');
            contentDiv.innerHTML = originalHtml;
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'beat-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', e => {
            e.stopPropagation();
            const updated = currentBeats.map((s, i) =>
                i === idx ? { ...s, text: textarea.value } : s
            );
            saveAndCatch(updated, 'edit beat_id=' + beat.beat_id);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        contentDiv.innerHTML = '';
        contentDiv.appendChild(textarea);
        contentDiv.appendChild(actions);
        textarea.focus();

        textarea.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                e.preventDefault();
                beatDiv.classList.remove('editing');
                contentDiv.classList.remove('editing');
                contentDiv.innerHTML = originalHtml;
            }
        });
    }

    function addBeatAbove(idx) {
        const result = C.insertBeatAbove(currentBeats, idx);
        if (!result) return;
        renderTemp(result.beats, result.newIndex, result.newBeatId);
    }

    function addBeatBelow(idx) {
        const result = C.insertBeatBelow(currentBeats, idx);
        if (!result) return;
        renderTemp(result.beats, result.newIndex, result.newBeatId);
    }

    function renderTemp(tempBeats, newIdx, newBeatId) {
        renderBoard(tempBeats);
        const beatEls = board.querySelectorAll('.storyboard-beat');
        const beatEl = beatEls[newIdx];
        if (!beatEl) return;
        beatEl.classList.add('new-beat');
        startEditingNewBeat(beatEl, tempBeats, newIdx, newBeatId);
    }

    function startEditingNewBeat(beatDiv, tempBeats, newIdx, newBeatId) {
        const contentDiv = beatDiv.querySelector('.storyboard-beat-content');
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
        cancelBtn.addEventListener('click', e => {
            e.stopPropagation();
            renderBoard(currentBeats);
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'beat-edit-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', e => {
            e.stopPropagation();
            const finalBeats = tempBeats.map((s, i) => {
                if (i === newIdx) {
                    const { isNew, ...rest } = s;
                    return { ...rest, text: textarea.value };
                }
                return s;
            });
            saveAndCatch(finalBeats, 'added beat_id=' + newBeatId);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        contentDiv.innerHTML = '';
        contentDiv.appendChild(textarea);
        contentDiv.appendChild(actions);
        textarea.focus();
    }

    // --- Rendering ---

    function createHoverMenu(idx) {
        const menu = document.createElement('div');
        menu.className = 'storyboard-beat-hover-menu';
        const buttons = [
            ['✏️', 'Edit beat', () => {
                const beatDiv = menu.closest('.storyboard-beat');
                if (beatDiv) startEditingBeat(beatDiv, idx);
            }],
            ['➕⬅️', 'Add beat before', () => addBeatAbove(idx)],
            ['➕➡️', 'Add beat after',  () => addBeatBelow(idx)],
            ['🗑️', 'Delete beat',      () => deleteBeat(idx)],
        ];
        buttons.forEach(([icon, title, fn]) => {
            const b = document.createElement('button');
            b.innerHTML = icon;
            b.title = title;
            b.addEventListener('click', e => { e.stopPropagation(); fn(); });
            menu.appendChild(b);
        });
        return menu;
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

    function createMediaNode(targetPath, filename, mimeType) {
        const wrapper = document.createElement('div');
        wrapper.className = 'sticky-media-wrapper';
        const nodeEl = window.createNode(targetPath, {
            type: 'target', mimeType, isLeaf: true, order: 0,
            parent: wrapper, label: filename,
        });
        if (nodeEl) {
            nodeEl.classList.add('expanded');
            const isImage = mimeType.startsWith('image/');
            const mediaContainer = nodeEl.querySelector(isImage ? '.image-container' : '.video-container');
            if (mediaContainer) {
                if (isImage && window.registerImageContainer) {
                    window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                    if (window.isFilePath(targetPath) && window.fetchImage) {
                        window.fetchImage(targetPath, false).catch(() => {});
                    }
                } else if (!isImage && window.registerVideoContainer) {
                    window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
                    if (window.isFilePath(targetPath) && window.fetchVideo) {
                        window.fetchVideo(targetPath, false).catch(() => {});
                    }
                }
            }
        }
        registeredPaths.add(targetPath);
        return wrapper;
    }

    function createStickyNote(beat, color) {
        const sticky = document.createElement('div');
        sticky.className = 'storyboard-sticky-note';
        sticky.style.background = color;
        sticky.dataset.beat_id = beat.beat_id;

        const grid = document.createElement('div');
        grid.className = 'sticky-meta-grid';
        grid.appendChild(createMetaRow('BEAT_ID', beat.beat_id));
        grid.appendChild(createMetaRow('CONTINUES_FROM', beat.continues_from_beat_id || '—'));
        if (beat.includes_beat_id) {
            grid.appendChild(createMetaRow('INCLUDES', beat.includes_beat_id));
        }
        grid.appendChild(createTargetRow('beat_type', getTargetPath('beat_type', beat.beat_id)));
        grid.appendChild(createTargetRow('length_seconds', getTargetPath('length_seconds', beat.beat_id)));
        sticky.appendChild(grid);

        const media = document.createElement('div');
        media.className = 'sticky-media-section';
        media.appendChild(createMediaNode(getTargetPath('startframe', beat.beat_id), 'startframe.png', 'image/png'));
        media.appendChild(createMediaNode(getTargetPath('video', beat.beat_id), 'raw.mp4', 'video/mp4'));
        sticky.appendChild(media);

        return sticky;
    }

    function createBeatColumn(beat, idx, color, isFirstInPaper) {
        const col = document.createElement('div');
        col.className = 'storyboard-beat';
        col.dataset.beat_id = beat.beat_id;
        col.dataset.beatIndex = idx;

        col.appendChild(createHoverMenu(idx));

        if (!isFirstInPaper) {
            // Merge with previous beat (which is in the same paper).
            const mergeBtn = document.createElement('button');
            mergeBtn.className = 'storyboard-merge-button';
            mergeBtn.innerHTML = '📄📄→📄';
            mergeBtn.title = 'Merge with previous beat';
            mergeBtn.addEventListener('click', e => {
                e.stopPropagation();
                mergeBeats(idx - 1, idx);
            });
            col.appendChild(mergeBtn);
        }

        const content = document.createElement('div');
        content.className = 'storyboard-beat-content';
        content.innerHTML = C.renderFountain(beat.text);
        content.addEventListener('dblclick', e => {
            e.stopPropagation();
            startEditingBeat(col, idx);
        });
        col.appendChild(content);

        col.appendChild(createStickyNote(beat, color));
        return col;
    }

    // Draw taxicab-routed arrows for continues_from references that skip
    // over at least one beat (non-adjacent). Arrows leave the south of
    // the source sticky note and arrive at the south of the target.
    function drawArrows(beats, colorOf) {
        if (!arrowLayer) return;
        while (arrowLayer.firstChild) arrowLayer.removeChild(arrowLayer.firstChild);

        const beatEls = board.querySelectorAll('.storyboard-beat');
        const boardRect = board.getBoundingClientRect();

        // Determine south-edge anchor (in board coords) for each beat idx.
        const anchors = [];
        beatEls.forEach((el, i) => {
            const sticky = el.querySelector('.storyboard-sticky-note');
            if (!sticky) { anchors.push(null); return; }
            const r = sticky.getBoundingClientRect();
            anchors.push({
                x: (r.left + r.right) / 2 - boardRect.left,
                y: r.bottom - boardRect.top,
                left:  r.left  - boardRect.left,
                right: r.right - boardRect.left,
            });
        });

        // Build list of arrows: { srcIdx, dstIdx } where dstIdx < srcIdx.
        const arrows = [];
        beats.forEach((b, i) => {
            if (!b.continues_from_beat_id) return;
            const dst = beats.findIndex(x => x.beat_id === b.continues_from_beat_id);
            if (dst < 0) return;
            if (Math.abs(i - dst) <= 1) return; // adjacent: handled by paper grouping
            arrows.push({ srcIdx: i, dstIdx: dst });
        });

        // Assign each arrow a "lane" depth. Two arrows that horizontally
        // overlap must use distinct lanes. Greedy first-fit by span length.
        arrows.sort((a, b) =>
            Math.abs(a.srcIdx - a.dstIdx) - Math.abs(b.srcIdx - b.dstIdx)
        );
        const laneRanges = []; // laneRanges[lane] = [{lo, hi}, ...]
        arrows.forEach(a => {
            const lo = Math.min(a.srcIdx, a.dstIdx);
            const hi = Math.max(a.srcIdx, a.dstIdx);
            let lane = 0;
            while (true) {
                const occ = laneRanges[lane] || [];
                if (!occ.some(r => !(hi < r.lo || lo > r.hi))) {
                    if (!laneRanges[lane]) laneRanges[lane] = [];
                    laneRanges[lane].push({ lo, hi });
                    a.lane = lane;
                    break;
                }
                lane++;
            }
        });

        const svgNS = 'http://www.w3.org/2000/svg';
        arrows.forEach(a => {
            const src = anchors[a.srcIdx];
            const dst = anchors[a.dstIdx];
            if (!src || !dst) return;
            const color = colorOf.get(beats[a.srcIdx].beat_id) || '#444';
            const depth = ARROW_BASE_OFFSET + a.lane * ARROW_LANE_HEIGHT;

            // Path: south of src -> down -> left to dst column -> up to south of dst.
            const sx = src.x;
            const sy = src.y;
            const dx = dst.x;
            const dy = dst.y;
            const laneY = Math.max(sy, dy) + depth;

            // Step out a bit beyond the sticky right edge for clarity,
            // then go down/left/up.
            const sxOut = sx; // straight down from south edge center
            const dxIn  = dx;

            const d = [
                `M ${sxOut} ${sy}`,
                `L ${sxOut} ${laneY}`,
                `L ${dxIn}  ${laneY}`,
                `L ${dxIn}  ${dy}`,
            ].join(' ');

            const path = document.createElementNS(svgNS, 'path');
            path.setAttribute('d', d);
            path.setAttribute('stroke', color);
            arrowLayer.appendChild(path);

            // Simple arrowhead at destination (pointing up into south).
            const head = document.createElementNS(svgNS, 'path');
            const h = ARROW_HEAD_SIZE;
            head.setAttribute('d',
                `M ${dxIn - h} ${dy + h} L ${dxIn} ${dy} L ${dxIn + h} ${dy + h}`);
            head.setAttribute('stroke', color);
            arrowLayer.appendChild(head);
        });
    }

    function clearRegisteredPaths() {
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

    function renderBoard(beats) {
        if (!container) return;
        clearRegisteredPaths();
        while (board.firstChild) board.removeChild(board.firstChild);

        if (beats.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'storyboard-empty';
            empty.textContent = 'No screenplay loaded. Waiting for shooting-script.xml...';
            board.appendChild(empty);
            return;
        }

        const islands = C.computeIslands(beats);
        const groups = C.computePaperGroups(beats);

        const rows = document.createElement('div');
        rows.className = 'storyboard-rows';
        board.appendChild(rows);

        groups.forEach(group => {
            const paper = document.createElement('div');
            paper.className = 'storyboard-paper';
            for (let i = group.start; i <= group.end; i++) {
                const beat = beats[i];
                const color = islands.colorOf.get(beat.beat_id) || C.ISLAND_COLORS[0];
                paper.appendChild(createBeatColumn(beat, i, color, i === group.start));
            }
            rows.appendChild(paper);
        });

        arrowLayer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        arrowLayer.setAttribute('class', 'storyboard-arrow-layer');
        board.appendChild(arrowLayer);

        // Defer arrow drawing until layout is settled.
        requestAnimationFrame(() => drawArrows(beats, islands.colorOf));
    }

    function handleScreenplayUpdate(content) {
        currentBeats = content ? C.parseScreenplayXml(content) : [];
        renderBoard(currentBeats);
    }

    function handleTargetUpdate(path, metadata) {
        if (window.hasNode(path)) {
            window.updateNode(path, {
                status: metadata.status,
                mimeType: metadata['mime-type'],
                content: metadata.content,
            });
        }
        const valueSpan = document.querySelector(
            `.sticky-target-value[data-target-path="${path}"]`);
        if (valueSpan && metadata.content) {
            valueSpan.textContent = metadata.content.trim() || '—';
        }
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

    function init(tabContainer) {
        container = document.createElement('div');
        container.className = 'storyboard-container';
        tabContainer.appendChild(container);

        board = document.createElement('div');
        board.className = 'storyboard-board';
        container.appendChild(board);

        window.registerPathHandler(function(path, metadata) {
            if (path === 'shooting-script.xml') {
                handleScreenplayUpdate(metadata.content);
                return;
            }
            if (isStoryboardTargetPath(path) && registeredPaths.has(path)) {
                handleTargetUpdate(path, metadata);
            }
        });

        renderBoard(currentBeats);
    }

    window.registerTab({
        id: 'storyboard',
        label: 'Storyboard',
        pane: 'main',
        render: init,
    });
})();
