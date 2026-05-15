// graph.js
//
// Renders the build system dependency graph in a tab.
//
// Fetches the graph from the /dep_graph endpoint and renders it using
// Cytoscape.js. Layout is computed manually (no auto-layout, no
// cytoscape compound parents) so that positions are a deterministic
// function of the "expanded set" of nodes. The layout:
//
//   - The "target-level" DAG (target nodes connected by target-target
//     edges) is laid out via a hidden dagre instance to get stable
//     top-level positions for every target.
//   - For each *expanded* target or group node, child nodes
//     (sub-groups and path leaves) are placed at fixed positions
//     inside the parent's rectangle using a wrapping grid.
//   - Targets are then iteratively pushed apart so their (resized)
//     bounding boxes do not overlap.
//
// Because every node is a regular (non-compound) cytoscape node and
// every node's position is set explicitly from the layout function,
// the rendered layout depends only on the set of expanded ids -- not
// on the order of expand/collapse operations.
//
// - target->target edges use taxi-style routing and are always drawn.
// - path->path (dependencies_built) edges are hidden by default; they
//   appear only when the cursor is over a path node that is the
//   *source* of those edges.
// - Node dragging is disabled (grabify is turned off on all nodes).
// - The toolbar provides Refresh, Fit, Zoom In, Zoom Out, Reset.
//
// Cytoscape is loaded from a CDN on demand so we do not vendor it.

