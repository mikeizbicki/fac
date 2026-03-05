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
//
// IMPORTANT:
// Coding agents must not change this API without asking for permission.

let targets = {};
let treeRoot = {};
let targetOrder = [];
let knownPaths = new Set();
let nodeElements = {};

let componentCallbacks = [];

// Pending operations queue per path to handle race conditions
let pendingOperations = {};
let processingPaths = new Set();

window.registerComponent = function(callback) {
    componentCallbacks.push(callback);
};

// Extract variable names from a target pattern
function extractVariables(pattern) {
    const regex = /\$([A-Z_][A-Z0-9_]*)/g;
    const vars = [];
    let match;
    while ((match = regex.exec(pattern)) !== null) {
        if (!vars.includes(match[1])) {
            vars.push(match[1]);
        }
    }
    return vars;
}

// Check if a target pattern has variables
function hasVariables(pattern) {
    return /\$[A-Z_][A-Z0-9_]*/.test(pattern);
}

// Convert a target pattern to a regex for matching paths
function targetToRegex(pattern) {
    let regexStr = pattern
        .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        .replace(/\\\$[A-Z_][A-Z0-9_]*/g, '([^/]+)');
    return new RegExp('^' + regexStr + '$');
}

// Extract variable values from a path given a target pattern
function extractVariableValues(pattern, path) {
    const vars = extractVariables(pattern);
    if (vars.length === 0) return null;
    
    const regex = targetToRegex(pattern);
    const match = path.match(regex);
    if (!match) return null;
    
    const values = {};
    for (let i = 0; i < vars.length; i++) {
        values[vars[i]] = match[i + 1];
    }
    return values;
}

// Find which target pattern matches a given path
function findMatchingTarget(path) {
    for (const target of targetOrder) {
        const regex = targetToRegex(target);
        if (regex.test(path)) {
            return target;
        }
    }
    return null;
}

// Get all known variable value combinations for a target pattern
function getKnownVariableCombinations(targetPattern) {
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return [];
    
    const combinations = [];
    for (const path of knownPaths) {
        const values = extractVariableValues(targetPattern, path);
        if (values) {
            // Check if this combination already exists
            const exists = combinations.some(combo => 
                vars.every(v => combo[v] === values[v])
            );
            if (!exists) {
                combinations.push(values);
            }
        }
    }
    return combinations;
}

// Generate all possible paths for a target given known variable combinations
function generatePossiblePaths(targetPattern, combinations) {
    const paths = [];
    for (const combo of combinations) {
        let path = targetPattern;
        for (const [varName, value] of Object.entries(combo)) {
            path = path.replace(new RegExp('\\$' + varName, 'g'), value);
        }
        paths.push(path);
    }
    return paths;
}

// Check if a path exists in knownPaths
function pathExists(path) {
    return knownPaths.has(path);
}

// Get targets that share variables with the given target (same variable scope)
function getRelatedTargets(targetPattern) {
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return [targetPattern];
    
    const related = [];
    for (const target of targetOrder) {
        const targetVars = extractVariables(target);
        // Check if they share at least one variable
        if (vars.some(v => targetVars.includes(v))) {
            related.push(target);
        }
    }
    return related;
}

// Get all variable combinations across related targets
function getAllVariableCombinations(targetPattern) {
    const relatedTargets = getRelatedTargets(targetPattern);
    const allVars = new Set();
    for (const target of relatedTargets) {
        for (const v of extractVariables(target)) {
            allVars.add(v);
        }
    }
    
    const combinations = [];
    for (const target of relatedTargets) {
        for (const combo of getKnownVariableCombinations(target)) {
            const exists = combinations.some(existing => 
                [...allVars].every(v => existing[v] === combo[v])
            );
            if (!exists) {
                combinations.push(combo);
            }
        }
    }
    return combinations;
}

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
                    _expanded: false,
                    _fullPath: path
                };
            } else if (!isTarget && metadata) {
                current._children[nodeKey]._metadata = metadata;
            }
        } else {
            // Check if this is a variable segment in a target
            const isVariableSegment = isTarget && part.includes('$');
            const nodeKey = isVariableSegment ? `targetvar:${part}` : part;
            
            if (!current._children[nodeKey]) {
                current._children[nodeKey] = {
                    _name: part,
                    _isIntermediate: true,
                    _isVariableScope: isVariableSegment,
                    _expanded: true
                };
            }
            current = current._children[nodeKey];
        }
    }
}

