// targets.js
//
// This file manages a hierarchical tree view of build targets and file paths.
// It fetches target definitions from /list_targets and monitors file changes
// via Server-Sent Events from /monitor_files. The tree displays both targets
// (build recipes with potential variables like $CHAPTER) and paths (actual
// files generated from those targets). Nodes are expandable/collapsible,
// with all nodes expanded by default.
//
// Component System API:
// ---------------------
// window.registerComponent(callback) - Register a callback for status changes:
//   callback(nodeElement, status, isNew) called on status updates
//   - isNew=true when a node is first added to the DOM
//   - status values: "fresh", "stale", "building", "queued", "deleted", or initial status
//
// Node elements have data attributes:
//   - data-path: full path of the target/file
//   - data-is-target: "true" if this is a target, absent for paths
//   - data-mime-type: MIME type (paths only)
//   - data-status: current status (paths only)
//   - data-content: file content for text files (paths only)

let targets = {};
let treeRoot = {};
let targetOrder = [];
let knownPaths = new Set();
let nodeElements = {};

let componentCallbacks = [];

window.registerComponent = function(callback) {
    componentCallbacks.push(callback);
};

function insertIntoTree(path, isTarget, metadata = null) {
    const parts = path.split('/');
    let current = treeRoot;

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLeaf = i === parts.length - 1;

        if (!current._children) {
            current._children = {};
        }

        if (isLeaf) {
            const nodeKey = isTarget ? `target:${part}` : `path:${part}`;
            if (!current._children[nodeKey]) {
                current._children[nodeKey] = {
                    _name: part,
                    _isTarget: isTarget,
                    _isPath: !isTarget,
                    _metadata: metadata,
                    _order: isTarget ? targetOrder.indexOf(path) : null,
                    _expanded: true,
                    _fullPath: path
                };
            } else if (!isTarget && metadata) {
                current._children[nodeKey]._metadata = metadata;
            }
        } else {
            if (!current._children[part]) {
                current._children[part] = {
                    _name: part,
                    _isIntermediate: true,
                    _expanded: true
                };
            }
            current = current._children[part];
        }
    }
}

function getOrderKey(key, child) {
    if (child._isTarget && child._order !== null) {
        return String(child._order).padStart(10, '0');
    }
    const name = key.includes(':') ? key.split(':')[1] : key;
    return name;
}

function toggleNode(nodeKey, pathParts) {
    let current = treeRoot;
    for (const part of pathParts) {
        if (current._children && current._children[part]) {
            current = current._children[part];
        } else {
            return;
        }
    }
    if (current._children && current._children[nodeKey]) {
        current._children[nodeKey]._expanded = !current._children[nodeKey]._expanded;
        refreshDisplay();
    }
}

function updateNodeStatus(path, status, isNew) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;

    nodeEl.dataset.status = status;

    if (status === 'deleted') {
        nodeEl.classList.add('fading-out');
        setTimeout(() => {
            removePathFromTree(path);
            delete nodeElements[path];
            knownPaths.delete(path);
            refreshDisplay();
        }, 1500);
    }

    for (const callback of componentCallbacks) {
        callback(nodeEl, status, isNew);
    }
}

function removePathFromTree(path) {
    const parts = path.split('/');
    let current = treeRoot;
    const stack = [{ node: treeRoot, key: null }];

    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        if (current._children && current._children[part]) {
            current = current._children[part];
            stack.push({ node: current, key: part });
        } else {
            return;
        }
    }

    const lastPart = parts[parts.length - 1];
    const nodeKey = `path:${lastPart}`;
    if (current._children && current._children[nodeKey]) {
        delete current._children[nodeKey];
    }

    for (let i = stack.length - 1; i >= 0; i--) {
        const { node, key } = stack[i];
        if (node._children && Object.keys(node._children).length === 0 && node._isIntermediate) {
            if (i > 0) {
                const parent = stack[i - 1].node;
                delete parent._children[key];
            }
        }
    }
}