(function() {
    const CYTOSCAPE_URL = 'https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js';
    const DAGRE_URL = 'https://unpkg.com/dagre@0.8.5/dist/dagre.min.js';
    const CYTOSCAPE_DAGRE_URL = 'https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js';

    // Layout tuning constants.
    const LEAF_W = 160;          // width of path leaf / collapsed placeholder
    const LEAF_H = 32;           // height of same
    const PAD_X = 18;            // horizontal padding inside a container
    const PAD_TOP = 26;          // top padding (leaves room for label)
    const PAD_BOTTOM = 16;       // bottom padding
    const SIBLING_GAP_X = 14;    // gap between siblings in a row
    const SIBLING_GAP_Y = 12;    // gap between rows of siblings
    const TARGET_MARGIN = 40;    // min separation between target containers
    const TARGET_NODE_SEP = 80;  // dagre nodeSep for the top-level target DAG
    const TARGET_RANK_SEP = 120; // dagre rankSep for the top-level target DAG

    let cyInstance = null;
    let containerEl = null;
    let loadingPromise = null;

    // The set of node ids (cytoscape ids) that are currently "expanded".
    // A target or internal-group node not in this set is collapsed
    // (rendered as a single small leaf placeholder; its descendants are
    // not present in the graph at all).
    let expandedIds = new Set();

    let lastGraph = null;
    let hierarchy = null;

    // parentMap is used to resolve edges whose endpoint is inside a
    // collapsed container to the nearest visible ancestor.
    let parentMap = new Map();          // cyId -> parent cyId (or null)
    let knownTargetIds = new Set();
    let knownPathIds = new Set();

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
            t.root = {
                cyId: groupCyId(t.id, []),
                label: '',
                isRoot: true,
                children: [],
                paths: [],
                varNames: t.varNames,
                targetId: t.id,
                chain: [],
            };
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
                    child = {
                        cyId: groupCyId(t.id, chain),
                        label: `${varName}=${val}`,
                        isRoot: false,
                        children: [],
                        paths: [],
                        varNames: t.varNames,
                        targetId: t.id,
                        chain: chain.slice(),
                    };
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

    // ---------- Layout ----------
    //
    // The layout functions return a plan object:
    //   {
    //     width, height,                              // bounding box size
    //     place(cx, cy, out, depth)                   // emits placements
    //   }
    // where `out` is an array of placement records:
    //   { cyId, x, y, w, h, kind, label, depth, data }
    // kind in {'target', 'group', 'path'}.
    //
    // The container (target / group) itself is always emitted at its own
    // center; descendants are emitted at their own centers.

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
        const expanded = expandedIds.has(group.cyId);
        const hasChildren = group.children.length > 0 || group.paths.length > 0;

        if (!expanded || !hasChildren) {
            // Collapsed (or empty) group: small leaf placeholder.
            return {
                width: LEAF_W,
                height: LEAF_H,
                place(cx, cy, out) {
                    out.push({
                        cyId: group.cyId,
                        x: cx, y: cy,
                        w: LEAF_W, h: LEAF_H,
                        kind: 'group',
                        label: group.label,
                        depth,
                        collapsed: true,
                        expandable: hasChildren,
                    });
                },
            };
        }

        // Expanded: gather child layouts (sub-groups first, then paths).
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
                // Emit this container.
                out.push({
                    cyId: group.cyId,
                    x: cx, y: cy,
                    w: width, h: height,
                    kind: 'group',
                    label: group.label,
                    depth,
                    collapsed: false,
                    expandable: true,
                });
                // Lay out children inside.
                placeGrid(grid, cx, cy, width, height, out);
            },
        };
    }

    function layoutTarget(t) {
        const expanded = expandedIds.has(t.cyId);
        const rootHasChildren =
            t.root.children.length > 0 || t.root.paths.length > 0;

        if (!expanded || !rootHasChildren) {
            return {
                width: LEAF_W,
                height: LEAF_H,
                place(cx, cy, out) {
                    out.push({
                        cyId: t.cyId,
                        x: cx, y: cy,
                        w: LEAF_W, h: LEAF_H,
                        kind: 'target',
                        label: t.id,
                        depth: 0,
                        collapsed: true,
                        expandable: rootHasChildren,
                    });
                },
            };
        }

        // Expanded target: the root group's children attach directly to
        // the target container (we skip drawing the root group as its
        // own rectangle to avoid an extra nesting level).
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
                });
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
            + SIBLING_GAP_X * (colWidths.length - 1);
        const innerH = rowHeights.reduce((a, b) => a + b, 0)
            + SIBLING_GAP_Y * (rows.length - 1);
        return { rows, rowHeights, colWidths, innerW, innerH };
    }

    function placeGrid(grid, cx, cy, width, height, out) {
        // Inner area is offset from container center: leaves PAD_TOP at
        // the top for the label, PAD_BOTTOM at the bottom, PAD_X on each
        // side.
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

    // ---------- Target-level layout (dagre on targets only) ----------

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
            const layout = tmpCy.layout({
                name: 'dagre',
                rankDir: 'TB',
                nodeSep: TARGET_NODE_SEP,
                rankSep: TARGET_RANK_SEP,
            });
            layout.run();
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

    // Iteratively push apart any two target bounding boxes that overlap.
    // Result depends only on (centers, boxes), so the final layout is a
    // pure function of the expanded set.
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

    // ---------- Element construction & application ----------

    function endpointTypeFor(id, kind, role) {
        // role is 'source' or 'target'
        const inT = knownTargetIds.has(id);
        const inP = knownPathIds.has(id);
        const preferPath = (kind === 'dependencies_built');
        if (inT && inP) return preferPath ? 'path' : 'target';
        if (inT) return 'target';
        if (inP) return 'path';
        return preferPath ? 'path' : 'target';
    }

    function buildElementsAndPositions() {
        // 1) Compute target-level centers (pure function of lastGraph).
        const baseCenters = computeTargetCenters();

        // 2) Compute each target's plan and bounding box.
        const targetPlans = new Map();
        const targetBoxes = new Map();
        for (const t of hierarchy.targets) {
            const plan = layoutTarget(t);
            targetPlans.set(t.cyId, plan);
            targetBoxes.set(t.cyId, { width: plan.width, height: plan.height });
        }

        // 3) Separate overlapping target boxes.
        const centers = new Map(baseCenters);
        // Ensure every target has a center (in case dagre missed one).
        for (const t of hierarchy.targets) {
            if (!centers.has(t.cyId)) {
                centers.set(t.cyId, { x: 0, y: 0 });
            }
        }
        separateBoxes(centers, targetBoxes);

        // 4) Emit placements for every visible node.
        const placements = [];
        for (const t of hierarchy.targets) {
            const c = centers.get(t.cyId);
            targetPlans.get(t.cyId).place(c.x, c.y, placements);
        }

        // Build a quick lookup of visible cyIds.
        const visibleIds = new Set(placements.map(p => p.cyId));

        // 5) Build cytoscape elements. Containers first (so they render
        // below leaves), then leaves on top. Elements added to cytoscape
        // in this order get lower z-index by default; we also set
        // explicit z-index based on depth.
        const sorted = placements.slice().sort((a, b) => {
            // Containers (kind == target/group with !collapsed) before
            // leaves. Among containers, shallower depth first.
            const aContainer = (a.kind === 'target' || a.kind === 'group')
                             && !a.collapsed;
            const bContainer = (b.kind === 'target' || b.kind === 'group')
                             && !b.collapsed;
            if (aContainer !== bContainer) return aContainer ? -1 : 1;
            return a.depth - b.depth;
        });

        const elements = [];
        for (const p of sorted) {
            const cls = nodeClasses(p);
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
                    zIndexValue:
                        p.kind === 'path' ? 1000
                        : (p.collapsed ? 800 : 100 + p.depth * 10),
                },
                position: { x: p.x, y: p.y },
                classes: cls,
                grabbable: false,
                selectable: true,
            });
        }

        // 6) Edges. Redirect endpoints inside collapsed containers to
        // the nearest visible ancestor.
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
            const sType = endpointTypeFor(edge.source, kind, 'source');
            const tType = endpointTypeFor(edge.target, kind, 'target');
            const sOrig = sType === 'target'
                ? targetCyId(edge.source) : pathCyId(edge.source);
            const tOrig = tType === 'target'
                ? targetCyId(edge.target) : pathCyId(edge.target);
            const sCy = resolveVisible(sOrig);
            const tCy = resolveVisible(tOrig);
            if (!sCy || !tCy) continue;
            if (sCy === tCy) continue;

            // Deduplicate -- after retargeting, many path->path edges
            // can collapse to the same target->target endpoints.
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

        return { elements, placements };
    }

    function nodeClasses(p) {
        const parts = [];
        if (p.kind === 'target') {
            parts.push('node-target');
            parts.push(p.collapsed ? 'collapsed' : 'expanded');
        } else if (p.kind === 'group') {
            parts.push('node-group');
            parts.push(p.collapsed ? 'collapsed' : 'expanded');
            if (p.expandable) parts.push('expandable');
        } else if (p.kind === 'path') {
            parts.push('node-path');
            if (p.state) parts.push(`state-${p.state}`);
        }
        return parts.join(' ');
    }

    // ---------- Cytoscape style ----------

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
                    'text-halign': 'center',
                    'text-margin-y': 4,
                    'font-size': 11,
                    'font-weight': 'bold',
                    'color': '#2c3e64',
                    'z-index': 'data(zIndexValue)',
                    'z-compound-depth': 'bottom',
                },
            },
            {
                selector: 'node.node-target.collapsed',
                style: {
                    'background-color': '#e8eefb',
                    'background-opacity': 1,
                    'border-style': 'solid',
                    'text-valign': 'center',
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
                    'text-halign': 'center',
                    'text-margin-y': 4,
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
            // Edges -- default.
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
            // path->path edges: hidden by default, revealed on hover.
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

    // ---------- Rendering ----------

    async function fetchGraph() {
        const response = await fetch('/dep_graph');
        if (!response.ok) {
            throw new Error(`/dep_graph returned ${response.status}`);
        }
        return response.json();
    }

    function rebuildAndRender() {
        if (!cyInstance) return;
        const { elements } = buildElementsAndPositions();
        cyInstance.elements().remove();
        cyInstance.add(elements);
        // Make sure positions stick (cytoscape can recompute things
        // after add; we re-apply explicitly from the placements).
        wireInteractionHandlers();
    }

    function wireInteractionHandlers() {
        cyInstance.off('tap', 'node');
        cyInstance.on('tap', 'node', evt => {
            const node = evt.target;
            const t = node.data('nodeType');
            if (t === 'target') {
                toggleExpand(node.id());
            } else if (t === 'group' && node.data('expandable')) {
                toggleExpand(node.id());
            }
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

    function toggleExpand(cyId) {
        if (expandedIds.has(cyId)) {
            collapseRecursive(cyId);
        } else {
            expandedIds.add(cyId);
        }
        rebuildAndRender();
    }

    function collapseRecursive(cyId) {
        expandedIds.delete(cyId);
        for (const t of hierarchy.targets) {
            if (t.cyId === cyId) {
                collapseGroupDescendants(t.root);
                return;
            }
            const g = findGroupByCyId(t.root, cyId);
            if (g) {
                collapseGroupDescendants(g);
                return;
            }
        }
    }

    function findGroupByCyId(group, cyId) {
        if (group.cyId === cyId && !group.isRoot) return group;
        for (const sub of group.children) {
            const r = findGroupByCyId(sub, cyId);
            if (r) return r;
        }
        return null;
    }

    function collapseGroupDescendants(group) {
        for (const sub of group.children) {
            expandedIds.delete(sub.cyId);
            collapseGroupDescendants(sub);
        }
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
                // Disable node dragging globally.
                autoungrabify: true,
                // Allow box-selection? Not needed here.
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
                <span class="graph-status"></span>
            </div>
            <div class="graph-canvas"></div>
        `;
        container.appendChild(containerEl);

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
