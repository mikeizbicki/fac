// graph.js
//
// Renders the build system dependency graph in a tab.
//
// Layout (manual; no cytoscape compound parents, no auto-layout):
//   - Target-level DAG positions come from a hidden dagre run on just
//     the target nodes and target-target edges.
//   - For each *expanded* target or group, child nodes (sub-groups and
//     path leaves) are placed at fixed offsets inside the parent's
//     rectangle using a wrapping grid.
//   - Target boxes are iteratively pushed apart so they never overlap.
//
// Because every node is a regular non-compound cytoscape node with an
// explicit width/height/position computed by these layout functions,
// the final layout is a pure function of the "effective expanded set"
// (== user expanded set ∪ auto-expanded set).
//
// Features:
//   - target->target edges use taxi routing and are always drawn.
//   - path->path (dependencies_built) edges are hidden unless the
//     cursor is over a path node that is the *source* of those edges.
//   - Node dragging is fully disabled (autoungrabify).
//   - Toolbar: Refresh, Fit, Zoom In/Out/Reset, Expand-all, Collapse-all.
//   - Each expandable container gets two small inline buttons:
//         [+]/[-]      toggle this node's expansion
//         [+children]  toggle expansion of all direct children
//     Buttons are gray when disabled (auto-expanded node, or no
//     applicable children).
//   - Auto-expand rule: any container that would have exactly one
//     direct visible child when expanded is treated as expanded
//     automatically (applied recursively).
//   - Arrow keys pan the canvas when the canvas has keyboard focus.
//
// Cytoscape is loaded from a CDN on demand so we do not vendor it.

