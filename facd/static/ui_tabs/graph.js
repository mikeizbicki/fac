// graph.js
//
// Renders the build system dependency graph in a tab.
//
// Fetches the graph from the /dep_graph endpoint and renders it using
// Cytoscape.js. Unlike a generic dagre layout, this view manually
// computes positions so that:
//   - The "target-level" DAG (target nodes connected by target-target
//     edges) is laid out via dagre to get a stable top-level layout.
//   - Path nodes belonging to a target are grouped hierarchically
//     by the values of their resolved variables (left to right),
//     mirroring the tree structure used in targets.js. The grouping
//     hierarchy is: target -> VAR1=val -> VAR2=val -> ... -> path.
//   - Target nodes and group ("internal") nodes are independently
//     expandable/collapsable. On every expand/collapse toggle the
//     whole layout is recomputed from scratch from the saved
//     "expanded set" so that the final layout depends *only* on
//     which nodes are expanded -- never on the order of operations.
//   - target->target edges use taxi-style routing and are always
//     drawn. path->path (dependencies_built) edges are hidden by
//     default and revealed only when the user hovers over a path
//     node that is the *source* of those edges.
//
// Cytoscape is loaded from a CDN on demand so we do not vendor it.

(function() {
    const CYTOSCAPE_URL = 'https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js';
    const DAGRE_URL = 'https://unpkg.com/dagre@0.8.5/dist/dagre.min.js';
    const CYTOSCAPE_DAGRE_URL = 'https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js';

    // Layout tuning constants.
    const NODE_W = 160;            // standard width for path / group / target nodes
    const NODE_H = 32;             // standard height
    const PAD_X = 24;              // horizontal padding inside a compound
    const PAD_Y = 28;              // vertical padding inside a compound (extra on top for label)
    const SIBLING_GAP_X = 16;      // gap between siblings in a row
    const SIBLING_GAP_Y = 14;      // gap between rows of siblings
    const TARGET_NODE_SEP = 60;    // dagre nodeSep for the top-level target DAG
    const TARGET_RANK_SEP = 100;   // dagre rankSep for the top-level target DAG

    let cyInstance = null;
    let containerEl = null;
    let loadingPromise = null;

    // The set of node ids (cytoscape ids) that are currently "expanded".
    // A target or internal-group node not in this set is collapsed
    // (rendered as a single small placeholder; its descendants are not
    // present in the graph at all). This is the single source of truth
    // for the rendered layout.
    let expandedIds = new Set();

    // The last fetched graph response, kept so we can re-render on
    // expand/collapse without re-fetching.
    let lastGraph = null;

    // Built once per fetched graph: the hierarchy of target -> group ->
    // ... -> path nodes. See buildHierarchy() for shape.
    let hierarchy = null;

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
    //
    // Target and path nodes share id strings, so we namespace them.
    // Group nodes have synthetic ids derived from the target id plus
    // the chain of resolved (variable, value) pairs.

    function targetCyId(id) { return `target::${id}`; }
    function pathCyId(id)   { return `path::${id}`; }
    function groupCyId(targetId, chain) {
        // chain is an array of [varName, value] pairs
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
    //
    // hierarchy = {
    //     targets: ordered array of target nodes, each:
    //         {
    //             id: <target id>,
    //             cyId: <namespaced id>,
    //             data: original node.data,
    //             varNames: [...] left-to-right variables in target pattern,
    //             root: <group node>     // root group; if target has no
    //                                    // variables this still exists
    //                                    // and directly holds path leaves
    //         }
    // }
    //
    // group node = {
    //     cyId,
    //     label,           // "" for the root group; "VAR=value" for inner groups
    //     isRoot,          // true iff this is the top-level group under a target
    //     children: [],    // array of group nodes (next-level variable buckets)
    //     paths: [],       // array of path leaves directly in this group (only
    //                      // populated at the deepest level or for var-less targets)
    //     parentCyId,      // cytoscape id of containing compound (target or group)
    // }
    //
    // path leaf = {
    //     cyId,
    //     id,
    //     data,
    //     parentCyId,
    // }

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
                        root: null, // filled in below
                    };
                    targetOrder.push(node.id);
                }
            } else if (node.type === 'path') {
                pathNodes.push(node);
            }
        }

        // Make sure every target has a root group.
        for (const tId of targetOrder) {
            const t = targetsById[tId];
            t.root = {
                cyId: groupCyId(t.id, []),
                label: '',
                isRoot: true,
                children: [],
                paths: [],
                parentCyId: t.cyId,
                varNames: t.varNames,
                targetId: t.id,
                chain: [],
            };
        }

        for (const pNode of pathNodes) {
            const targetId = pNode.target;
            const t = targetsById[targetId];
            if (!t) {
                // Orphan path; skip (or it could be attached as a root-level node,
                // but the example data always has a corresponding target).
                continue;
            }
            const resolved = (pNode.data && pNode.data.variables_resolved) || {};
            const chain = [];
            let group = t.root;
            for (const varName of t.varNames) {
                const val = resolved[varName];
                if (val === undefined || val === null) break;
                chain.push([varName, val]);
                // Find or create child group at this level.
                let child = group.children.find(c =>
                    c.label === `${varName}=${val}`);
                if (!child) {
                    child = {
                        cyId: groupCyId(t.id, chain),
                        label: `${varName}=${val}`,
                        isRoot: false,
                        children: [],
                        paths: [],
                        parentCyId: group.cyId,
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
                parentCyId: group.cyId,
            });
        }

        return { targets: targetOrder.map(id => targetsById[id]) };
    }

    // ---------- Layout ----------
    //
    // We compute the bounding box (width, height) of each compound
    // depending on whether it is expanded. Then we lay out children in
    // a wrapped grid. Coordinates returned for each leaf/group/target
    // are absolute "center" positions for cytoscape.

    // Returns layout info for a group node:
    //   { width, height, place(cx, cy) -> { positions: Map<cyId, {x,y}> } }
    // If the group's parent is collapsed (caller decides), the caller
    // simply won't include it in the layout at all.
    //
    // For a group that is itself *collapsed*, we render it as a single
    // small placeholder node (cyId of the group) with no children.
    function layoutGroup(group) {
        const expanded = expandedIds.has(group.cyId);
        if (!expanded) {
            // Collapsed group placeholder.
            return {
                width: NODE_W,
                height: NODE_H,
                place(cx, cy) {
                    const positions = new Map();
                    positions.set(group.cyId, { x: cx, y: cy });
                    return { positions };
                },
                isPlaceholder: true,
            };
        }

        // Expanded: gather child layouts.
        // Children are either nested groups or path leaves.
        const childLayouts = [];

        for (const sub of group.children) {
            childLayouts.push({
                kind: 'group',
                ref: sub,
                layout: layoutGroup(sub),
            });
        }
        for (const p of group.paths) {
            childLayouts.push({
                kind: 'path',
                ref: p,
                layout: {
                    width: NODE_W,
                    height: NODE_H,
                    place(cx, cy) {
                        const positions = new Map();
                        positions.set(p.cyId, { x: cx, y: cy });
                        return { positions };
                    },
                    isPlaceholder: true,
                },
            });
        }

        if (childLayouts.length === 0) {
            // Expanded but empty group (rare). Render as a small box.
            return {
                width: NODE_W,
                height: NODE_H,
                place(cx, cy) {
                    const positions = new Map();
                    positions.set(group.cyId, { x: cx, y: cy });
                    return { positions };
                },
            };
        }

        // Arrange children in a wrapping grid. We choose a column count
        // roughly proportional to sqrt(N) so the cluster looks square-ish.
        const n = childLayouts.length;
        const cols = Math.max(1, Math.ceil(Math.sqrt(n)));

        // Compute row metrics.
        const rows = [];
        for (let i = 0; i < n; i += cols) {
            rows.push(childLayouts.slice(i, i + cols));
        }
        const rowHeights = rows.map(row =>
            row.reduce((m, c) => Math.max(m, c.layout.height), 0));
        const colWidths = [];
        for (let c = 0; c < cols; c++) {
            let w = 0;
            for (const row of rows) {
                if (row[c]) w = Math.max(w, row[c].layout.width);
            }
            colWidths.push(w);
        }
        const innerW = colWidths.reduce((a, b) => a + b, 0)
            + SIBLING_GAP_X * (cols - 1);
        const innerH = rowHeights.reduce((a, b) => a + b, 0)
            + SIBLING_GAP_Y * (rows.length - 1);

        const width = innerW + 2 * PAD_X;
        const height = innerH + 2 * PAD_Y;

        return {
            width,
            height,
            place(cx, cy) {
                const positions = new Map();
                // The group node itself is a compound and cytoscape will
                // position it automatically based on its children, but we
                // still record a position for it in case it has no
                // children (handled above).
                const left = cx - width / 2 + PAD_X;
                const top = cy - height / 2 + PAD_Y;
                let yCursor = top;
                for (let r = 0; r < rows.length; r++) {
                    let xCursor = left;
                    const rowH = rowHeights[r];
                    for (let c = 0; c < rows[r].length; c++) {
                        const child = rows[r][c];
                        const colW = colWidths[c];
                        const childCx = xCursor + colW / 2;
                        const childCy = yCursor + rowH / 2;
                        const sub = child.layout.place(childCx, childCy);
                        for (const [k, v] of sub.positions) {
                            positions.set(k, v);
                        }
                        xCursor += colW + SIBLING_GAP_X;
                    }
                    yCursor += rowH + SIBLING_GAP_Y;
                }
                return { positions };
            },
        };
    }

    // Returns layout info for a target node (the target is a compound
    // containing its root group, unless the target itself is collapsed).
    function layoutTarget(t) {
        const expanded = expandedIds.has(t.cyId);
        if (!expanded) {
            return {
                width: NODE_W,
                height: NODE_H,
                place(cx, cy) {
                    const positions = new Map();
                    positions.set(t.cyId, { x: cx, y: cy });
                    return { positions };
                },
                isPlaceholder: true,
            };
        }
        // Expanded: layout its root group as the sole "child" inside.
        const inner = layoutGroup(t.root);
        const width = inner.width + 2 * PAD_X;
        const height = inner.height + 2 * PAD_Y;
        return {
            width,
            height,
            place(cx, cy) {
                // Inner group is centered horizontally; placed below the
                // target's top label area.
                const positions = new Map();
                const innerCy = cy + (PAD_Y / 2); // slight downward bias for label
                const sub = inner.place(cx, innerCy);
                for (const [k, v] of sub.positions) {
                    positions.set(k, v);
                }
                return { positions };
            },
        };
    }

    // ---------- Element construction (cytoscape JSON) ----------

    function buildVisibleElements() {
        const elements = [];
        const visibleNodeIds = new Set();

        for (const t of hierarchy.targets) {
            const tExpanded = expandedIds.has(t.cyId);

            // Always include the target node itself.
            elements.push({
                group: 'nodes',
                data: {
                    id: t.cyId,
                    label: t.id,
                    nodeType: 'target',
                    origId: t.id,
                    collapsed: !tExpanded,
                    expandable: true,
                },
                classes: 'node-target' + (tExpanded ? ' expanded' : ' collapsed'),
            });
            visibleNodeIds.add(t.cyId);

            if (!tExpanded) continue;

            // Recurse into groups.
            addGroupElements(t.root, t.cyId, elements, visibleNodeIds);
        }

        // Edges: only include those whose endpoints are both visible
        // (i.e. not hidden inside a collapsed compound). For collapsed
        // targets / groups, redirect endpoints to the nearest visible
        // ancestor placeholder.
        const ancestorCache = new Map(); // origCyId -> visible cyId
        const resolveVisible = (cyId) => {
            if (visibleNodeIds.has(cyId)) return cyId;
            if (ancestorCache.has(cyId)) return ancestorCache.get(cyId);
            // Walk up the hierarchy via parentMap.
            let cur = cyId;
            while (cur && !visibleNodeIds.has(cur)) {
                cur = parentMap.get(cur) || null;
            }
            ancestorCache.set(cyId, cur);
            return cur;
        };

        for (const edge of lastGraph.edges || []) {
            const kind = edge.kind || '';
            const isPathPath = (kind === 'dependencies_built');
            // Determine source / target cyIds. We disambiguate using
            // node existence.
            const [srcType, tgtType] = endpointTypesForEdge(edge);
            const srcCyOrig = srcType === 'target'
                ? targetCyId(edge.source) : pathCyId(edge.source);
            const tgtCyOrig = tgtType === 'target'
                ? targetCyId(edge.target) : pathCyId(edge.target);
            const srcCy = resolveVisible(srcCyOrig);
            const tgtCy = resolveVisible(tgtCyOrig);
            if (!srcCy || !tgtCy) continue;
            if (srcCy === tgtCy) continue; // collapsed into same node

            elements.push({
                group: 'edges',
                data: {
                    source: srcCy,
                    target: tgtCy,
                    kind: kind,
                    origSource: edge.source,
                    origTarget: edge.target,
                    isPathPath: isPathPath,
                },
                classes: `edge-${kind}` + (isPathPath ? ' edge-path-path-hidden' : ''),
            });
        }

        return elements;
    }

    // parentMap and endpointTypesForEdge depend on the current hierarchy
    // and known node existence. We build them per render.
    let parentMap = new Map();          // cyId -> parent cyId (or null)
    let knownTargetIds = new Set();
    let knownPathIds = new Set();

    function addGroupElements(group, parentCyId, elements, visibleNodeIds) {
        const gExpanded = expandedIds.has(group.cyId);
        const hasChildren = group.children.length > 0 || group.paths.length > 0;

        // The root group of a target is "invisible structurally": instead
        // of a wrapping compound for it, we attach its children directly
        // to the target. This keeps the target's label as the visible
        // group label and avoids an extra nesting level.
        if (group.isRoot) {
            if (!hasChildren) return;
            // Even root groups can have nested variable buckets. Always
            // expand into the target (the target's own collapsed state
            // already gates this).
            for (const sub of group.children) {
                addGroupElements(sub, parentCyId, elements, visibleNodeIds);
            }
            for (const p of group.paths) {
                elements.push({
                    group: 'nodes',
                    data: {
                        id: p.cyId,
                        label: p.id,
                        nodeType: 'path',
                        origId: p.id,
                        state: (p.data && p.data.state) || null,
                        parent: parentCyId,
                    },
                    classes: 'node-path'
                        + (p.data && p.data.state ? ` state-${p.data.state}` : ''),
                });
                visibleNodeIds.add(p.cyId);
            }
            return;
        }

        // Non-root group: this is a "VAR=value" cluster node.
        if (!gExpanded || !hasChildren) {
            // Render as a simple placeholder node (no compound).
            elements.push({
                group: 'nodes',
                data: {
                    id: group.cyId,
                    label: group.label,
                    nodeType: 'group',
                    parent: parentCyId,
                    collapsed: true,
                    expandable: hasChildren,
                },
                classes: 'node-group collapsed'
                    + (hasChildren ? ' expandable' : ' leaf'),
            });
            visibleNodeIds.add(group.cyId);
            return;
        }

        // Expanded group: render as a compound containing children.
        elements.push({
            group: 'nodes',
            data: {
                id: group.cyId,
                label: group.label,
                nodeType: 'group',
                parent: parentCyId,
                collapsed: false,
                expandable: true,
            },
            classes: 'node-group expanded expandable',
        });
        visibleNodeIds.add(group.cyId);

        for (const sub of group.children) {
            addGroupElements(sub, group.cyId, elements, visibleNodeIds);
        }
        for (const p of group.paths) {
            elements.push({
                group: 'nodes',
                data: {
                    id: p.cyId,
                    label: p.id,
                    nodeType: 'path',
                    origId: p.id,
                    state: (p.data && p.data.state) || null,
                    parent: group.cyId,
                },
                classes: 'node-path'
                    + (p.data && p.data.state ? ` state-${p.data.state}` : ''),
            });
            visibleNodeIds.add(p.cyId);
        }
    }

    function endpointTypesForEdge(edge) {
        // Decide whether each endpoint refers to a target or a path node.
        const sInT = knownTargetIds.has(edge.source);
        const sInP = knownPathIds.has(edge.source);
        const tInT = knownTargetIds.has(edge.target);
        const tInP = knownPathIds.has(edge.target);
        const kind = edge.kind || '';
        const preferPath = (kind === 'dependencies_built');

        function pick(inT, inP) {
            if (inT && inP) return preferPath ? 'path' : 'target';
            if (inT) return 'target';
            if (inP) return 'path';
            return preferPath ? 'path' : 'target';
        }
        return [pick(sInT, sInP), pick(tInT, tInP)];
    }

    // Build the parentMap for the full hierarchy (so we can resolve
    // collapsed-into-ancestor for edges).
    function buildParentMap() {
        parentMap = new Map();
        for (const t of hierarchy.targets) {
            parentMap.set(t.cyId, null);
            // Root group's children attach to the target.
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

    // ---------- Cytoscape style ----------

    function getStyle() {
        return [
            // Target compound nodes.
            {
                selector: 'node.node-target',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': '#f5f7fb',
                    'background-opacity': 0.55,
                    'border-color': '#5a7fb8',
                    'border-width': 2,
                    'border-style': 'dashed',
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'center',
                    'text-margin-y': -4,
                    'font-size': 11,
                    'font-weight': 'bold',
                    'color': '#2c3e64',
                    'padding': '14px',
                    'compound-sizing-wrt-labels': 'include',
                },
            },
            {
                selector: 'node.node-target.collapsed',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': '#e8eefb',
                    'background-opacity': 1,
                    'border-style': 'solid',
                    'width': NODE_W,
                    'height': NODE_H,
                    'text-valign': 'center',
                    'text-margin-y': 0,
                    'padding': '6px',
                },
            },
            // Group (internal) nodes.
            {
                selector: 'node.node-group',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': '#fbf6ea',
                    'background-opacity': 0.7,
                    'border-color': '#b08a00',
                    'border-width': 1,
                    'border-style': 'dotted',
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'center',
                    'text-margin-y': -4,
                    'font-size': 10,
                    'color': '#6b5400',
                    'padding': '10px',
                },
            },
            {
                selector: 'node.node-group.collapsed',
                style: {
                    'background-color': '#fff4cc',
                    'background-opacity': 1,
                    'border-style': 'solid',
                    'width': NODE_W,
                    'height': NODE_H,
                    'text-valign': 'center',
                    'text-margin-y': 0,
                    'padding': '4px',
                },
            },
            // Path leaf nodes.
            {
                selector: 'node.node-path',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': '#ffffff',
                    'border-color': '#888',
                    'border-width': 1,
                    'label': 'data(label)',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': 10,
                    'color': '#222',
                    'width': NODE_W,
                    'height': NODE_H,
                    'padding': '4px',
                    'text-wrap': 'ellipsis',
                    'text-max-width': NODE_W - 12,
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
                    'taxi-turn': 24,
                    'taxi-turn-min-distance': 8,
                    'target-arrow-shape': 'triangle',
                    'width': 1.5,
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'arrow-scale': 0.9,
                },
            },
            {
                selector: 'edge.edge-target-target',
                style: {
                    'curve-style': 'taxi',
                    'line-color': '#5a7fb8',
                    'target-arrow-color': '#5a7fb8',
                    'width': 2,
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

    function computeAndApplyLayout() {
        // Step 1: lay out target-level DAG with dagre on a temporary
        // graph that only contains target nodes and target-target edges.
        // This determines each target's center position.
        const targetEls = [];
        for (const t of hierarchy.targets) {
            targetEls.push({
                group: 'nodes',
                data: { id: t.cyId },
            });
        }
        for (const edge of lastGraph.edges || []) {
            if (edge.kind !== 'target-target') continue;
            const sId = targetCyId(edge.source);
            const tId = targetCyId(edge.target);
            targetEls.push({
                group: 'edges',
                data: { id: `${sId}->${tId}`, source: sId, target: tId },
            });
        }

        // Use a hidden cytoscape instance just to run dagre. This avoids
        // having to manage layout on the live instance with compounds.
        const tmpDiv = document.createElement('div');
        tmpDiv.style.position = 'absolute';
        tmpDiv.style.width = '1000px';
        tmpDiv.style.height = '1000px';
        tmpDiv.style.left = '-10000px';
        tmpDiv.style.top = '-10000px';
        document.body.appendChild(tmpDiv);

        const targetCenters = new Map();
        try {
            const tmpCy = window.cytoscape({
                container: tmpDiv,
                elements: targetEls,
                style: [],
                headless: false,
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
                targetCenters.set(n.id(), { x: pos.x, y: pos.y });
            });
            tmpCy.destroy();
        } finally {
            tmpDiv.remove();
        }

        // Step 2: compute each target's required bounding box (based on
        // expansion state) and shift target positions outward so that no
        // two target boxes overlap. We do this by performing a simple
        // iterative separation along x and y axes.
        const targetBoxes = new Map(); // tCyId -> { w, h, layout }
        for (const t of hierarchy.targets) {
            const tl = layoutTarget(t);
            targetBoxes.set(t.cyId, tl);
        }

        // Separate overlapping target boxes by translating them.
        const centers = new Map(targetCenters);
        separateBoxes(centers, targetBoxes);

        // Step 3: compute final positions for every visible leaf node by
        // calling each target's layout.place() at its center.
        const allPositions = new Map();
        for (const t of hierarchy.targets) {
            const center = centers.get(t.cyId);
            if (!center) continue;
            const box = targetBoxes.get(t.cyId);
            if (box.isPlaceholder) {
                allPositions.set(t.cyId, { x: center.x, y: center.y });
            } else {
                const placed = box.place(center.x, center.y);
                for (const [k, v] of placed.positions) {
                    allPositions.set(k, v);
                }
            }
        }

        // Apply positions to cytoscape. Only leaf nodes need explicit
        // positions; compound nodes auto-fit to their children.
        cyInstance.batch(() => {
            cyInstance.nodes().forEach(n => {
                const pos = allPositions.get(n.id());
                if (pos && n.isChildless()) {
                    n.position(pos);
                } else if (pos && !n.isParent()) {
                    // collapsed compound rendered as placeholder
                    n.position(pos);
                }
            });
        });
    }

    // Iteratively push apart any two target bounding boxes that overlap.
    // We keep doing passes until no overlaps remain (or a pass cap is
    // hit). For each overlapping pair, we shift them apart along the
    // axis with the smaller required separation. Because we ALWAYS
    // recompute the layout from scratch from the dagre output + the
    // expandedIds set, the result depends only on those inputs.
    function separateBoxes(centers, boxes) {
        const MARGIN = 30;
        const ids = Array.from(centers.keys());
        // Iterate a bounded number of times; for typical graphs this
        // converges quickly.
        const MAX_PASSES = 200;
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
                    const overlapX = (halfWA + halfWB + MARGIN) - Math.abs(dx);
                    const overlapY = (halfHA + halfHB + MARGIN) - Math.abs(dy);
                    if (overlapX > 0 && overlapY > 0) {
                        // Push apart along the smaller-overlap axis.
                        if (overlapX < overlapY) {
                            const shift = overlapX / 2 + 0.5;
                            if (dx >= 0) {
                                centers.set(b, { x: cb.x + shift, y: cb.y });
                                centers.set(a, { x: ca.x - shift, y: ca.y });
                            } else {
                                centers.set(b, { x: cb.x - shift, y: cb.y });
                                centers.set(a, { x: ca.x + shift, y: ca.y });
                            }
                        } else {
                            const shift = overlapY / 2 + 0.5;
                            if (dy >= 0) {
                                centers.set(b, { x: cb.x, y: cb.y + shift });
                                centers.set(a, { x: ca.x, y: ca.y - shift });
                            } else {
                                centers.set(b, { x: cb.x, y: cb.y - shift });
                                centers.set(a, { x: ca.x, y: ca.y + shift });
                            }
                        }
                        moved = true;
                    }
                }
            }
            if (!moved) break;
        }
    }

    function rebuildAndRender() {
        if (!cyInstance) return;
        const elements = buildVisibleElements();
        cyInstance.elements().remove();
        cyInstance.add(elements);
        wireInteractionHandlers();
        computeAndApplyLayout();
    }

    function wireInteractionHandlers() {
        // Click handler for expand/collapse on target and group nodes.
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

        // Path hover: reveal outgoing dependencies_built edges (only
        // edges where source = this path).
        cyInstance.off('mouseover', 'node.node-path');
        cyInstance.off('mouseout', 'node.node-path');
        cyInstance.on('mouseover', 'node.node-path', evt => {
            const id = evt.target.id();
            cyInstance.edges('.edge-dependencies_built').forEach(e => {
                if (e.data('source') === id) e.addClass('reveal');
            });
        });
        cyInstance.on('mouseout', 'node.node-path', evt => {
            cyInstance.edges('.edge-dependencies_built.reveal')
                .removeClass('reveal');
        });
    }

    function toggleExpand(cyId) {
        if (expandedIds.has(cyId)) {
            // Collapse: also collapse all descendants so that re-expanding
            // just this node behaves deterministically.
            collapseRecursive(cyId);
        } else {
            expandedIds.add(cyId);
        }
        rebuildAndRender();
    }

    function collapseRecursive(cyId) {
        // Remove this id and any descendant ids from expandedIds. We
        // walk the hierarchy to find descendants.
        expandedIds.delete(cyId);
        // Find the corresponding hierarchy node.
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

            // Default: everything collapsed.
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
                // We do our own layout, so don't auto-layout.
                layout: { name: 'preset' },
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
        // Render position of viewport center:
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