function removeFromTree(path, isTarget) {
    const parts = path.split('/');
    let current = treeRoot;
    const stack = [{ node: treeRoot, key: null }];

    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        let found = false;
        if (current._children) {
            // Try exact match first
            if (current._children[part]) {
                current = current._children[part];
                stack.push({ node: current, key: part });
                found = true;
            } else {
                // Try targetvar match
                for (const key of Object.keys(current._children)) {
                    if (key.startsWith('targetvar:') || key === part) {
                        current = current._children[key];
                        stack.push({ node: current, key: key });
                        found = true;
                        break;
                    }
                }
            }
        }
        if (!found) return;
    }

    const lastPart = parts[parts.length - 1];
    const nodeKey = isTarget ? `target:${lastPart}` : `path:${lastPart}`;
    if (current._children && current._children[nodeKey]) {
        delete current._children[nodeKey];
    }

    // Clean up empty intermediate nodes
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

function processNextOperation(path) {
    if (!pendingOperations[path] || pendingOperations[path].length === 0) {
        processingPaths.delete(path);
        delete pendingOperations[path];
        return;
    }

    processingPaths.add(path);
    const operation = pendingOperations[path].shift();
    operation(() => processNextOperation(path));
}

function queueOperation(path, operation) {
    if (!pendingOperations[path]) {
        pendingOperations[path] = [];
    }
    pendingOperations[path].push(operation);

    if (!processingPaths.has(path)) {
        processNextOperation(path);
    }
}

function updateNodeStatus(path, status, isNew) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;

    nodeEl.dataset.status = status;

    for (const callback of componentCallbacks) {
        callback(nodeEl, status, isNew);
    }
}

function handleDeleteOperation(path, onComplete) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) {
        onComplete();
        return;
    }

    nodeEl.dataset.status = 'deleted';

    for (const callback of componentCallbacks) {
        callback(nodeEl, 'deleted', false);
    }

    nodeEl.classList.add('fading-out');
    setTimeout(() => {
        // Check if a newer operation has re-added this path
        if (pendingOperations[path] && pendingOperations[path].length > 0) {
            // There's a pending operation, skip the actual deletion
            nodeEl.classList.remove('fading-out');
            onComplete();
            return;
        }

        removePathFromTree(path);
        delete nodeElements[path];
        knownPaths.delete(path);
        rebuildTree();
        refreshDisplay();
        onComplete();
    }, 1500);
}

function handleCreateOrUpdateOperation(path, metadata, isNew, onComplete) {
    knownPaths.add(path);
    rebuildTree();
    refreshDisplay();
    updateNodeStatus(path, metadata.status, isNew);
    onComplete();
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

// Rebuild the entire tree based on current targets and known paths
function rebuildTree() {
    treeRoot = {};
    
    // For each target, determine what should be displayed
    for (const target of targetOrder) {
        const vars = extractVariables(target);
        
        if (vars.length === 0) {
            // No variables - show target only if path doesn't exist
            if (!pathExists(target)) {
                insertIntoTree(target, true);
            }
        } else {
            // Has variables - need to show target nodes for missing paths
            const combinations = getAllVariableCombinations(target);
            
            for (const combo of combinations) {
                let path = target;
                for (const [varName, value] of Object.entries(combo)) {
                    path = path.replace(new RegExp('\\$' + varName, 'g'), value);
                }
                
                if (!pathExists(path)) {
                    // Insert as a "virtual target" - a target with variables filled in
                    insertIntoTree(path, true, { _isVirtualTarget: true, _sourceTarget: target });
                }
            }
            
            // Also insert the original target pattern for the variable scope form
            insertTargetPattern(target);
        }
    }
    
    // Insert all known paths
    for (const path of knownPaths) {
        const metadata = getPathMetadata(path);
        insertIntoTree(path, false, metadata);
    }
}

// Store metadata for paths
let pathMetadata = {};

function getPathMetadata(path) {
    return pathMetadata[path] || {};
}

function setPathMetadata(path, metadata) {
    pathMetadata[path] = metadata;
}

// Insert a target pattern into the tree (for variable scope forms)
function insertTargetPattern(pattern) {
    const parts = pattern.split('/');
    let current = treeRoot;

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLeaf = i === parts.length - 1;

        if (!current._children) {
            current._children = {};
        }

        const isVariableSegment = part.includes('$');
        
        if (isLeaf) {
            // Don't add leaf target patterns, they're handled by rebuildTree
        } else {
            const nodeKey = isVariableSegment ? `targetvar:${part}` : part;
            
            if (!current._children[nodeKey]) {
                current._children[nodeKey] = {
                    _name: part,
                    _isIntermediate: true,
                    _isVariableScope: isVariableSegment,
                    _targetPattern: pattern,
                    _expanded: true
                };
            } else if (isVariableSegment) {
                current._children[nodeKey]._isVariableScope = true;
                current._children[nodeKey]._targetPattern = pattern;
            }
            current = current._children[nodeKey];
        }
    }
}

