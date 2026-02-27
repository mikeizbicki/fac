// targets.js
//
// This file manages a hierarchical tree view of build targets and file paths.
// It fetches target definitions from /list_targets and monitors file changes
// via Server-Sent Events from /monitor_files. The tree displays both targets
// (build recipes with potential variables like $CHAPTER) and paths (actual
// files generated from those targets). Nodes are expandable/collapsible,
// with all nodes expanded by default.
//
// Status handling:
// - fresh: shows a flash overlay ("new" or "modified") that fades after 1s
// - deleted: shows a red flash overlay, then fades out and removes the node
// - stale/building/queued: shows a persistent gray overlay with status text
//   and a spinner for building/queued states
//
// File editing:
// - Text files can be edited inline by clicking the edit button
// - Shows a textarea with submit/cancel buttons
// - Submitting shows a spinner overlay until the file update is confirmed
//
// File deletion:
// - Files can be deleted via the delete button in the header menu

let targets = {};
let treeRoot = {};
let targetOrder = [];
let knownPaths = new Set();
let nodeElements = {};
let pendingEdits = new Set();

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

function createStatusOverlay(status, isNew) {
    const overlay = document.createElement('div');
    overlay.className = 'status-overlay';

    const textSpan = document.createElement('span');
    textSpan.className = 'status-overlay-text';

    if (status === 'fresh') {
        overlay.classList.add('flash-overlay');
        textSpan.textContent = isNew ? 'new' : 'modified';
    } else if (status === 'deleted') {
        overlay.classList.add('flash-overlay', 'deleted');
        textSpan.textContent = 'deleted';
    } else if (status === 'stale' || status === 'building' || status === 'queued') {
        overlay.classList.add('persistent-overlay');
        textSpan.textContent = status;

        if (status === 'building' || status === 'queued') {
            const spinner = document.createElement('div');
            spinner.className = 'status-spinner';
            overlay.appendChild(textSpan);
            overlay.appendChild(spinner);
            return overlay;
        }
    }

    overlay.appendChild(textSpan);
    return overlay;
}

function updateNodeStatus(path, status, isNew) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;

    const existingOverlay = nodeEl.querySelector('.status-overlay');
    if (existingOverlay) {
        existingOverlay.remove();
    }

    if (status === 'deleted') {
        const overlay = createStatusOverlay(status, false);
        nodeEl.appendChild(overlay);
        nodeEl.classList.add('fading-out');
        setTimeout(() => {
            removePathFromTree(path);
            delete nodeElements[path];
            knownPaths.delete(path);
            refreshDisplay();
        }, 1500);
    } else if (status === 'fresh') {
        const overlay = createStatusOverlay(status, isNew);
        nodeEl.appendChild(overlay);
        setTimeout(() => {
            overlay.remove();
        }, 1000);

        if (pendingEdits.has(path)) {
            pendingEdits.delete(path);
        }
    } else if (status === 'stale' || status === 'building' || status === 'queued') {
        const overlay = createStatusOverlay(status, false);
        nodeEl.appendChild(overlay);
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

function createHeaderMenu(path, mimeType, isTarget, originalContent) {
    const menu = document.createElement('div');
    menu.className = 'header-menu';

    const isTextFile = mimeType && mimeType.startsWith('text/');

    // Build button
    const buildBtn = document.createElement('button');
    buildBtn.innerHTML = '🔨';
    buildBtn.title = 'Build';
    buildBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (isTarget) {
            window.buildTarget(path, '');
        } else {
            window.buildTarget(path, '');
        }
    });
    menu.appendChild(buildBtn);

    if (!isTarget) {
        if (isTextFile) {
            const editBtn = document.createElement('button');
            editBtn.innerHTML = '✏️';
            editBtn.title = 'Edit';
            editBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const nodeEl = nodeElements[path];
                if (nodeEl) {
                    const contentWrapper = nodeEl.querySelector('.content-wrapper');
                    if (contentWrapper) {
                        startEditing(path, contentWrapper, originalContent);
                    }
                }
            });
            menu.appendChild(editBtn);
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = 'Delete';
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteFile(path);
        });
        menu.appendChild(deleteBtn);
    }

    return menu;
}