(function() {
    const CYTOSCAPE_URL = 'https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js';
    const DAGRE_URL = 'https://unpkg.com/dagre@0.8.5/dist/dagre.min.js';
    const CYTOSCAPE_DAGRE_URL = 'https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js';

    // Layout tuning.
    const LEAF_W = 160;
    const LEAF_H = 32;
    const PAD_X = 18;
    const PAD_TOP = 30;
    const PAD_BOTTOM = 16;
    const SIBLING_GAP_X = 14;
    const SIBLING_GAP_Y = 12;
    const TARGET_MARGIN = 40;
    const TARGET_NODE_SEP = 80;
    const TARGET_RANK_SEP = 120;

    // Inline button geometry. Buttons sit inside the top-left corner
    // of an expanded container, or stacked to the right of a collapsed
    // container leaf.
    const BTN_W = 22;
    const BTN_H = 18;
    const BTN_GAP = 4;
    // Width of the "[+children]" button (wider because of label).
    const BTN_WIDE_W = 72;
    const KBD_PAN_STEP = 50;

    let cyInstance = null;
    let containerEl = null;
    let canvasEl = null;
    let loadingPromise = null;

    // User-controlled expansion set.
    let expandedIds = new Set();
    // Derived (from hierarchy): containers that must always be treated
    // as expanded because they have only one child.
    let autoExpandedIds = new Set();

    let lastGraph = null;
    let hierarchy = null;

    let parentMap = new Map();
    let knownTargetIds = new Set();
    let knownPathIds = new Set();

    // Map from button-node-id -> { action, payload }.
    let buttonHandlers = new Map();

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[data-src="${src}"]`);
            if (existing) {
                if (existing.dataset.loaded === 'true') {
                    resolve();
                } else {
                    existing.addEventListener('load', () => resolve());
                    existing.addEventListener('error', reject);
                }
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.dataset.src = src;
            script.addEventListener('load', () => {
                script.dataset.loaded = 'true';
                resolve();
            });
            script.addEventListener('error', reject);
            document.head.appendChild(script);
        });
    }

    function ensureLibsLoaded() {
        if (loadingPromise) return loadingPromise;
        loadingPromise = (async () => {
            await loadScript(CYTOSCAPE_URL);
            await loadScript(DAGRE_URL);
            await loadScript(CYTOSCAPE_DAGRE_URL);
            if (window.cytoscape && window.cytoscapeDagre) {
                window.cytoscape.use(window.cytoscapeDagre);
            }
        })();
        return loadingPromise;
    }

    // ---------- ID helpers ----------

    function targetCyId(id) { return `target::${id}`; }
    function pathCyId(id)   { return `path::${id}`; }
    function groupCyId(targetId, chain) {
        const tail = chain.map(([k, v]) => `${k}=${v}`).join('|');
        return `group::${targetId}::${tail}`;
    }

    // ---------- Variable parsing ----------

    function extractVariableNames(targetPattern) {
        const vars = [];
        const regex = /\$([A-Z_][A-Z0-9_]*)/g;
        let m;
        while ((m = regex.exec(targetPattern)) !== null) {
            if (!vars.includes(m[1])) vars.push(m[1]);
        }
        return vars;
    }

    // ---------- Hierarchy construction ----------

    function buildHierarchy(graph) {
        const targetsById = {};
        const targetOrder = [];
        const pathNodes = [];

        for (const node of graph.nodes || []) {
            if (node.type === 'target') {
                if (!targetsById[node.id]) {
                    targetsById[node.id] = {
                        id: node.id,
                        cyId: targetCyId(node.id),
                        data: node.data || {},
                        varNames: extractVariableNames(node.id),
                        root: null,
                    };
                    targetOrder.push(node.id);
                }
            } else if (node.type === 'path') {
                pathNodes.push(node);
            }
        }

        for (const tId of targetOrder) {
            const t = targetsById[tId];
            t.root = makeGroup(t.id, '', true, []);
        }

        for (const pNode of pathNodes) {
            const t = targetsById[pNode.target];
            if (!t) continue;
            const resolved = (pNode.data && pNode.data.variables_resolved) || {};
            const chain = [];
            let group = t.root;
            for (const varName of t.varNames) {
                const val = resolved[varName];
                if (val === undefined || val === null) break;
                chain.push([varName, val]);
                let child = group.children.find(c =>
                    c.label === `${varName}=${val}`);
                if (!child) {
                    child = makeGroup(t.id, `${varName}=${val}`, false,
                                      chain.slice());
                    group.children.push(child);
                }
                group = child;
            }
            group.paths.push({
                cyId: pathCyId(pNode.id),
                id: pNode.id,
                data: pNode.data || {},
            });
        }

        return { targets: targetOrder.map(id => targetsById[id]) };
    }

    function makeGroup(targetId, label, isRoot, chain) {
        return {
            cyId: groupCyId(targetId, chain),
            label,
            isRoot,
            children: [],
            paths: [],
            targetId,
            chain,
        };
    }

    function buildParentMap() {
        parentMap = new Map();
        for (const t of hierarchy.targets) {
            parentMap.set(t.cyId, null);
            walkGroup(t.root, t.cyId);
        }
        function walkGroup(g, parentCyId) {
            if (!g.isRoot) {
                parentMap.set(g.cyId, parentCyId);
                parentCyId = g.cyId;
            }
            for (const sub of g.children) walkGroup(sub, parentCyId);
            for (const p of g.paths) parentMap.set(p.cyId, parentCyId);
        }
    }

    function buildKnownIdSets(graph) {
        knownTargetIds = new Set();
        knownPathIds = new Set();
        for (const n of graph.nodes || []) {
            if (n.type === 'target') knownTargetIds.add(n.id);
            else if (n.type === 'path') knownPathIds.add(n.id);
        }
    }

    // ---------- Auto-expand computation ----------

    function computeAutoExpandedIds() {
        autoExpandedIds = new Set();
        for (const t of hierarchy.targets) {
            if (targetDirectChildCount(t) === 1) {
                autoExpandedIds.add(t.cyId);
            }
            walkGroupAuto(t.root);
        }
        function walkGroupAuto(g) {
            if (!g.isRoot) {
                if (groupDirectChildCount(g) === 1) {
                    autoExpandedIds.add(g.cyId);
                }
            }
            for (const sub of g.children) walkGroupAuto(sub);
        }
    }

    function targetDirectChildCount(t) {
        // Direct children = children of t.root.
        return t.root.children.length + t.root.paths.length;
    }

    function groupDirectChildCount(g) {
        return g.children.length + g.paths.length;
    }

    function isEffectivelyExpanded(cyId) {
        return expandedIds.has(cyId) || autoExpandedIds.has(cyId);
    }

    function isAutoExpanded(cyId) {
        return autoExpandedIds.has(cyId);
    }

    // ---------- Layout ----------
    //
    // Plan object: { width, height, place(cx, cy, out) }
    // Placement record:
    //   { cyId, x, y, w, h, kind, label, depth, state?, collapsed?,
    //     expandable?, hasChildren?, autoExpanded? }

    function layoutPathLeaf(p, depth) {
        return {
            width: LEAF_W,
            height: LEAF_H,
            place(cx, cy, out) {
                out.push({
                    cyId: p.cyId,
                    x: cx, y: cy,
                    w: LEAF_W, h: LEAF_H,
                    kind: 'path',
                    label: p.id,
                    state: (p.data && p.data.state) || null,
                    depth,
                });
            },
        };
    }

    function layoutGroup(group, depth) {
        const hasChildren = groupDirectChildCount(group) > 0;
        const expanded = isEffectivelyExpanded(group.cyId);

        if (!expanded || !hasChildren) {
            // Collapsed leaf: room for control buttons to the right.
            const w = LEAF_W + (hasChildren ? (BTN_W + BTN_GAP) * 1 : 0);
            return {
                width: w,
                height: LEAF_H,
                place(cx, cy, out) {
                    out.push({
                        cyId: group.cyId,
                        x: cx, y: cy,
                        w: w, h: LEAF_H,
                        kind: 'group',
                        label: group.label,
                        depth,
                        collapsed: true,
                        expandable: hasChildren,
                        hasChildren,
                        autoExpanded: false,
                    });
                    if (hasChildren) {
                        emitCollapsedButtons(group.cyId, cx, cy, w, LEAF_H,
                                             /*isGroup*/ true,
                                             /*hasChildren*/ hasChildren,
                                             out);
                    }
                },
            };
        }

        // Expanded.
        const childPlans = [];
        for (const sub of group.children) {
            childPlans.push({ kind: 'group', plan: layoutGroup(sub, depth + 1) });
        }
        for (const p of group.paths) {
            childPlans.push({ kind: 'path', plan: layoutPathLeaf(p, depth + 1) });
        }
        const grid = computeGrid(childPlans);
        const width = grid.innerW + 2 * PAD_X;
        const height = grid.innerH + PAD_TOP + PAD_BOTTOM;

        return {
            width,
            height,
            place(cx, cy, out) {
                out.push({
                    cyId: group.cyId,
                    x: cx, y: cy,
                    w: width, h: height,
                    kind: 'group',
                    label: group.label,
                    depth,
                    collapsed: false,
                    expandable: true,
                    hasChildren: true,
                    autoExpanded: isAutoExpanded(group.cyId),
                });
                emitExpandedButtons(group.cyId, cx, cy, width, height,
                                    /*isTarget*/ false,
                                    hasContainerChildren(group),
                                    isAutoExpanded(group.cyId),
                                    out);
                placeGrid(grid, cx, cy, width, height, out);
            },
        };
    }

    function hasContainerChildren(group) {
        // True if any direct child is itself an expandable container
        // (i.e. a sub-group; paths are not containers).
        for (const sub of group.children) {
            if (groupDirectChildCount(sub) > 0) return true;
        }
        return false;
    }

    function layoutTarget(t) {
        const direct = targetDirectChildCount(t);
        const expanded = isEffectivelyExpanded(t.cyId);
        const expandable = direct > 0;

        if (!expanded || !expandable) {
            const w = LEAF_W + (expandable ? (BTN_W + BTN_GAP) * 1 : 0);
            return {
                width: w,
                height: LEAF_H,
                place(cx, cy, out) {
                    out.push({
                        cyId: t.cyId,
                        x: cx, y: cy,
                        w: w, h: LEAF_H,
                        kind: 'target',
                        label: t.id,
                        depth: 0,
                        collapsed: true,
                        expandable,
                        hasChildren: expandable,
                        autoExpanded: false,
                    });
                    if (expandable) {
                        emitCollapsedButtons(t.cyId, cx, cy, w, LEAF_H,
                                             /*isGroup*/ false,
                                             expandable, out);
                    }
                },
            };
        }

        // Expanded target: lay out root group's children directly inside.
        const childPlans = [];
        for (const sub of t.root.children) {
            childPlans.push({ kind: 'group', plan: layoutGroup(sub, 1) });
        }
        for (const p of t.root.paths) {
            childPlans.push({ kind: 'path', plan: layoutPathLeaf(p, 1) });
        }
        const grid = computeGrid(childPlans);
        const width = grid.innerW + 2 * PAD_X;
        const height = grid.innerH + PAD_TOP + PAD_BOTTOM;

        const targetHasContainerChildren = t.root.children.some(
            sub => groupDirectChildCount(sub) > 0);

        return {
            width,
            height,
            place(cx, cy, out) {
                out.push({
                    cyId: t.cyId,
                    x: cx, y: cy,
                    w: width, h: height,
                    kind: 'target',
                    label: t.id,
                    depth: 0,
                    collapsed: false,
                    expandable: true,
                    hasChildren: true,
                    autoExpanded: isAutoExpanded(t.cyId),
                });
                emitExpandedButtons(t.cyId, cx, cy, width, height,
                                    /*isTarget*/ true,
                                    targetHasContainerChildren,
                                    isAutoExpanded(t.cyId),
                                    out);
                placeGrid(grid, cx, cy, width, height, out);
            },
        };
    }

    function computeGrid(childPlans) {
        const n = childPlans.length;
        if (n === 0) {
            return { rows: [], rowHeights: [], colWidths: [],
                     innerW: 0, innerH: 0 };
        }
        const cols = Math.max(1, Math.ceil(Math.sqrt(n)));
        const rows = [];
        for (let i = 0; i < n; i += cols) {
            rows.push(childPlans.slice(i, i + cols));
        }
        const rowHeights = rows.map(row =>
            row.reduce((m, c) => Math.max(m, c.plan.height), 0));
        const colWidths = [];
        for (let c = 0; c < cols; c++) {
            let w = 0;
            for (const row of rows) {
                if (row[c]) w = Math.max(w, row[c].plan.width);
            }
            colWidths.push(w);
        }
        const innerW = colWidths.reduce((a, b) => a + b, 0)
            + SIBLING_GAP_X * Math.max(0, colWidths.length - 1);
        const innerH = rowHeights.reduce((a, b) => a + b, 0)
            + SIBLING_GAP_Y * Math.max(0, rows.length - 1);
        return { rows, rowHeights, colWidths, innerW, innerH };
    }

    function placeGrid(grid, cx, cy, width, height, out) {
        const left = cx - width / 2 + PAD_X;
        const top = cy - height / 2 + PAD_TOP;
        let yCursor = top;
        for (let r = 0; r < grid.rows.length; r++) {
            let xCursor = left;
            const rowH = grid.rowHeights[r];
            for (let c = 0; c < grid.rows[r].length; c++) {
                const child = grid.rows[r][c];
                const colW = grid.colWidths[c];
                const childCx = xCursor + colW / 2;
                const childCy = yCursor + rowH / 2;
                child.plan.place(childCx, childCy, out);
                xCursor += colW + SIBLING_GAP_X;
            }
            yCursor += rowH + SIBLING_GAP_Y;
        }
    }

    // ---------- Button placement ----------

    function emitExpandedButtons(ownerCyId, cx, cy, w, h,
                                 isTarget, hasContainerChildren,
                                 isAuto, out) {
        // Buttons sit just inside the top-left corner of the container.
        const bx0 = cx - w / 2 + 6;
        const by  = cy - h / 2 + 6 + BTN_H / 2;

        // Toggle (collapse) button.
        out.push({
            cyId: `btn::${ownerCyId}::toggle`,
            x: bx0 + BTN_W / 2,
            y: by,
            w: BTN_W, h: BTN_H,
            kind: 'button',
            buttonKind: 'toggle',
            label: '−',
            ownerCyId,
            disabled: isAuto,
            depth: 0,
        });

        // [+children] button.
        const bx1 = bx0 + BTN_W + BTN_GAP;
        out.push({
            cyId: `btn::${ownerCyId}::children`,
            x: bx1 + BTN_WIDE_W / 2,
            y: by,
            w: BTN_WIDE_W, h: BTN_H,
            kind: 'button',
            buttonKind: 'children-expand',
            label: '+children',
            ownerCyId,
            disabled: !hasContainerChildren,
            depth: 0,
        });

        // [-children] button below row.
        const by2 = by + BTN_H + BTN_GAP;
        out.push({
            cyId: `btn::${ownerCyId}::children-collapse`,
            x: bx1 + BTN_WIDE_W / 2,
            y: by2,
            w: BTN_WIDE_W, h: BTN_H,
            kind: 'button',
            buttonKind: 'children-collapse',
            label: '−children',
            ownerCyId,
            disabled: !hasContainerChildren,
            depth: 0,
        });
    }

    function emitCollapsedButtons(ownerCyId, cx, cy, w, h,
                                  isGroup, hasChildren, out) {
        // Single toggle button at the right edge of the collapsed leaf.
        const bx = cx + w / 2 - 6 - BTN_W / 2;
        out.push({
            cyId: `btn::${ownerCyId}::toggle`,
            x: bx,
            y: cy,
            w: BTN_W, h: BTN_H,
            kind: 'button',
            buttonKind: 'toggle',
            label: '+',
            ownerCyId,
            disabled: !hasChildren,
            depth: 0,
        });
    }

    // ---------- Target-level layout ----------

    function computeTargetCenters() {
        const targetEls = [];
        for (const t of hierarchy.targets) {
            targetEls.push({ group: 'nodes', data: { id: t.cyId } });
        }
        for (const edge of lastGraph.edges || []) {
            if (edge.kind !== 'target-target') continue;
            const sId = targetCyId(edge.source);
            const tId = targetCyId(edge.target);
            if (!knownTargetIds.has(edge.source)
                || !knownTargetIds.has(edge.target)) continue;
            targetEls.push({
                group: 'edges',
                data: { id: `${sId}->${tId}`, source: sId, target: tId },
            });
        }
        const tmpDiv = document.createElement('div');
        tmpDiv.style.position = 'absolute';
        tmpDiv.style.width = '1000px';
        tmpDiv.style.height = '1000px';
        tmpDiv.style.left = '-10000px';
        tmpDiv.style.top = '-10000px';
        document.body.appendChild(tmpDiv);

        const centers = new Map();
        try {
            const tmpCy = window.cytoscape({
                container: tmpDiv,
                elements: targetEls,
                style: [],
            });
            tmpCy.layout({
                name: 'dagre',
                rankDir: 'TB',
                nodeSep: TARGET_NODE_SEP,
                rankSep: TARGET_RANK_SEP,
            }).run();
            tmpCy.nodes().forEach(n => {
                const pos = n.position();
                centers.set(n.id(), { x: pos.x, y: pos.y });
            });
            tmpCy.destroy();
        } finally {
            tmpDiv.remove();
        }
        return centers;
    }

    function separateBoxes(centers, boxes) {
        const ids = Array.from(centers.keys());
        const MAX_PASSES = 400;
        for (let pass = 0; pass < MAX_PASSES; pass++) {
            let moved = false;
            for (let i = 0; i < ids.length; i++) {
                for (let j = i + 1; j < ids.length; j++) {
                    const a = ids[i], b = ids[j];
                    const ca = centers.get(a), cb = centers.get(b);
                    const ba = boxes.get(a), bb = boxes.get(b);
                    const halfWA = ba.width / 2, halfHA = ba.height / 2;
                    const halfWB = bb.width / 2, halfHB = bb.height / 2;
                    const dx = cb.x - ca.x;
                    const dy = cb.y - ca.y;
                    const overlapX = (halfWA + halfWB + TARGET_MARGIN)
                                    - Math.abs(dx);
                    const overlapY = (halfHA + halfHB + TARGET_MARGIN)
                                    - Math.abs(dy);
                    if (overlapX > 0 && overlapY > 0) {
                        if (overlapX < overlapY) {
                            const shift = overlapX / 2 + 0.5;
                            const sign = dx >= 0 ? 1 : -1;
                            centers.set(b, { x: cb.x + sign * shift, y: cb.y });
                            centers.set(a, { x: ca.x - sign * shift, y: ca.y });
                        } else {
                            const shift = overlapY / 2 + 0.5;
                            const sign = dy >= 0 ? 1 : -1;
                            centers.set(b, { x: cb.x, y: cb.y + sign * shift });
                            centers.set(a, { x: ca.x, y: ca.y - sign * shift });
                        }
                        moved = true;
                    }
                }
            }
            if (!moved) break;
        }
    }

    // ---------- Elements ----------

    function endpointTypeFor(id, kind) {
        const inT = knownTargetIds.has(id);
        const inP = knownPathIds.has(id);
        const preferPath = (kind === 'dependencies_built');
        if (inT && inP) return preferPath ? 'path' : 'target';
        if (inT) return 'target';
        if (inP) return 'path';
        return preferPath ? 'path' : 'target';
    }

    function buildElementsAndPositions() {
        const baseCenters = computeTargetCenters();

        const targetPlans = new Map();
        const targetBoxes = new Map();
        for (const t of hierarchy.targets) {
            const plan = layoutTarget(t);
            targetPlans.set(t.cyId, plan);
            targetBoxes.set(t.cyId, { width: plan.width, height: plan.height });
        }

        const centers = new Map(baseCenters);
        for (const t of hierarchy.targets) {
            if (!centers.has(t.cyId)) centers.set(t.cyId, { x: 0, y: 0 });
        }
        separateBoxes(centers, targetBoxes);

        const placements = [];
        for (const t of hierarchy.targets) {
            const c = centers.get(t.cyId);
            targetPlans.get(t.cyId).place(c.x, c.y, placements);
        }

        const visibleIds = new Set(placements.map(p => p.cyId));

        // Sort: containers (non-collapsed target/group) first, by depth,
        // then leaves, then buttons last (so buttons render on top).
        const sorted = placements.slice().sort((a, b) => {
            return zOrderRank(a) - zOrderRank(b);
        });

        buttonHandlers = new Map();

        const elements = [];
        for (const p of sorted) {
            if (p.kind === 'button') {
                // Register handler.
                buttonHandlers.set(p.cyId, {
                    buttonKind: p.buttonKind,
                    ownerCyId: p.ownerCyId,
                    disabled: p.disabled,
                });
                elements.push({
                    group: 'nodes',
                    data: {
                        id: p.cyId,
                        label: p.label,
                        nodeType: 'button',
                        width: p.w,
                        height: p.h,
                        disabled: p.disabled,
                        zIndexValue: 5000,
                    },
                    position: { x: p.x, y: p.y },
                    classes: 'node-button'
                        + (p.disabled ? ' disabled' : '')
                        + ` btn-${p.buttonKind}`,
                    grabbable: false,
                    selectable: false,
                });
                continue;
            }

            elements.push({
                group: 'nodes',
                data: {
                    id: p.cyId,
                    label: p.label,
                    nodeType: p.kind,
                    width: p.w,
                    height: p.h,
                    collapsed: !!p.collapsed,
                    expandable: !!p.expandable,
                    state: p.state || null,
                    depth: p.depth,
                    zIndexValue: zIndexFor(p),
                },
                position: { x: p.x, y: p.y },
                classes: nodeClasses(p),
                grabbable: false,
                selectable: true,
            });
        }

        // Edges (retargeted to nearest visible ancestor on each end).
        const ancestorCache = new Map();
        const resolveVisible = (cyId) => {
            if (visibleIds.has(cyId)) return cyId;
            if (ancestorCache.has(cyId)) return ancestorCache.get(cyId);
            let cur = cyId;
            while (cur && !visibleIds.has(cur)) {
                cur = parentMap.get(cur) || null;
            }
            ancestorCache.set(cyId, cur);
            return cur;
        };

        const seenEdgeKeys = new Set();
        for (const edge of lastGraph.edges || []) {
            const kind = edge.kind || '';
            const sType = endpointTypeFor(edge.source, kind);
            const tType = endpointTypeFor(edge.target, kind);
            const sOrig = sType === 'target'
                ? targetCyId(edge.source) : pathCyId(edge.source);
            const tOrig = tType === 'target'
                ? targetCyId(edge.target) : pathCyId(edge.target);
            const sCy = resolveVisible(sOrig);
            const tCy = resolveVisible(tOrig);
            if (!sCy || !tCy) continue;
            if (sCy === tCy) continue;

            const key = `${kind}|${sCy}|${tCy}`;
            if (seenEdgeKeys.has(key)) continue;
            seenEdgeKeys.add(key);

            elements.push({
                group: 'edges',
                data: {
                    id: `e::${key}`,
                    source: sCy,
                    target: tCy,
                    kind: kind,
                    origSource: edge.source,
                    origTarget: edge.target,
                },
                classes: `edge-${kind}`,
            });
        }

        return { elements };
    }

    function zOrderRank(p) {
        if (p.kind === 'button') return 4000;
        if (p.kind === 'path') return 3000;
        if ((p.kind === 'target' || p.kind === 'group') && p.collapsed) {
            return 2000;
        }
        // Expanded containers: shallower depth renders first (lower).
        return 100 + p.depth * 10;
    }

    function zIndexFor(p) {
        if (p.kind === 'path') return 1000;
        if (p.collapsed) return 800;
        return 100 + p.depth * 10;
    }

    function nodeClasses(p) {
        const parts = [];
        if (p.kind === 'target') {
            parts.push('node-target');
            parts.push(p.collapsed ? 'collapsed' : 'expanded');
            if (p.autoExpanded) parts.push('auto-expanded');
        } else if (p.kind === 'group') {
            parts.push('node-group');
            parts.push(p.collapsed ? 'collapsed' : 'expanded');
            if (p.expandable) parts.push('expandable');
            if (p.autoExpanded) parts.push('auto-expanded');
        } else if (p.kind === 'path') {
            parts.push('node-path');
            if (p.state) parts.push(`state-${p.state}`);
        }
        return parts.join(' ');
    }

    // ---------- Style ----------

    function getStyle() {
        return [
            // Target container.
            {
                selector: 'node.node-target',
                style: {
                    'shape': 'round-rectangle',
                    'width': 'data(width)',
                    'height': 'data(height)',
                    'background-color': '#f5f7fb',
                    'background-opacity': 0.6,
                    'border-color': '#5a7fb8',
                    'border-width': 2,
                    'border-style': 'dashed',
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'right',
                    'text-margin-x': -8,
                    'text-margin-y': 6,
                    'font-size': 11,
                    'font-weight': 'bold',
                    'color': '#2c3e64',
                    'z-index': 'data(zIndexValue)',
                },
            },
            {
                selector: 'node.node-target.collapsed',
                style: {
                    'background-color': '#e8eefb',
                    'background-opacity': 1,
                    'border-style': 'solid',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'text-margin-x': -10,
                    'text-margin-y': 0,
                    'text-wrap': 'ellipsis',
                    'text-max-width': LEAF_W - 12,
                },
            },
            // Group container.
            {
                selector: 'node.node-group',
                style: {
                    'shape': 'round-rectangle',
                    'width': 'data(width)',
                    'height': 'data(height)',
                    'background-color': '#fbf6ea',
                    'background-opacity': 0.7,
                    'border-color': '#b08a00',
                    'border-width': 1,
                    'border-style': 'dotted',
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'right',
                    'text-margin-x': -8,
                    'text-margin-y': 6,
                    'font-size': 10,
                    'color': '#6b5400',
                    'z-index': 'data(zIndexValue)',
                },
            },
            {
                selector: 'node.node-group.collapsed',
                style: {
                    'background-color': '#fff4cc',
                    'background-opacity': 1,
                    'border-style': 'solid',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'text-margin-x': -10,
                    'text-margin-y': 0,
                    'text-wrap': 'ellipsis',
                    'text-max-width': LEAF_W - 12,
                },
            },
            // Path leaf.
            {
                selector: 'node.node-path',
                style: {
                    'shape': 'round-rectangle',
                    'width': 'data(width)',
                    'height': 'data(height)',
                    'background-color': '#ffffff',
                    'border-color': '#888',
                    'border-width': 1,
                    'label': 'data(label)',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': 10,
                    'color': '#222',
                    'text-wrap': 'ellipsis',
                    'text-max-width': LEAF_W - 12,
                    'z-index': 'data(zIndexValue)',
                },
            },
            {
                selector: 'node.node-path.state-built',
                style: { 'background-color': '#d6f5d6', 'border-color': '#2e8b3a' },
            },
            {
                selector: 'node.node-path.state-notbuilt',
                style: { 'background-color': '#fdecea', 'border-color': '#b03030' },
            },
            {
                selector: 'node.node-path.state-stale',
                style: { 'background-color': '#fff4cc', 'border-color': '#b08a00' },
            },
            {
                selector: 'node.node-path.state-building',
                style: { 'background-color': '#dceeff', 'border-color': '#1f6fd0' },
            },
            {
                selector: 'node:selected',
                style: { 'border-color': '#ff7e29', 'border-width': 3 },
            },
            // Inline button nodes.
            {
                selector: 'node.node-button',
                style: {
                    'shape': 'round-rectangle',
                    'width': 'data(width)',
                    'height': 'data(height)',
                    'background-color': '#ffffff',
                    'border-color': '#666',
                    'border-width': 1,
                    'label': 'data(label)',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': 10,
                    'font-weight': 'bold',
                    'color': '#222',
                    'z-index': 'data(zIndexValue)',
                    'padding': 0,
                },
            },
            {
                selector: 'node.node-button.disabled',
                style: {
                    'background-color': '#eee',
                    'border-color': '#bbb',
                    'color': '#aaa',
                },
            },
            // Edges.
            {
                selector: 'edge',
                style: {
                    'curve-style': 'taxi',
                    'taxi-direction': 'auto',
                    'taxi-turn': 28,
                    'taxi-turn-min-distance': 8,
                    'target-arrow-shape': 'triangle',
                    'width': 1.5,
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'arrow-scale': 0.9,
                    'z-index': 50,
                },
            },
            {
                selector: 'edge.edge-target-target',
                style: {
                    'curve-style': 'taxi',
                    'line-color': '#5a7fb8',
                    'target-arrow-color': '#5a7fb8',
                    'width': 2,
                    'z-index': 60,
                },
            },
            {
                selector: 'edge.edge-path-target, edge.edge-target-path',
                style: {
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'line-style': 'dashed',
                },
            },
            {
                selector: 'edge.edge-dependencies_built',
                style: {
                    'curve-style': 'bezier',
                    'line-color': '#2e8b3a',
                    'target-arrow-color': '#2e8b3a',
                    'line-style': 'dotted',
                    'width': 1,
                    'display': 'none',
                    'z-index': 70,
                },
            },
            {
                selector: 'edge.edge-dependencies_built.reveal',
                style: { 'display': 'element' },
            },
        ];
    }

    // ---------- Rendering & interactions ----------

    async function fetchGraph() {
        const response = await fetch('/dep_graph');
        if (!response.ok) {
            throw new Error(`/dep_graph returned ${response.status}`);
        }
        return response.json();
    }

    function rebuildAndRender() {
        if (!cyInstance) return;
        computeAutoExpandedIds();
        const { elements } = buildElementsAndPositions();
        cyInstance.elements().remove();
        cyInstance.add(elements);
        wireInteractionHandlers();
    }

    function wireInteractionHandlers() {
        cyInstance.off('tap', 'node');
        cyInstance.on('tap', 'node', evt => {
            const node = evt.target;
            const nodeType = node.data('nodeType');
            if (nodeType !== 'button') return;
            const h = buttonHandlers.get(node.id());
            if (!h || h.disabled) return;
            handleButtonClick(h);
        });

        cyInstance.off('mouseover', 'node.node-path');
        cyInstance.off('mouseout', 'node.node-path');
        cyInstance.on('mouseover', 'node.node-path', evt => {
            const id = evt.target.id();
            cyInstance.edges('.edge-dependencies_built').forEach(e => {
                if (e.data('source') === id) e.addClass('reveal');
            });
        });
        cyInstance.on('mouseout', 'node.node-path', () => {
            cyInstance.edges('.edge-dependencies_built.reveal')
                .removeClass('reveal');
        });
    }

    function handleButtonClick(h) {
        switch (h.buttonKind) {
            case 'toggle':
                toggleSingle(h.ownerCyId);
                break;
            case 'children-expand':
                expandDirectChildren(h.ownerCyId);
                break;
            case 'children-collapse':
                collapseDirectChildren(h.ownerCyId);
                break;
        }
        rebuildAndRender();
    }

    function toggleSingle(cyId) {
        if (isAutoExpanded(cyId)) return; // can't change
        if (expandedIds.has(cyId)) {
            // Collapsing: also clear descendants from user-expanded set.
            expandedIds.delete(cyId);
            forEachDescendantContainer(cyId, id => expandedIds.delete(id));
        } else {
            expandedIds.add(cyId);
        }
    }

    function expandDirectChildren(cyId) {
        forEachDirectChildContainer(cyId, id => expandedIds.add(id));
    }

    function collapseDirectChildren(cyId) {
        forEachDirectChildContainer(cyId, id => {
            expandedIds.delete(id);
            forEachDescendantContainer(id, did => expandedIds.delete(did));
        });
    }

    function expandAll() {
        for (const t of hierarchy.targets) {
            expandedIds.add(t.cyId);
            forEachDescendantContainer(t.cyId, id => expandedIds.add(id));
        }
        rebuildAndRender();
    }

    function collapseAll() {
        expandedIds = new Set();
        rebuildAndRender();
    }

    // Walks the hierarchy to find all container descendants of cyId.
    function forEachDescendantContainer(cyId, fn) {
        const node = findHierarchyContainer(cyId);
        if (!node) return;
        if (node.kind === 'target') {
            // Target's descendants are sub-groups of its root.
            for (const sub of node.target.root.children) {
                visitGroup(sub);
            }
        } else if (node.kind === 'group') {
            for (const sub of node.group.children) {
                visitGroup(sub);
            }
        }
        function visitGroup(g) {
            // Only consider it a "container" if it has children.
            if (groupDirectChildCount(g) > 0) {
                fn(g.cyId);
            }
            for (const sub of g.children) visitGroup(sub);
        }
    }

    function forEachDirectChildContainer(cyId, fn) {
        const node = findHierarchyContainer(cyId);
        if (!node) return;
        const subs = node.kind === 'target'
            ? node.target.root.children
            : node.group.children;
        for (const sub of subs) {
            if (groupDirectChildCount(sub) > 0) fn(sub.cyId);
        }
    }

    function findHierarchyContainer(cyId) {
        for (const t of hierarchy.targets) {
            if (t.cyId === cyId) return { kind: 'target', target: t };
            const g = findGroupByCyId(t.root, cyId);
            if (g) return { kind: 'group', group: g };
        }
        return null;
    }

    function findGroupByCyId(group, cyId) {
        if (group.cyId === cyId && !group.isRoot) return group;
        for (const sub of group.children) {
            const r = findGroupByCyId(sub, cyId);
            if (r) return r;
        }
        return null;
    }

    async function renderGraph() {
        if (!containerEl) return;
        const graphRoot = containerEl.querySelector('.graph-canvas');
        const statusEl = containerEl.querySelector('.graph-status');

        statusEl.textContent = 'Loading graph...';
        statusEl.classList.remove('graph-status-error');

        try {
            await ensureLibsLoaded();
            const data = await fetchGraph();
            lastGraph = data;
            buildKnownIdSets(data);
            hierarchy = buildHierarchy(data);
            buildParentMap();
            expandedIds = new Set();

            if (cyInstance) {
                cyInstance.destroy();
                cyInstance = null;
            }

            cyInstance = window.cytoscape({
                container: graphRoot,
                elements: [],
                style: getStyle(),
                wheelSensitivity: 0.2,
                layout: { name: 'preset' },
                autoungrabify: true,
                boxSelectionEnabled: false,
            });

            rebuildAndRender();
            cyInstance.fit(undefined, 30);

            statusEl.textContent =
                `${data.nodes ? data.nodes.length : 0} nodes, ` +
                `${data.edges ? data.edges.length : 0} edges`;
        } catch (err) {
            console.error('graph.js: failed to render graph', err);
            statusEl.textContent = `Error: ${err.message}`;
            statusEl.classList.add('graph-status-error');
        }
    }

    function renderTab(container) {
        containerEl = document.createElement('div');
        containerEl.className = 'graph-tab';
        containerEl.innerHTML = `
            <div class="graph-toolbar">
                <button class="graph-refresh-btn" type="button">Refresh</button>
                <button class="graph-fit-btn" type="button">Fit</button>
                <button class="graph-zoom-in-btn" type="button" title="Zoom in">+</button>
                <button class="graph-zoom-out-btn" type="button" title="Zoom out">−</button>
                <button class="graph-zoom-reset-btn" type="button" title="Reset zoom">Reset</button>
                <button class="graph-expand-all-btn" type="button">Expand all</button>
                <button class="graph-collapse-all-btn" type="button">Collapse all</button>
                <span class="graph-status"></span>
            </div>
            <div class="graph-canvas" tabindex="0"></div>
        `;
        container.appendChild(containerEl);

        canvasEl = containerEl.querySelector('.graph-canvas');

        containerEl.querySelector('.graph-refresh-btn')
            .addEventListener('click', () => renderGraph());
        containerEl.querySelector('.graph-fit-btn')
            .addEventListener('click', () => {
                if (cyInstance) cyInstance.fit(undefined, 30);
            });
        containerEl.querySelector('.graph-zoom-in-btn')
            .addEventListener('click', () => zoomBy(1.25));
        containerEl.querySelector('.graph-zoom-out-btn')
            .addEventListener('click', () => zoomBy(1 / 1.25));
        containerEl.querySelector('.graph-zoom-reset-btn')
            .addEventListener('click', () => {
                if (cyInstance) {
                    cyInstance.zoom(1);
                    cyInstance.center();
                }
            });
        containerEl.querySelector('.graph-expand-all-btn')
            .addEventListener('click', expandAll);
        containerEl.querySelector('.graph-collapse-all-btn')
            .addEventListener('click', collapseAll);

        // Keyboard panning when canvas is focused.
        canvasEl.addEventListener('keydown', evt => {
            if (!cyInstance) return;
            let dx = 0, dy = 0;
            switch (evt.key) {
                case 'ArrowLeft':  dx = +KBD_PAN_STEP; break;
                case 'ArrowRight': dx = -KBD_PAN_STEP; break;
                case 'ArrowUp':    dy = +KBD_PAN_STEP; break;
                case 'ArrowDown':  dy = -KBD_PAN_STEP; break;
                default: return;
            }
            const mult = evt.shiftKey ? 3 : 1;
            const pan = cyInstance.pan();
            cyInstance.pan({ x: pan.x + dx * mult, y: pan.y + dy * mult });
            evt.preventDefault();
        });
        // Focus the canvas on click so arrow keys work.
        canvasEl.addEventListener('mousedown', () => canvasEl.focus());

        renderGraph();
    }

    function zoomBy(factor) {
        if (!cyInstance) return;
        const ext = cyInstance.extent();
        const cx = (ext.x1 + ext.x2) / 2;
        const cy = (ext.y1 + ext.y2) / 2;
        const pan = cyInstance.pan();
        const z = cyInstance.zoom();
        const rx = cx * z + pan.x;
        const ry = cy * z + pan.y;
        cyInstance.zoom({
            level: z * factor,
            renderedPosition: { x: rx, y: ry },
        });
    }

    function onActivate() {
        if (cyInstance) {
            cyInstance.resize();
            cyInstance.fit(undefined, 30);
        }
    }

    if (window.registerTab) {
        window.registerTab({
            id: 'graph',
            label: 'Graph',
            pane: 'main',
            render: renderTab,
            onActivate: onActivate,
        });
    }
})();