function createVariableScopeForm(node, container, pathParts) {
    // Find all variables used in targets under this scope
    const allVars = new Set();
    for (const target of targetOrder) {
        if (target.includes(node._name)) {
            for (const v of extractVariables(target)) {
                allVars.add(v);
            }
        }
    }
    
    if (allVars.size === 0) return;
    
    const formDiv = document.createElement('div');
    formDiv.className = 'variable-scope-form';
    
    const varsContainer = document.createElement('div');
    varsContainer.className = 'variable-inputs';
    
    const inputs = {};
    for (const varName of allVars) {
        const varDiv = document.createElement('div');
        varDiv.className = 'variable-input';
        
        const label = document.createElement('label');
        label.textContent = '$' + varName + ':';
        varDiv.appendChild(label);
        
        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = varName;
        input.dataset.varName = varName;
        inputs[varName] = input;
        varDiv.appendChild(input);
        
        varsContainer.appendChild(varDiv);
    }
    
    formDiv.appendChild(varsContainer);
    
    const promptDiv = document.createElement('div');
    promptDiv.className = 'prompt-input';
    
    const promptLabel = document.createElement('label');
    promptLabel.textContent = 'Prompt (optional):';
    promptDiv.appendChild(promptLabel);
    
    const promptInput = document.createElement('textarea');
    promptInput.placeholder = 'Enter build prompt...';
    promptInput.rows = 2;
    promptDiv.appendChild(promptInput);
    
    formDiv.appendChild(promptDiv);
    
    const buttonsDiv = document.createElement('div');
    buttonsDiv.className = 'form-buttons';
    
    const buildAllBtn = document.createElement('button');
    buildAllBtn.textContent = 'Build All';
    buildAllBtn.addEventListener('click', () => {
        // Reconstruct the path prefix from pathParts, substituting variables
        const pathPrefix = pathParts.map(p => {
            if (p.startsWith('targetvar:')) {
                let segment = p.substring('targetvar:'.length);
                // Substitute variables in this segment
                for (const [varName, input] of Object.entries(inputs)) {
                    const value = input.value.trim();
                    if (value) {
                        segment = segment.replace(new RegExp('\\$' + varName, 'g'), value);
                    }
                }
                return segment;
            }
            return p;
        }).join('/');
        
        const targetPath = pathPrefix + '/**';
        
        const params = new URLSearchParams();
        params.set('target', targetPath);
        if (promptInput.value.trim()) {
            params.set('include_prompt', promptInput.value.trim());
        }
        
        fetch('/add_target?' + params.toString(), {
            method: 'POST'
        })
        .then(response => {
            if (!response.ok) throw new Error('Failed to queue build');
            return response.json();
        })
        .then(() => {
            // Reset form fields
            for (const input of Object.values(inputs)) {
                input.value = '';
            }
            promptInput.value = '';
            
            // Show confirmation message
            const existingConfirmation = buttonsDiv.querySelector('.build-confirmation');
            if (existingConfirmation) {
                existingConfirmation.remove();
            }
            
            const confirmation = document.createElement('span');
            confirmation.className = 'build-confirmation';
            confirmation.textContent = 'Build command sent';
            buttonsDiv.appendChild(confirmation);
            
            // Fade out after 3 seconds
            setTimeout(() => {
                confirmation.classList.add('fading');
                setTimeout(() => {
                    confirmation.remove();
                }, 500);
            }, 3000);
        })
        .catch(error => {
            console.error('Error queuing build:', error);
            alert('Failed to queue build: ' + error.message);
        });
    });
    buttonsDiv.appendChild(buildAllBtn);
    
    formDiv.appendChild(buttonsDiv);
    container.appendChild(formDiv);
}

function getPathPrefix(node) {
    // This is simplified; in practice we'd track the full path
    // For now, return the node name with a trailing slash
    return node._name.replace(/\$[A-Z_][A-Z0-9_]*/g, '**') + '/';
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
            if (child._isVariableScope) {
                div.classList.add('variable-scope');
            }
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

        // Add variable scope form if this is a variable scope node
        if (child._isVariableScope) {
            createVariableScopeForm(child, div, [...pathParts, key]);
        }

        if (child._isPath && child._metadata) {
            const metadataContainer = document.createElement('div');
            metadataContainer.className = 'metadata';

            const mimeType = child._metadata['mime-type'] || '';
            const showContent = mimeType.startsWith('text/');

            for (const [metaKey, metaValue] of Object.entries(child._metadata)) {
                if (metaKey === 'content') continue;
                if (metaKey.startsWith('_')) continue;
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
            rebuildTree();
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

        setPathMetadata(path, metadata);

        if (status === 'deleted') {
            if (knownPaths.has(path)) {
                queueOperation(path, (onComplete) => handleDeleteOperation(path, onComplete));
            }
        } else {
            queueOperation(path, (onComplete) => handleCreateOrUpdateOperation(path, metadata, isNew, onComplete));
        }
    };
}

loadTargets();
monitorFiles();