function renderTree(node, container, pathParts = []) {
    if (!node._children) return;

    const sortedKeys = Object.keys(node._children).sort((a, b) => {
        const childA = node._children[a];
        const childB = node._children[b];
        return getOrderKey(a, childA).localeCompare(getOrderKey(b, childB));
    });

    for (const key of sortedKeys) {
        const child = node._children[key];
        const div = document.createElement('div');
        div.className = 'tree-node';

        div.dataset.path = child._fullPath || '';

        if (child._isTarget) {
            div.classList.add('target', 'leaf');
            div.dataset.isTarget = 'true';
        } else if (child._isPath) {
            div.classList.add('path', 'leaf');
            nodeElements[child._fullPath] = div;
            if (child._metadata) {
                if (child._metadata['mime-type']) {
                    div.dataset.mimeType = child._metadata['mime-type'];
                }
                if (child._metadata.status) {
                    div.dataset.status = child._metadata.status;
                }
                if (child._metadata.content !== undefined) {
                    div.dataset.content = child._metadata.content;
                }
            }
        } else if (child._isIntermediate) {
            div.classList.add('intermediate');
        }

        if (child._expanded) {
            div.classList.add('expanded');
        }

        const header = document.createElement('div');
        header.className = 'tree-header';
        header.addEventListener('click', () => {
            toggleNode(key, [...pathParts]);
        });

        const toggle = document.createElement('button');
        toggle.className = 'tree-toggle';
        toggle.innerHTML = '&#9654;';
        header.appendChild(toggle);

        const label = document.createElement('span');
        label.className = 'tree-label';
        label.textContent = child._name;
        header.appendChild(label);

        div.appendChild(header);

        if (child._isPath && child._metadata) {
            const metadataContainer = document.createElement('div');
            metadataContainer.className = 'metadata';

            const mimeType = child._metadata['mime-type'] || '';
            const showContent = mimeType.startsWith('text/');

            for (const [metaKey, metaValue] of Object.entries(child._metadata)) {
                if (metaKey === 'content') continue;
                const metaDiv = document.createElement('div');
                metaDiv.className = 'meta-info';
                metaDiv.setAttribute('data-label', metaKey);
                metaDiv.textContent = metaValue;
                metadataContainer.appendChild(metaDiv);
            }

            if (showContent && child._metadata.content !== undefined) {
                const contentWrapper = document.createElement('div');
                contentWrapper.className = 'content-wrapper';
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                contentDiv.textContent = child._metadata.content;
                contentWrapper.appendChild(contentDiv);
                metadataContainer.appendChild(contentWrapper);
            }

            div.appendChild(metadataContainer);
        }

        // Notify components about new node
        const status = child._metadata?.status || (child._isTarget ? 'target' : null);
        for (const callback of componentCallbacks) {
            callback(div, status, true);
        }

        if (child._children) {
            const childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            renderTree(child, childContainer, [...pathParts, key]);
            div.appendChild(childContainer);
        }

        container.appendChild(div);
    }
}

function refreshDisplay() {
    const container = document.getElementById('targets-container');
    container.innerHTML = '';
    nodeElements = {};
    renderTree(treeRoot, container);
}

function loadTargets() {
    fetch('/list_targets')
        .then(response => response.json())
        .then(data => {
            targets = data;
            targetOrder = Object.keys(data);
            for (const target of targetOrder) {
                insertIntoTree(target, true);
            }
            refreshDisplay();
        });
}

function monitorFiles() {
    const eventSource = new EventSource('/monitor_files');

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const path = data.path;
        const status = data.status;
        const isNew = !knownPaths.has(path);

        const metadata = {
            target: data.target,
            status: data.status,
            'mime-type': data['mime-type'],
            content: data.content
        };

        if (status === 'deleted') {
            if (knownPaths.has(path)) {
                updateNodeStatus(path, status, false);
            }
        } else {
            insertIntoTree(path, false, metadata);
            knownPaths.add(path);

            if (status === 'fresh') {
                updateNodeStatus(path, status, isNew);
            } else if (status === 'stale' || status === 'building' || status === 'queued') {
                updateNodeStatus(path, status, false);
            }
        }
    };
}

loadTargets();
monitorFiles();
