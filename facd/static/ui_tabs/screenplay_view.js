// screenplay_view.js
//
// Unified beat-board view used by both screenplay.js (vertical) and
// storyboard.js (horizontal). The two views are identical except for
// orientation:
//
//   - vertical:   beats stacked top-to-bottom, sticky note to the
//                 right of the script, arrows leave the RIGHT edge of
//                 the sticky and route through a gutter on the right.
//   - horizontal: beats laid out left-to-right, sticky note below the
//                 script, arrows leave the BOTTOM edge of the sticky
//                 and route through a gutter below.
//
// In both cases, a "paper" groups one or more consecutive beats whose
// continues_from_beat_id chains link them; the boundary between papers
// implies a page break. Non-adjacent continues_from references draw
// taxicab-routed arrows in the gutter, colored to match the island.
//
// All XML parsing, save/load, beat mutation, and island/paper-group
// computation lives in screenplay_common.js. Sticky-note rendering and
// target wiring lives in screenplay_stickynote.js.

(function() {
    const C = window.ScreenplayCommon;
    const SN = window.ScreenplayStickyNote;

    // Arrow routing tuning.
    const ARROW_BASE_OFFSET    = 30;
    const ARROW_LANE_DEPTH     = 14;
    const ARROW_HEAD_SIZE      = 6;

    // Create one view instance. Returns an object with init(tabContainer).
    function createView(orientation) {
        const isHorizontal = (orientation === 'horizontal');

        let container = null;
        let board = null;
        let arrowLayer = null;
        let currentBeats = [];
        const registeredPaths = new Set();

        // --- Save wrappers ---

        function saveAndCatch(beats, message) {
            return C.saveScreenplay(beats, message).catch(err => {
                console.error('screenplay_view save failed:', err);
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
            if (updated) saveAndCatch(updated,
                'merged beat_id=' + second.beat_id + ' into beat_id=' + first.beat_id);
        }

        function startEditingBeat(beatDiv, idx) {
            const contentDiv = beatDiv.querySelector('.screenplay-beat-content');
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
                    i === idx ? { ...s, text: textarea.value } : s);
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
            const r = C.insertBeatAbove(currentBeats, idx);
            if (r) renderTemp(r.beats, r.newIndex, r.newBeatId);
        }
        function addBeatBelow(idx) {
            const r = C.insertBeatBelow(currentBeats, idx);
            if (r) renderTemp(r.beats, r.newIndex, r.newBeatId);
        }

        function renderTemp(tempBeats, newIdx, newBeatId) {
            renderBoard(tempBeats);
            const beatEls = board.querySelectorAll('.screenplay-beat');
            const beatEl = beatEls[newIdx];
            if (!beatEl) return;
            beatEl.classList.add('new-beat');
            startEditingNewBeat(beatEl, tempBeats, newIdx, newBeatId);
        }

        function startEditingNewBeat(beatDiv, tempBeats, newIdx, newBeatId) {
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
            menu.className = 'screenplay-beat-hover-menu';
            const beforeIcon = isHorizontal ? '➕⬅️' : '➕⬆️';
            const afterIcon  = isHorizontal ? '➕➡️' : '➕⬇️';
            const buttons = [
                ['✏️', 'Edit beat', () => {
                    const beatDiv = menu.closest('.screenplay-beat');
                    if (beatDiv) startEditingBeat(beatDiv, idx);
                }],
                [beforeIcon, 'Add beat before', () => addBeatAbove(idx)],
                [afterIcon,  'Add beat after',  () => addBeatBelow(idx)],
                ['🗑️', 'Delete beat',           () => deleteBeat(idx)],
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

        function createBeatElement(beat, idx, color, isFirstInPaper) {
            const beatDiv = document.createElement('div');
            beatDiv.className = 'screenplay-beat';
            beatDiv.dataset.beat_id = beat.beat_id;
            beatDiv.dataset.beatIndex = idx;
            if (beat.isNew) beatDiv.classList.add('new-beat');

            beatDiv.appendChild(createHoverMenu(idx));

            if (!isFirstInPaper) {
                const mergeBtn = document.createElement('button');
                mergeBtn.className = 'screenplay-merge-button';
                mergeBtn.innerHTML = '📄📄→📄';
                mergeBtn.title = 'Merge with previous beat';
                mergeBtn.addEventListener('click', e => {
                    e.stopPropagation();
                    mergeBeats(idx - 1, idx);
                });
                beatDiv.appendChild(mergeBtn);
            }

            const content = document.createElement('div');
            content.className = 'screenplay-beat-content';
            content.innerHTML = C.renderFountain(beat.text);
            content.addEventListener('dblclick', e => {
                e.stopPropagation();
                startEditingBeat(beatDiv, idx);
            });
            beatDiv.appendChild(content);

            if (!beat.isNew) {
                beatDiv.appendChild(SN.createStickyNote(beat, color, registeredPaths));
            } else {
                const placeholder = document.createElement('div');
                placeholder.className = 'screenplay-sticky-note';
                if (color) placeholder.style.background = color;
                placeholder.innerHTML = '<em>New beat</em>';
                beatDiv.appendChild(placeholder);
            }

            return beatDiv;
        }

        // Draw arrows in the gutter for non-adjacent continues_from refs.
        // Anchor edge depends on orientation: right edge for vertical,
        // bottom edge for horizontal.
        function drawArrows(beats, colorOf) {
            if (!arrowLayer) return;
            while (arrowLayer.firstChild) arrowLayer.removeChild(arrowLayer.firstChild);

            const beatEls = board.querySelectorAll('.screenplay-beat');
            const boardRect = board.getBoundingClientRect();

            // Per-beat anchor point (in board coords) at the "exit" edge.
            const anchors = [];
            beatEls.forEach(el => {
                const sticky = el.querySelector('.screenplay-sticky-note');
                if (!sticky) { anchors.push(null); return; }
                const r = sticky.getBoundingClientRect();
                if (isHorizontal) {
                    // bottom edge, centered horizontally
                    anchors.push({
                        primary: (r.left + r.right) / 2 - boardRect.left, // x
                        cross:   r.bottom - boardRect.top,                 // y
                    });
                } else {
                    // right edge, centered vertically
                    anchors.push({
                        primary: (r.top + r.bottom) / 2 - boardRect.top,   // y
                        cross:   r.right - boardRect.left,                  // x
                    });
                }
            });

            const arrows = [];
            beats.forEach((b, i) => {
                if (!b.continues_from_beat_id) return;
                const dst = beats.findIndex(x => x.beat_id === b.continues_from_beat_id);
                if (dst < 0) return;
                if (Math.abs(i - dst) <= 1) return;
                arrows.push({ srcIdx: i, dstIdx: dst });
            });

            // Lane assignment along the primary axis.
            arrows.sort((a, b) =>
                Math.abs(a.srcIdx - a.dstIdx) - Math.abs(b.srcIdx - b.dstIdx));
            const laneRanges = [];
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
                const laneCross = Math.max(src.cross, dst.cross)
                    + ARROW_BASE_OFFSET + a.lane * ARROW_LANE_DEPTH;
                const h = ARROW_HEAD_SIZE;

                let d, headD;
                if (isHorizontal) {
                    // primary=x, cross=y. Path: down, across, up.
                    d = `M ${src.primary} ${src.cross} ` +
                        `L ${src.primary} ${laneCross} ` +
                        `L ${dst.primary} ${laneCross} ` +
                        `L ${dst.primary} ${dst.cross}`;
                    headD = `M ${dst.primary - h} ${dst.cross + h} ` +
                            `L ${dst.primary} ${dst.cross} ` +
                            `L ${dst.primary + h} ${dst.cross + h}`;
                } else {
                    // primary=y, cross=x. Path: right, down/up, left.
                    d = `M ${src.cross} ${src.primary} ` +
                        `L ${laneCross} ${src.primary} ` +
                        `L ${laneCross} ${dst.primary} ` +
                        `L ${dst.cross} ${dst.primary}`;
                    headD = `M ${dst.cross + h} ${dst.primary - h} ` +
                            `L ${dst.cross} ${dst.primary} ` +
                            `L ${dst.cross + h} ${dst.primary + h}`;
                }

                const path = document.createElementNS(svgNS, 'path');
                path.setAttribute('d', d);
                path.setAttribute('stroke', color);
                arrowLayer.appendChild(path);

                const head = document.createElementNS(svgNS, 'path');
                head.setAttribute('d', headD);
                head.setAttribute('stroke', color);
                arrowLayer.appendChild(head);
            });
        }

        function renderBoard(beats) {
            if (!container) return;
            SN.clearRegisteredPaths(registeredPaths);
            while (board.firstChild) board.removeChild(board.firstChild);

            if (beats.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'screenplay-empty';
                empty.textContent = 'No screenplay loaded. Waiting for shooting-script.xml...';
                board.appendChild(empty);
                return;
            }

            const islands = C.computeIslands(beats);
            const groups = C.computePaperGroups(beats);

            const rows = document.createElement('div');
            rows.className = 'screenplay-rows';
            board.appendChild(rows);

            groups.forEach(group => {
                const paper = document.createElement('div');
                paper.className = 'screenplay-paper';
                for (let i = group.start; i <= group.end; i++) {
                    const beat = beats[i];
                    const color = islands.colorOf.get(beat.beat_id) || C.ISLAND_COLORS[0];
                    paper.appendChild(
                        createBeatElement(beat, i, color, i === group.start));
                }
                rows.appendChild(paper);
            });

            arrowLayer = document.createElementNS(
                'http://www.w3.org/2000/svg', 'svg');
            arrowLayer.setAttribute('class', 'screenplay-arrow-layer');
            board.appendChild(arrowLayer);

            requestAnimationFrame(() => drawArrows(beats, islands.colorOf));
        }

        function handleScreenplayUpdate(content) {
            currentBeats = content ? C.parseScreenplayXml(content) : [];
            renderBoard(currentBeats);
        }

        function init(tabContainer) {
            container = document.createElement('div');
            container.className = 'screenplay-container';
            container.dataset.orientation = orientation;
            tabContainer.appendChild(container);

            board = document.createElement('div');
            board.className = 'screenplay-board';
            container.appendChild(board);

            window.registerPathHandler(function(path, metadata) {
                if (path === 'shooting-script.xml') {
                    handleScreenplayUpdate(metadata.content);
                    return;
                }
                if (SN.isBeatTargetPath(path) && registeredPaths.has(path)) {
                    SN.handleTargetUpdate(path, metadata);
                }
            });

            renderBoard(currentBeats);
        }

        return { init };
    }

    window.ScreenplayView = { createView };
})();
