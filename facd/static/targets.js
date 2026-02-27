// targets.js
//
// This file manages a hierarchical tree view of build targets and file paths.
// It fetches target definitions from /list_targets and monitors file changes
// via Server-Sent Events from /monitor_files. The tree displays both targets
// (build recipes with potential variables like $CHAPTER) and paths (actual
// files generated from those targets). Nodes are expandable/collapsible,
// with all nodes expanded by default.

let targets = {};
let treeRoot = {};
let targetOrder = [];

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

        if (child._isTarget) {
            div.classList.add('target');
            div.classList.add('leaf');
        } else if (child._isPath) {
            div.classList.add('path');
            div.classList.add('leaf');
        } else if (child._isIntermediate) {
            div.classList.add('intermediate');
        }

        if (child._expanded) {
            div.classList.add('expanded');
        }

        const header = document.createElement('div');
        header.className = 'tree-header';
        header.addEventListener('click', () => {
            const currentPath = [...pathParts];
            toggleNode(key, currentPath);
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
            const showContent = mimeType.includes('text');

            for (const [metaKey, metaValue] of Object.entries(child._metadata)) {
                if (metaKey === 'content' && !showContent) {
                    continue;
                }
                const metaDiv = document.createElement('div');
                metaDiv.className = `meta-${metaKey}`;
                metaDiv.setAttribute('data-label', metaKey);
                metaDiv.textContent = metaValue;
                metadataContainer.appendChild(metaDiv);
            }
            div.appendChild(metadataContainer);
        }

        // Add build menu for leaf nodes (targets and paths)
        if (child._isTarget || child._isPath) {
            const fullPath = child._fullPath;
            const buildMenu = window.createBuildMenu(child, fullPath, child._isTarget);
            div.appendChild(buildMenu);
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
        const metadata = {
            target: data.target,
            status: data.status,
            'mime-type': data['mime-type'],
            content: data.content
        };
        insertIntoTree(data.path, false, metadata);
        refreshDisplay();
    };
}

loadTargets();
monitorFiles();
