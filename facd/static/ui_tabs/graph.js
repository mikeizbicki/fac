// graph.js
//
// Renders the build system dependency graph in a tab.
//
// Fetches the graph from the /dep_graph endpoint and renders it using
// Cytoscape.js with the dagre layout extension. Target nodes act as
// compound (parent) nodes that visually contain their corresponding
// path nodes. Different edge "kind" values are styled distinctly.
//
// The Cytoscape and dagre libraries are loaded from a CDN on demand
// so we do not need to vendor them into static/external.

(function() {
    const CYTOSCAPE_URL = 'https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js';
    const DAGRE_URL = 'https://unpkg.com/dagre@0.8.5/dist/dagre.min.js';
    const CYTOSCAPE_DAGRE_URL = 'https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js';

    let cyInstance = null;
    let containerEl = null;
    let loadingPromise = null;

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

    // Because both target and path nodes can share the same id
    // (e.g. "outline.json" exists as both a target and a path), we
    // namespace cytoscape ids by type.
    function cyId(type, id) {
        return `${type}::${id}`;
    }

    // Resolve an edge endpoint id to an actual existing node type.
    // The /dep_graph endpoint's edge "kind" is not always a reliable
    // indicator of the endpoint types (e.g. "dependencies_built" edges
    // can connect path nodes even though "kind" does not say so).
    // We therefore disambiguate based on which nodes actually exist,
    // using the edge kind only as a hint when both forms exist.
    function resolveEndpoint(id, preferredType, targetIds, pathIds) {
        const inTargets = targetIds.has(id);
        const inPaths = pathIds.has(id);
        if (inTargets && inPaths) {
            return preferredType === 'path' ? 'path' : 'target';
        }
        if (inTargets) return 'target';
        if (inPaths) return 'path';
        // Fallback - return the preferred type so cytoscape will throw
        // a clear error if the data is genuinely inconsistent.
        return preferredType;
    }

    function preferredTypesForKind(kind) {
        // Returns [sourcePref, targetPref]. "dependencies_built" edges
        // describe path-level build state so prefer path nodes when
        // both exist.
        switch (kind) {
            case 'path-path': return ['path', 'path'];
            case 'path-target': return ['path', 'target'];
            case 'target-path': return ['target', 'path'];
            case 'target-target': return ['target', 'target'];
            case 'dependencies_built': return ['path', 'path'];
            default: return ['target', 'target'];
        }
    }

    function buildElements(graph) {
        const elements = [];
        const targetIds = new Set();
        const pathIds = new Set();

        for (const node of graph.nodes || []) {
            if (node.type === 'target') {
                targetIds.add(node.id);
            } else if (node.type === 'path') {
                pathIds.add(node.id);
            }
        }

        for (const node of graph.nodes || []) {
            const data = {
                id: cyId(node.type, node.id),
                label: node.id,
                nodeType: node.type,
                origId: node.id,
                state: (node.data && node.data.state) || null,
                mime: (node.data && node.data['mime-type']) || null,
            };
            if (node.parent && targetIds.has(node.parent)) {
                data.parent = cyId('target', node.parent);
            }
            elements.push({
                group: 'nodes',
                data,
                classes: `node-${node.type}` + (data.state ? ` state-${data.state}` : ''),
            });
        }

        for (const edge of graph.edges || []) {
            const kind = edge.kind || '';
            const [srcPref, tgtPref] = preferredTypesForKind(kind);
            const srcType = resolveEndpoint(edge.source, srcPref, targetIds, pathIds);
            const tgtType = resolveEndpoint(edge.target, tgtPref, targetIds, pathIds);
            elements.push({
                group: 'edges',
                data: {
                    source: cyId(srcType, edge.source),
                    target: cyId(tgtType, edge.target),
                    kind: kind,
                },
                classes: `edge-${kind}`,
            });
        }

        return elements;
    }

    function getStyle() {
        return [
            {
                selector: 'node.node-target',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': '#f5f7fb',
                    'background-opacity': 0.6,
                    'border-color': '#5a7fb8',
                    'border-width': 2,
                    'border-style': 'dashed',
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'center',
                    'font-size': 11,
                    'font-weight': 'bold',
                    'color': '#2c3e64',
                    'padding': '16px',
                    'compound-sizing-wrt-labels': 'include',
                },
            },
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
                    'width': 'label',
                    'height': 'label',
                    'padding': '8px',
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
            {
                selector: 'edge',
                style: {
                    'curve-style': 'bezier',
                    'target-arrow-shape': 'triangle',
                    'width': 1.5,
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'arrow-scale': 0.9,
                },
            },
            {
                selector: 'edge.edge-target-target',
                style: { 'line-color': '#5a7fb8', 'target-arrow-color': '#5a7fb8' },
            },
            {
                selector: 'edge.edge-path-path',
                style: { 'line-color': '#444', 'target-arrow-color': '#444' },
            },
            {
                selector: 'edge.edge-path-target',
                style: {
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'line-style': 'dashed',
                },
            },
            {
                selector: 'edge.edge-target-path',
                style: {
                    'line-color': '#888',
                    'target-arrow-color': '#888',
                    'line-style': 'dashed',
                },
            },
            {
                selector: 'edge.edge-dependencies_built',
                style: {
                    'line-color': '#2e8b3a',
                    'target-arrow-color': '#2e8b3a',
                    'line-style': 'dotted',
                    'width': 1,
                },
            },
        ];
    }

    async function fetchGraph() {
        const response = await fetch('/dep_graph');
        if (!response.ok) {
            throw new Error(`/dep_graph returned ${response.status}`);
        }
        return response.json();
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
            const elements = buildElements(data);

            if (cyInstance) {
                cyInstance.destroy();
                cyInstance = null;
            }

            cyInstance = window.cytoscape({
                container: graphRoot,
                elements: elements,
                style: getStyle(),
                layout: {
                    name: 'dagre',
                    rankDir: 'TB',
                    nodeSep: 30,
                    rankSep: 60,
                    padding: 20,
                },
                wheelSensitivity: 0.2,
            });

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

        renderGraph();
    }

    function onActivate() {
        // Cytoscape sometimes needs a resize when the container becomes
        // visible after being hidden.
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