function startEditing(path, contentWrapper, originalContent) {
    const contentDiv = contentWrapper.querySelector('.content');
    
    if (!contentDiv) return;

    const textarea = document.createElement('textarea');
    textarea.className = 'content-editor';
    textarea.value = originalContent || '';
    
    const actions = document.createElement('div');
    actions.className = 'content-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'cancel-btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        cancelEditing(path, contentWrapper, originalContent);
    });

    const submitBtn = document.createElement('button');
    submitBtn.className = 'submit-btn';
    submitBtn.textContent = 'Submit';
    submitBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        submitEdit(path, textarea.value, contentWrapper);
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(submitBtn);

    contentDiv.style.display = 'none';
    contentWrapper.appendChild(textarea);
    contentWrapper.appendChild(actions);
    textarea.focus();
}

function cancelEditing(path, contentWrapper, originalContent) {
    const textarea = contentWrapper.querySelector('.content-editor');
    const actions = contentWrapper.querySelector('.content-actions');
    const contentDiv = contentWrapper.querySelector('.content');

    if (textarea) textarea.remove();
    if (actions) actions.remove();
    if (contentDiv) contentDiv.style.display = 'block';
}

function submitEdit(path, newContent, contentWrapper) {
    const textarea = contentWrapper.querySelector('.content-editor');
    const actions = contentWrapper.querySelector('.content-actions');

    if (textarea) textarea.disabled = true;
    if (actions) actions.style.display = 'none';

    const overlay = document.createElement('div');
    overlay.className = 'submitting-overlay';
    const spinner = document.createElement('div');
    spinner.className = 'status-spinner';
    overlay.appendChild(spinner);
    contentWrapper.appendChild(overlay);

    pendingEdits.add(path);

    fetch(`/edit_file/${encodeURIComponent(path)}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ content: newContent })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to edit file');
        }
        return response.json();
    })
    .catch(error => {
        console.error('Error editing file:', error);
        pendingEdits.delete(path);
        overlay.remove();
        if (textarea) textarea.disabled = false;
        if (actions) actions.style.display = 'flex';
        alert('Failed to edit file: ' + error.message);
    });
}

function deleteFile(path) {
    if (!confirm(`Are you sure you want to delete "${path}"?`)) {
        return;
    }

    fetch(`/delete_file/${encodeURIComponent(path)}`, {
        method: 'DELETE'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to delete file');
        }
        return response.json();
    })
    .catch(error => {
        console.error('Error deleting file:', error);
        alert('Failed to delete file: ' + error.message);
    });
}

function createTargetBuildMenu(fullPath) {
    const buildMenu = document.createElement('div');
    buildMenu.className = 'target-build-menu';

    const textarea = document.createElement('textarea');
    textarea.className = 'build-prompt-input';
    textarea.placeholder = 'Enter build prompt (optional)...';
    buildMenu.appendChild(textarea);

    const submitBtn = document.createElement('button');
    submitBtn.className = 'build-submit-btn';
    submitBtn.textContent = 'Build';
    submitBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        window.buildTarget(fullPath, textarea.value);
    });
    buildMenu.appendChild(submitBtn);

    return buildMenu;
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
            nodeElements[child._fullPath] = div;
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

        // Add header menu for paths (with build, edit, delete buttons)
        if (child._isPath && child._metadata) {
            const mimeType = child._metadata['mime-type'] || '';
            const headerMenu = createHeaderMenu(
                child._fullPath,
                mimeType,
                false,
                child._metadata.content
            );
            header.appendChild(headerMenu);
        }

        // Add header menu for targets (with just build button)
        if (child._isTarget) {
            const headerMenu = createHeaderMenu(
                child._fullPath,
                null,
                true,
                null
            );
            header.appendChild(headerMenu);
        }

        div.appendChild(header);

        if (child._isPath && child._metadata) {
            const metadataContainer = document.createElement('div');
            metadataContainer.className = 'metadata';

            const mimeType = child._metadata['mime-type'] || '';
            const showContent = mimeType.startsWith('text/');

            for (const [metaKey, metaValue] of Object.entries(child._metadata)) {
                if (metaKey === 'content') {
                    continue;
                }
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

            const status = child._metadata.status;
            if (status && status !== 'fresh') {
                const overlay = createStatusOverlay(status, false);
                div.appendChild(overlay);
            }
        }

        // Add target build menu (textarea + build button) for targets
        if (child._isTarget) {
            const buildMenu = createTargetBuildMenu(child._fullPath);
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
            
            if (!pendingEdits.has(path)) {
                refreshDisplay();
            }

            if (status === 'fresh') {
                if (pendingEdits.has(path)) {
                    pendingEdits.delete(path);
                    refreshDisplay();
                }
                updateNodeStatus(path, status, isNew);
            } else if (status === 'stale' || status === 'building' || status === 'queued') {
                updateNodeStatus(path, status, false);
            }
        }
    };
}

loadTargets();
monitorFiles();
