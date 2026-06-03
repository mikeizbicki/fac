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
        let lastIslands = null;
        const registeredPaths = new Set();
        let savingOverlay = null;
        let savingTimeout = null;
        // Per-paper fold state. Keys are the first beat_id of each
        // paper (which is stable across edits within an island).
        //   foldStates: paperKey -> 'max' | 'partial' | 'full'
        //   frontBeats: paperKey -> beat_id of the beat currently
        //               kept visible in partial mode.
        const foldStates = new Map();
        const frontBeats = new Map();

        function showSavingOverlay(message) {
            if (!container) return;
            if (!savingOverlay) {
                savingOverlay = document.createElement('div');
                savingOverlay.className = 'screenplay-saving-overlay';
                const spinner = document.createElement('div');
                spinner.className = 'screenplay-saving-spinner';
                const msg = document.createElement('div');
                msg.className = 'screenplay-saving-message';
                msg.textContent = message || 'Saving...';
                savingOverlay.appendChild(spinner);
                savingOverlay.appendChild(msg);
                container.appendChild(savingOverlay);
            }
        }

        function hideSavingOverlay() {
            if (savingOverlay && savingOverlay.parentElement) {
                savingOverlay.parentElement.removeChild(savingOverlay);
            }
            savingOverlay = null;
            if (savingTimeout) { clearTimeout(savingTimeout); savingTimeout = null; }
        }

        // --- Save wrappers ---

        function saveAndCatch(beats, message) {
            showSavingOverlay(message ? ('Saving: ' + message) : 'Saving...');
            return C.saveScreenplay(beats, message).catch(err => {
                hideSavingOverlay();
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

        function updateBeatRef(beatId, field, newValue) {
            const idx = currentBeats.findIndex(b => b.beat_id === beatId);
            if (idx < 0) return;
            const updated = currentBeats.map((s, i) =>
                i === idx ? { ...s, [field]: newValue } : s);
            const human = field === 'continues_from_beat_id'
                ? 'continues_from' : 'includes';
            saveAndCatch(updated,
                'set ' + human + ' on beat_id=' + beatId + ' to ' + (newValue || 'none'));
        }

        function createBeatElement(beat, idx, color, isFirstInPaper, separatorKind) {
            const beatDiv = document.createElement('div');
            beatDiv.className = 'screenplay-beat';
            beatDiv.dataset.beat_id = beat.beat_id;
            beatDiv.dataset.beatIndex = idx;
            if (beat.isNew) beatDiv.classList.add('new-beat');

            beatDiv.appendChild(createHoverMenu(idx));

            if (!isFirstInPaper) {
                if (separatorKind) {
                    beatDiv.dataset.separator = separatorKind;
                }
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
                beatDiv.appendChild(SN.createStickyNote(beat, color, registeredPaths, {
                    beats: currentBeats,
                    orientation: orientation,
                    onUpdateBeatRef: updateBeatRef,
                }));
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
        //
        // IMPORTANT: drawArrows positions arrows using
        // getBoundingClientRect() of each beat's sticky note, so it
        // MUST be re-run whenever anything changes the size or
        // position of beats/stickies. That includes: SSE-driven
        // re-renders (renderBoard), window resize, tab visibility
        // transitions (handled by the ResizeObserver /
        // IntersectionObserver in init()), and any user action that
        // changes fold state on a paper (handled by setPaperFold).
        function drawArrows(beats, colorOf, beatColors) {
            if (!arrowLayer) return;
            while (arrowLayer.firstChild) arrowLayer.removeChild(arrowLayer.firstChild);

            const beatEls = board.querySelectorAll('.screenplay-beat');
            const boardRect = board.getBoundingClientRect();

            // Give the SVG explicit pixel dimensions matching the board
            // so paths drawn at large coordinates aren't clipped to the
            // SVG's default 300x150 viewport (overflow:visible alone is
            // not enough on all browsers for absolute-positioned SVGs).
            arrowLayer.setAttribute('width', board.scrollWidth);
            arrowLayer.setAttribute('height', board.scrollHeight);

            // Per-beat sticky-note rectangle in board coords. We later
            // pick specific anchor points along the appropriate edge
            // and offset them so multiple arrows don't overlap.
            const rects = [];
            beatEls.forEach(el => {
                const sticky = el.querySelector('.screenplay-sticky-note');
                if (!sticky) { rects.push(null); return; }
                const sr = sticky.getBoundingClientRect();
                // In folded modes the .screenplay-beat is the clip
                // container (overflow:hidden + constrained
                // width/height). The sticky inside still renders at
                // its natural size and overflows behind subsequent
                // beats; using its raw bbox would push arrow anchors
                // off-screen. Intersect with the beat's bbox so
                // anchors land on the visible portion of the sticky.
                const br = el.getBoundingClientRect();
                rects.push({
                    left:   Math.max(sr.left,   br.left)   - boardRect.left,
                    right:  Math.min(sr.right,  br.right)  - boardRect.left,
                    top:    Math.max(sr.top,    br.top)    - boardRect.top,
                    bottom: Math.min(sr.bottom, br.bottom) - boardRect.top,
                });
            });

            // Helper: compute an anchor along a sticky's edge, given a
            // position index (0..n-1 of n total anchors on that edge).
            // Anchors are distributed in the middle 60% of the edge to
            // keep them centered-ish while still being distinct.
            function edgeAnchor(idx, edge, posIdx, total) {
                const r = rects[idx];
                if (!r) return null;
                const t = total <= 1 ? 0.5 : (0.2 + 0.6 * posIdx / (total - 1));
                if (edge === 'top') {
                    return { x: r.left + (r.right - r.left) * t, y: r.top };
                } else if (edge === 'bottom') {
                    return { x: r.left + (r.right - r.left) * t, y: r.bottom };
                } else if (edge === 'left') {
                    return { x: r.left, y: r.top + (r.bottom - r.top) * t };
                } else {
                    return { x: r.right, y: r.top + (r.bottom - r.top) * t };
                }
            }

            function scrollBeatIntoView(beatId) {
                const el = board.querySelector(
                    `.screenplay-beat[data-beat_id="${beatId}"]`);
                if (!el) return;
                el.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                    inline: 'center',
                });
                // Brief highlight flash to make the destination obvious.
                const sticky = el.querySelector('.screenplay-sticky-note');
                if (sticky) {
                    sticky.classList.add('flash-highlight');
                    setTimeout(() => sticky.classList.remove('flash-highlight'), 1200);
                }
            }

            // Build list of arrows. Each arrow has a 'kind':
            //   'continues' - solid, colored from island
            //   'includes'  - colored from grayed source sticky color
            // Adjacent continues_from arrows are drawn direct (no gutter)
            // in vertical mode and skipped entirely in horizontal mode.
            // Adjacent include_beat_id arrows are always drawn direct.
            const arrows = [];
            const directArrows = [];
            beats.forEach((b, i) => {
                if (b.continues_from_beat_id) {
                    const dst = beats.findIndex(x => x.beat_id === b.continues_from_beat_id);
                    if (dst >= 0) {
                        if (Math.abs(i - dst) <= 1) {
                            if (!isHorizontal) {
                                directArrows.push({ srcIdx: i, dstIdx: dst, kind: 'continues' });
                            }
                        } else {
                            arrows.push({ srcIdx: i, dstIdx: dst, kind: 'continues' });
                        }
                    }
                }
                if (b.include_beat_id) {
                    const dst = beats.findIndex(x => x.beat_id === b.include_beat_id);
                    if (dst >= 0) {
                        if (Math.abs(i - dst) <= 1) {
                            if (!isHorizontal) {
                                directArrows.push({ srcIdx: i, dstIdx: dst, kind: 'includes' });
                            }
                        } else {
                            arrows.push({ srcIdx: i, dstIdx: dst, kind: 'includes' });
                        }
                    }
                }
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
            // Collect anchor requests per (beat index, edge) so we can
            // distribute them along the edge once we know the total
            // count. Each request gets a unique posIdx in [0, total-1].
            const anchorRequests = new Map(); // key "idx|edge" -> [request, ...]
            function requestAnchor(beatIdx, edge, request) {
                const key = beatIdx + '|' + edge;
                if (!anchorRequests.has(key)) anchorRequests.set(key, []);
                anchorRequests.get(key).push(request);
            }

            // Gutter-arrow exit/entry edges depend on orientation.
            const gutterEdge = isHorizontal ? 'bottom' : 'right';
            arrows.forEach(a => {
                requestAnchor(a.srcIdx, gutterEdge, { arrow: a, role: 'src' });
                requestAnchor(a.dstIdx, gutterEdge, { arrow: a, role: 'dst' });
            });

            // Direct-arrow edges depend on src/dst index ordering.
            directArrows.forEach(a => {
                let srcEdge, dstEdge;
                if (isHorizontal) {
                    srcEdge = a.srcIdx < a.dstIdx ? 'right' : 'left';
                    dstEdge = a.srcIdx < a.dstIdx ? 'left'  : 'right';
                } else {
                    srcEdge = a.srcIdx < a.dstIdx ? 'bottom' : 'top';
                    dstEdge = a.srcIdx < a.dstIdx ? 'top'    : 'bottom';
                }
                requestAnchor(a.srcIdx, srcEdge, { arrow: a, role: 'src' });
                requestAnchor(a.dstIdx, dstEdge, { arrow: a, role: 'dst' });
            });

            // Resolve positions: for each edge, sort requests by the
            // index of the "other" beat so arrows fan out predictably,
            // then assign posIdx.
            anchorRequests.forEach((reqs, key) => {
                reqs.sort((x, y) => {
                    const ox = x.role === 'src' ? x.arrow.dstIdx : x.arrow.srcIdx;
                    const oy = y.role === 'src' ? y.arrow.dstIdx : y.arrow.srcIdx;
                    return ox - oy;
                });
                reqs.forEach((req, i) => {
                    req.posIdx = i;
                    req.total = reqs.length;
                    req.key = key;
                });
            });

            function resolveAnchor(beatIdx, edge, arrow, role) {
                const reqs = anchorRequests.get(beatIdx + '|' + edge) || [];
                const req = reqs.find(r => r.arrow === arrow && r.role === role);
                if (!req) return null;
                return edgeAnchor(beatIdx, edge, req.posIdx, req.total);
            }

            function arrowColor(a) {
                const srcBeatId = beats[a.srcIdx].beat_id;
                // Arrows always match the (possibly grayed) source
                // sticky color, regardless of arrow kind.
                return (beatColors && beatColors.get(srcBeatId))
                    || colorOf.get(srcBeatId) || '#444';
            }

            function attachClickHandlers(linePath, headPath, arrow) {
                const srcBeatId = beats[arrow.srcIdx].beat_id;
                const dstBeatId = beats[arrow.dstIdx].beat_id;
                linePath.classList.add('arrow-line');
                headPath.classList.add('arrow-head');
                linePath.addEventListener('click', e => {
                    e.stopPropagation();
                    scrollBeatIntoView(dstBeatId);
                });
                headPath.addEventListener('click', e => {
                    e.stopPropagation();
                    scrollBeatIntoView(srcBeatId);
                });
            }

            arrows.forEach(a => {
                const src = resolveAnchor(a.srcIdx, gutterEdge, a, 'src');
                const dst = resolveAnchor(a.dstIdx, gutterEdge, a, 'dst');
                if (!src || !dst) return;
                const color = arrowColor(a);
                // Convert anchor x,y to (primary, cross) in the gutter
                // coordinate system used below.
                let srcP, srcC, dstP, dstC, laneCross;
                if (isHorizontal) {
                    srcP = src.x; srcC = src.y;
                    dstP = dst.x; dstC = dst.y;
                } else {
                    srcP = src.y; srcC = src.x;
                    dstP = dst.y; dstC = dst.x;
                }
                laneCross = Math.max(srcC, dstC)
                    + ARROW_BASE_OFFSET + a.lane * ARROW_LANE_DEPTH;
                const h = ARROW_HEAD_SIZE;

                // Split the arrow into two paths:
                //   - lineD: the long routing portion from the source
                //            sticky out to (and along) the lane.
                //   - tailHeadD: the final segment from the lane back
                //            to the destination, fused with the
                //            arrowhead, so the drop-shadow casts as a
                //            single shape and doesn't break the line.
                // We append the tail+head path *first*, then the line
                // path, so the line is painted on top and the head's
                // shadow falls behind the line rather than across it.
                let lineD, tailHeadD;
                if (isHorizontal) {
                    lineD = `M ${srcP} ${srcC} ` +
                            `L ${srcP} ${laneCross} ` +
                            `L ${dstP} ${laneCross}`;
                    tailHeadD = `M ${dstP} ${laneCross} ` +
                                `L ${dstP} ${dstC} ` +
                                `M ${dstP - h} ${dstC + h} ` +
                                `L ${dstP} ${dstC} ` +
                                `L ${dstP + h} ${dstC + h}`;
                } else {
                    lineD = `M ${srcC} ${srcP} ` +
                            `L ${laneCross} ${srcP} ` +
                            `L ${laneCross} ${dstP}`;
                    tailHeadD = `M ${laneCross} ${dstP} ` +
                                `L ${dstC} ${dstP} ` +
                                `M ${dstC + h} ${dstP - h} ` +
                                `L ${dstC} ${dstP} ` +
                                `L ${dstC + h} ${dstP + h}`;
                }

                // Append head first (drawn under), then line (drawn over).
                const head = document.createElementNS(svgNS, 'path');
                head.setAttribute('d', tailHeadD);
                head.setAttribute('stroke', color);
                arrowLayer.appendChild(head);

                const path = document.createElementNS(svgNS, 'path');
                path.setAttribute('d', lineD);
                path.setAttribute('stroke', color);
                arrowLayer.appendChild(path);

                attachClickHandlers(path, head, a);
            });

            // Direct (non-gutter) arrows: from one sticky's near edge to
            // the adjacent sticky's near edge. Vertical only for
            // continues; both orientations possible for includes.
            directArrows.forEach(a => {
                let srcEdge, dstEdge;
                if (isHorizontal) {
                    srcEdge = a.srcIdx < a.dstIdx ? 'right' : 'left';
                    dstEdge = a.srcIdx < a.dstIdx ? 'left'  : 'right';
                } else {
                    srcEdge = a.srcIdx < a.dstIdx ? 'bottom' : 'top';
                    dstEdge = a.srcIdx < a.dstIdx ? 'top'    : 'bottom';
                }
                const src = resolveAnchor(a.srcIdx, srcEdge, a, 'src');
                const dst = resolveAnchor(a.dstIdx, dstEdge, a, 'dst');
                if (!src || !dst) return;
                const color = arrowColor(a);
                const h = ARROW_HEAD_SIZE;
                // For direct arrows we likewise fuse the (very short)
                // line and arrowhead into one shape, and draw the
                // separate line beneath, so shadows are consistent.
                let lineD, tailHeadD;
                if (isHorizontal) {
                    lineD = `M ${src.x} ${src.y} L ${dst.x} ${dst.y}`;
                    const sign = dst.x > src.x ? -1 : 1;
                    tailHeadD = `M ${dst.x + sign * h} ${dst.y - h} ` +
                                `L ${dst.x} ${dst.y} ` +
                                `L ${dst.x + sign * h} ${dst.y + h}`;
                } else {
                    lineD = `M ${src.x} ${src.y} L ${dst.x} ${dst.y}`;
                    const sign = dst.y > src.y ? -1 : 1;
                    tailHeadD = `M ${dst.x - h} ${dst.y + sign * h} ` +
                                `L ${dst.x} ${dst.y} ` +
                                `L ${dst.x + h} ${dst.y + sign * h}`;
                }
                // For direct arrows, draw the line first and then the
                // arrowhead on top so the head is clearly visible.
                const path = document.createElementNS(svgNS, 'path');
                path.setAttribute('d', lineD);
                path.setAttribute('stroke', color);
                arrowLayer.appendChild(path);
                const head = document.createElementNS(svgNS, 'path');
                head.setAttribute('d', tailHeadD);
                head.setAttribute('stroke', color);
                arrowLayer.appendChild(head);
                attachClickHandlers(path, head, a);
            });
        }

        // --- Fold-state helpers ---
        //
        // applyFoldStateToPaper reads paper.dataset.fold and updates
        // the per-beat fold role classes (.fold-front / .fold-before
        // / .fold-after), the inline z-index and transform:scale()
        // that create the 3D "farther away" effect, and the
        // .selected class on the menu buttons. It deliberately does
        // NOT touch paper.dataset.fold itself; callers set that
        // first (typically in renderBoard or setPaperFold).
        //
        // Shrinking is done via a cross-axis-only scale transform:
        // scaleY() in horizontal mode (the cross-axis is vertical)
        // and scaleX() in vertical mode (the cross-axis is
        // horizontal). Scaling only along the cross-axis keeps
        // folded beats flush with their neighbors on the main flow
        // axis -- a uniform scale() would leave visible gaps because
        // CSS transforms don't affect layout. The trade-off is a
        // mild distortion on far-away beats, which is acceptable
        // since they're not meant to be read. transform-origin is
        // centered so the shrink is symmetric on both ends.
        function applyFoldStateToPaper(paper) {
            const state = paper.dataset.fold || 'max';
            const key = paper.dataset.foldKey;
            const beatEls = Array.from(
                paper.querySelectorAll(':scope > .screenplay-beat'));
            // Reset any fold-driven inline styling from a previous
            // render so 'max' returns the paper to its untouched look.
            beatEls.forEach(b => {
                b.classList.remove('fold-front', 'fold-before', 'fold-after');
                b.style.zIndex = '';
                b.style.transform = '';
                b.style.transformOrigin = '';
            });

            if (state !== 'max' && beatEls.length > 0) {
                // Determine which beat (by index) acts as the
                // "anchor" of the visual stack. In partial mode this
                // is the user-selected front beat; in full mode no
                // beat is shown in full, so we use index 0 as the
                // anchor (it ends up rendered as a fold-before-
                // styled background page at the top of the z-stack).
                let frontIdx;
                if (state === 'partial') {
                    const desiredId = frontBeats.get(key);
                    frontIdx = desiredId
                        ? beatEls.findIndex(b => b.dataset.beat_id === desiredId)
                        : 0;
                    if (frontIdx < 0) frontIdx = 0;
                } else {
                    frontIdx = 0;
                }
                // Each step further from the front shrinks by this much.
                const SHRINK_PER_STEP = 0.08;
                beatEls.forEach((b, i) => {
                    const dist = Math.abs(i - frontIdx);
                    if (state === 'partial' && i === frontIdx) {
                        b.classList.add('fold-front');
                    } else if (i < frontIdx) {
                        b.classList.add('fold-before');
                    } else if (i > frontIdx) {
                        b.classList.add('fold-after');
                    } else {
                        // state === 'full', i === 0: background page.
                        b.classList.add('fold-before');
                    }
                    if (dist > 0) {
                        b.style.zIndex = String(100 - dist);
                        // Clamp to a minimum scale so very deep
                        // beats stay visible rather than collapsing
                        // to a sliver.
                        const scale = Math.max(0.4, 1 - dist * SHRINK_PER_STEP);
                        b.style.transformOrigin = 'center center';
                        // Cross-axis-only scale: horizontal mode
                        // scales Y (cross-axis is vertical),
                        // vertical mode scales X (cross-axis is
                        // horizontal).
                        b.style.transform = isHorizontal
                            ? `scaleY(${scale})`
                            : `scaleX(${scale})`;
                    } else {
                        b.style.zIndex = '100';
                    }
                });
            }
            paper.querySelectorAll('.screenplay-fold-menu button').forEach(b => {
                b.classList.toggle('selected', b.dataset.foldOption === state);
            });
        }

        function setPaperFold(paper, state) {
            const key = paper.dataset.foldKey;
            if (key) foldStates.set(key, state);
            paper.dataset.fold = state;
            applyFoldStateToPaper(paper);
            // Folding changes beat/sticky sizes and therefore arrow
            // anchor positions. Use a double-rAF so the layout
            // engine has time to apply the new fold CSS before we
            // read getBoundingClientRect() in drawArrows; without
            // this the redraw happens against the previous layout
            // and the arrows point at stale locations.
            if (lastIslands) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => drawArrows(
                        currentBeats, lastIslands.colorOf, lastBeatColors));
                });
            }
        }

        function createFoldMenu(paperKey, currentState) {
            const menu = document.createElement('div');
            menu.className = 'screenplay-fold-menu';
            const options = [
                { v: 'max',     label: '🗖', title: 'Maximize (show all beats)' },
                { v: 'partial', label: '🗗', title: 'Partial fold (one beat visible)' },
                { v: 'full',    label: '🗕', title: 'Full fold (paper minimized)' },
            ];
            options.forEach(opt => {
                const btn = document.createElement('button');
                btn.dataset.foldOption = opt.v;
                btn.textContent = opt.label;
                btn.title = opt.title;
                if (opt.v === currentState) btn.classList.add('selected');
                btn.addEventListener('click', e => {
                    e.stopPropagation();
                    const paper = btn.closest('.screenplay-paper');
                    if (paper) setPaperFold(paper, opt.v);
                });
                menu.appendChild(btn);
            });
            return menu;
        }

        function renderBoard(beats) {
            if (!container) return;
            SN.clearRegisteredPaths(board, registeredPaths);
            while (board.firstChild) board.removeChild(board.firstChild);

            if (beats.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'screenplay-empty';
                empty.textContent = 'No screenplay loaded. Waiting for shooting-script.xml...';
                board.appendChild(empty);
                return;
            }

            const islands = C.computeIslands(beats);
            lastIslands = islands;
            const groups = C.computePaperGroups(beats, islands.islandOf);
            const includeDepths = C.computeIncludeDepths(beats);

            // Per-beat displayed sticky color, with include-graying applied.
            const beatColors = new Map();
            beats.forEach(b => {
                const base = islands.colorOf.get(b.beat_id) || C.ISLAND_COLORS[0];
                const d = includeDepths.get(b.beat_id) || 0;
                const amount = Math.min(d * 0.22, 0.85);
                beatColors.set(b.beat_id, C.grayifyColor(base, amount));
            });

            const rows = document.createElement('div');
            rows.className = 'screenplay-rows';
            board.appendChild(rows);

            groups.forEach(group => {
                const paper = document.createElement('div');
                paper.className = 'screenplay-paper';
                const paperKey = beats[group.start].beat_id;
                paper.dataset.foldKey = paperKey;
                const foldState = foldStates.get(paperKey) || 'max';
                paper.dataset.fold = foldState;
                paper.appendChild(createFoldMenu(paperKey, foldState));
                for (let i = group.start; i <= group.end; i++) {
                    const beat = beats[i];
                    const color = beatColors.get(beat.beat_id);
                    const sep = (i > group.start)
                        ? group.separators[i - group.start - 1] : null;
                    paper.appendChild(
                        createBeatElement(beat, i, color, i === group.start, sep));
                }
                applyFoldStateToPaper(paper);
                // In folded modes (partial OR full), clicking on a
                // beat that is currently clipped brings that beat to
                // the front by switching the paper to 'partial' with
                // that beat as the front. Buttons inside beats and
                // the sticky note all stopPropagation, so this
                // handler only fires for "blank" clicks on the
                // visible strip of a folded beat. In 'partial' mode
                // we skip clicks on the already-front beat to avoid
                // a no-op redraw.
                paper.addEventListener('click', e => {
                    const foldState = paper.dataset.fold;
                    if (foldState !== 'partial' && foldState !== 'full') return;
                    const beat = e.target.closest('.screenplay-beat');
                    if (!beat || !paper.contains(beat)) return;
                    if (foldState === 'partial'
                        && beat.classList.contains('fold-front')) return;
                    const beatId = beat.dataset.beat_id;
                    if (!beatId) return;
                    frontBeats.set(paperKey, beatId);
                    setPaperFold(paper, 'partial');
                });
                rows.appendChild(paper);
            });

            arrowLayer = document.createElementNS(
                'http://www.w3.org/2000/svg', 'svg');
            arrowLayer.setAttribute('class', 'screenplay-arrow-layer');
            board.appendChild(arrowLayer);

            lastBeatColors = beatColors;
            requestAnimationFrame(() => drawArrows(beats, islands.colorOf, beatColors));
        }

        function handleScreenplayUpdate(content) {
            currentBeats = content ? C.parseScreenplayXml(content) : [];
            hideSavingOverlay();
            renderBoard(currentBeats);
        }

        let lastBeatColors = null;

        function init(tabContainer) {
            container = document.createElement('div');
            container.className = 'screenplay-container';
            container.dataset.orientation = orientation;
            tabContainer.appendChild(container);

            board = document.createElement('div');
            board.className = 'screenplay-board';
            container.appendChild(board);

            // When this view becomes visible (e.g. user switches
            // tabs), arrow geometry computed while hidden will be
            // wrong (all anchors collapse to 0,0). Re-run drawArrows
            // whenever the container transitions from hidden to
            // visible. Also redraw on resize for good measure.
            let wasVisible = false;
            const checkVisibility = () => {
                if (!container || !arrowLayer || !lastIslands) return;
                const rect = container.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                if (visible && !wasVisible) {
                    drawArrows(currentBeats, lastIslands.colorOf, lastBeatColors);
                }
                wasVisible = visible;
            };
            if (typeof ResizeObserver !== 'undefined') {
                const ro = new ResizeObserver(checkVisibility);
                ro.observe(container);
            }
            if (typeof IntersectionObserver !== 'undefined') {
                const io = new IntersectionObserver(checkVisibility);
                io.observe(container);
            }
            window.addEventListener('resize', () => {
                if (arrowLayer && lastIslands) {
                    drawArrows(currentBeats, lastIslands.colorOf, lastBeatColors);
                }
            });

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

// actually create the horizontal/vertical views

(function() {
    const view = window.ScreenplayView.createView('vertical');
    window.registerTab({
        id: 'screenplay',
        label: 'Screenplay - vertical',
        pane: 'main',
        render: view.init,
    });
})();

(function() {
    const view = window.ScreenplayView.createView('horizontal');
    window.registerTab({
        id: 'storyboard',
        label: 'Screenplay - horizontal',
        pane: 'main',
        render: view.init,
    });
})();
