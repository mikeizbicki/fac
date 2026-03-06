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

// Get the order index for a target pattern
function getTargetOrderIndex(target) {
    const index = targetOrder.indexOf(target);
    return index >= 0 ? index : targetOrder.length;
}

// Get the order index for a path based on its matching target
function getPathOrderIndex(path) {
    const matchingTarget = findMatchingTarget(path);
    if (matchingTarget) {
        return getTargetOrderIndex(matchingTarget);
    }
    return targetOrder.length;
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

function getOrderKey(key, child) {
    // Use the _order field which is based on target order
    if (child._order !== undefined && child._order !== null) {
        // Pad with zeros for proper string sorting, then append name for stable sort
        const name = key.includes(':') ? key.split(':')[1] : key;
        return String(child._order).padStart(10, '0') + ':' + name;
    }
    // Fallback to name-based sorting for nodes without order
    const name = key.includes(':') ? key.split(':')[1] : key;
    return '9999999999:' + name;
}

function toggleNodeByElement(nodeEl) {
    nodeEl.classList.toggle('expanded');
    
    // Also update the tree data structure to keep it in sync
    const path = nodeEl.dataset.path;
    if (path) {
        const parts = path.split('/');
        let current = treeRoot;
        for (let i = 0; i < parts.length - 1; i++) {
            const part = parts[i];
            if (current._children) {
                // Try direct match first
                if (current._children[part]) {
                    current = current._children[part];
                } else {
                    // Try targetvar match
                    const targetVarKey = Object.keys(current._children).find(k => 
                        k.startsWith('targetvar:') && current._children[k]._name === part
                    );
                    if (targetVarKey) {
                        current = current._children[targetVarKey];
                    }
                }
            }
        }
        const lastPart = parts[parts.length - 1];
        if (current._children) {
            const nodeKey = `path:${lastPart}`;
            if (current._children[nodeKey]) {
                current._children[nodeKey]._expanded = nodeEl.classList.contains('expanded');
            }
            const targetKey = `target:${lastPart}`;
            if (current._children[targetKey]) {
                current._children[targetKey]._expanded = nodeEl.classList.contains('expanded');
            }
        }
    }
}

function toggleIntermediateNode(nodeEl) {
    nodeEl.classList.toggle('expanded');
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

        removeNodeFromDomAndTree(path);
        onComplete();
    }, 1500);
}

function handleCreateOrUpdateOperation(path, metadata, isNew, onComplete) {
    knownPaths.add(path);
    setPathMetadata(path, metadata);
    
    if (isNew) {
        // Insert into tree data structure
        insertPathIntoTree(path, metadata);
        // Insert into DOM
        insertNodeIntoDom(path, metadata);
    } else {
        // Just update the existing node's metadata
        updateExistingNode(path, metadata);
    }
    
    updateNodeStatus(path, metadata.status, isNew);
    onComplete();
}

// Insert a path into the tree data structure
function insertPathIntoTree(path, metadata) {
    const parts = path.split('/');
    let current = treeRoot;
    const orderIndex = getPathOrderIndex(path);

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLeaf = i === parts.length - 1;

        if (!current._children) {
            current._children = {};
        }

        if (isLeaf) {
            const nodeKey = `path:${part}`;
            current._children[nodeKey] = {
                _name: part,
                _isPath: true,
                _metadata: metadata,
                _order: orderIndex,
                _expanded: false,
                _fullPath: path
            };
        } else {
            if (!current._children[part]) {
                current._children[part] = {
                    _name: part,
                    _isIntermediate: true,
                    _expanded: true,
                    _order: orderIndex
                };
            } else {
                // Update order to be the minimum (earliest) of all children
                if (current._children[part]._order === undefined || 
                    orderIndex < current._children[part]._order) {
                    current._children[part]._order = orderIndex;
                }
            }
            current = current._children[part];
        }
    }
}

// Remove a node from both DOM and tree data structure
function removeNodeFromDomAndTree(path) {
    // Remove from DOM
    const nodeEl = nodeElements[path];
    if (nodeEl) {
        const parent = nodeEl.parentElement;
        nodeEl.remove();
        
        // Clean up empty parent containers
        cleanupEmptyContainers(parent);
    }
    
    // Remove from tree data structure
    removePathFromTree(path);
    
    // Clean up tracking
    delete nodeElements[path];
    knownPaths.delete(path);
    delete pathMetadata[path];
}

// Clean up empty tree-children containers after node removal
function cleanupEmptyContainers(container) {
    while (container && container.classList.contains('tree-children')) {
        if (container.children.length === 0) {
            const parentNode = container.parentElement;
            if (parentNode && parentNode.classList.contains('tree-node') && 
                parentNode.classList.contains('intermediate')) {
                const grandParent = parentNode.parentElement;
                parentNode.remove();
                container = grandParent;
            } else {
                break;
            }
        } else {
            break;
        }
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

    // Clean up empty intermediate nodes in tree data
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

// Insert a new node into the DOM at the correct position
function insertNodeIntoDom(path, metadata) {
    const parts = path.split('/');
    const container = document.getElementById('targets-container');
    let currentContainer = container;
    let currentTreeNode = treeRoot;

    // Navigate/create intermediate nodes
    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        
        if (!currentTreeNode._children || !currentTreeNode._children[part]) {
            // This shouldn't happen if insertPathIntoTree was called first
            return;
        }
        
        const treeNode = currentTreeNode._children[part];
        let domNode = findChildByName(currentContainer, part);
        
        if (!domNode) {
            // Create intermediate node
            domNode = createIntermediateNode(treeNode);
            insertNodeInOrder(currentContainer, domNode, treeNode, currentTreeNode);
        }
        
        let childContainer = domNode.querySelector(':scope > .tree-children');
        if (!childContainer) {
            childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            domNode.appendChild(childContainer);
        }
        
        currentContainer = childContainer;
        currentTreeNode = treeNode;
    }

    // Create the leaf node
    const lastPart = parts[parts.length - 1];
    const nodeKey = `path:${lastPart}`;
    const treeNode = currentTreeNode._children[nodeKey];
    
    const leafNode = createPathNode(treeNode, path, metadata);
    nodeElements[path] = leafNode;
    
    insertNodeInOrder(currentContainer, leafNode, treeNode, currentTreeNode);
    
    // Notify components about new node
    const status = metadata?.status || null;
    for (const callback of componentCallbacks) {
        callback(leafNode, status, true);
    }
}

// Find a child node by its display name
function findChildByName(container, name) {
    const children = container.querySelectorAll(':scope > .tree-node');
    for (const child of children) {
        const label = child.querySelector(':scope > .tree-header > .tree-label');
        if (label && label.textContent === name) {
            return child;
        }
    }
    return null;
}

// Insert a node in the correct order within a container
function insertNodeInOrder(container, newNode, newTreeNode, parentTreeNode) {
    const newOrderKey = getOrderKey('', newTreeNode);
    const children = container.querySelectorAll(':scope > .tree-node');
    
    for (const child of children) {
        const childLabel = child.querySelector(':scope > .tree-header > .tree-label');
        if (childLabel) {
            const childName = childLabel.textContent;
            // Find the corresponding tree node to get its order
            let childTreeNode = null;
            if (parentTreeNode._children) {
                for (const [key, node] of Object.entries(parentTreeNode._children)) {
                    if (node._name === childName) {
                        childTreeNode = node;
                        break;
                    }
                }
            }
            
            if (childTreeNode) {
                const childOrderKey = getOrderKey('', childTreeNode);
                if (newOrderKey < childOrderKey) {
                    container.insertBefore(newNode, child);
                    return;
                }
            }
        }
    }
    
    // Append at end if no insertion point found
    container.appendChild(newNode);
}

// Create an intermediate (directory) node
function createIntermediateNode(treeNode) {
    const div = document.createElement('div');
    div.className = 'tree-node intermediate';
    
    if (treeNode._isVariableScope) {
        div.classList.add('variable-scope');
    }
    
    if (treeNode._expanded) {
        div.classList.add('expanded');
    }

    const header = document.createElement('div');
    header.className = 'tree-header';
    
    header.addEventListener('click', () => {
        toggleIntermediateNode(div);
    });

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = treeNode._name;
    header.appendChild(label);

    div.appendChild(header);

    // Add variable scope form if this is a variable scope node
    if (treeNode._isVariableScope) {
        createVariableScopeForm(treeNode, div);
    }

    return div;
}

// Create a path (file) leaf node
function createPathNode(treeNode, path, metadata) {
    const div = document.createElement('div');
    div.className = 'tree-node path leaf';
    div.dataset.path = path;

    if (treeNode._expanded) {
        div.classList.add('expanded');
    }

    if (metadata) {
        if (metadata['mime-type']) {
            div.dataset.mimeType = metadata['mime-type'];
        }
        if (metadata.status) {
            div.dataset.status = metadata.status;
        }
        if (metadata.content !== undefined) {
            div.dataset.content = metadata.content;
        }
    }

    const header = document.createElement('div');
    header.className = 'tree-header';
    
    header.addEventListener('click', () => {
        toggleNodeByElement(div);
    });

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = treeNode._name;
    header.appendChild(label);

    div.appendChild(header);

    // Add metadata display
    if (metadata) {
        const metadataContainer = createMetadataContainer(metadata);
        div.appendChild(metadataContainer);
    }

    return div;
}

// Create a target leaf node
function createTargetNode(treeNode) {
    const div = document.createElement('div');
    div.className = 'tree-node target leaf';
    div.dataset.path = treeNode._fullPath || '';
    div.dataset.isTarget = 'true';

    if (treeNode._expanded) {
        div.classList.add('expanded');
    }

    const header = document.createElement('div');
    header.className = 'tree-header';
    
    header.addEventListener('click', () => {
        toggleNodeByElement(div);
    });

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = treeNode._name;
    header.appendChild(label);

    div.appendChild(header);

    return div;
}

// Create metadata container for a path node
function createMetadataContainer(metadata) {
    const metadataContainer = document.createElement('div');
    metadataContainer.className = 'metadata';

    const mimeType = metadata['mime-type'] || '';
    const showContent = mimeType.startsWith('text/');

    for (const [metaKey, metaValue] of Object.entries(metadata)) {
        if (metaKey === 'content') continue;
        if (metaKey.startsWith('_')) continue;
        const metaDiv = document.createElement('div');
        metaDiv.className = 'meta-info';
        metaDiv.setAttribute('data-label', metaKey);
        metaDiv.textContent = metaValue;
        metadataContainer.appendChild(metaDiv);
    }

    if (showContent && metadata.content !== undefined) {
        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'content-wrapper';
        const contentDiv = document.createElement('div');
        contentDiv.className = 'content';
        contentDiv.textContent = metadata.content;
        contentWrapper.appendChild(contentDiv);
        metadataContainer.appendChild(contentWrapper);
    }

    return metadataContainer;
}

// Update an existing node's metadata without rebuilding
function updateExistingNode(path, metadata) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;

    // Update data attributes
    if (metadata['mime-type']) {
        nodeEl.dataset.mimeType = metadata['mime-type'];
    }
    if (metadata.status) {
        nodeEl.dataset.status = metadata.status;
    }
    if (metadata.content !== undefined) {
        nodeEl.dataset.content = metadata.content;
    }

    // Update metadata display
    const existingMetadata = nodeEl.querySelector(':scope > .metadata');
    if (existingMetadata) {
        // Update meta-info elements
        for (const [metaKey, metaValue] of Object.entries(metadata)) {
            if (metaKey === 'content') continue;
            if (metaKey.startsWith('_')) continue;
            
            let metaDiv = existingMetadata.querySelector(`.meta-info[data-label="${metaKey}"]`);
            if (metaDiv) {
                metaDiv.textContent = metaValue;
            } else {
                metaDiv = document.createElement('div');
                metaDiv.className = 'meta-info';
                metaDiv.setAttribute('data-label', metaKey);
                metaDiv.textContent = metaValue;
                existingMetadata.insertBefore(metaDiv, existingMetadata.querySelector('.content-wrapper'));
            }
        }

        // Update content if applicable
        const mimeType = metadata['mime-type'] || '';
        const showContent = mimeType.startsWith('text/');
        const contentWrapper = existingMetadata.querySelector('.content-wrapper');
        
        if (showContent && metadata.content !== undefined) {
            if (contentWrapper) {
                const contentDiv = contentWrapper.querySelector('.content');
                if (contentDiv) {
                    contentDiv.textContent = metadata.content;
                }
            } else {
                const newContentWrapper = document.createElement('div');
                newContentWrapper.className = 'content-wrapper';
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                contentDiv.textContent = metadata.content;
                newContentWrapper.appendChild(contentDiv);
                existingMetadata.appendChild(newContentWrapper);
            }
        }
    }

    // Update tree data structure
    const parts = path.split('/');
    let current = treeRoot;
    for (let i = 0; i < parts.length - 1; i++) {
        if (current._children && current._children[parts[i]]) {
            current = current._children[parts[i]];
        } else {
            return;
        }
    }
    const nodeKey = `path:${parts[parts.length - 1]}`;
    if (current._children && current._children[nodeKey]) {
        current._children[nodeKey]._metadata = metadata;
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

function createVariableScopeForm(node, container) {
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
        // Build the path by substituting variables in the node's name pattern
        let pathPrefix = node._name;
        for (const [varName, input] of Object.entries(inputs)) {
            const value = input.value.trim();
            if (value) {
                pathPrefix = pathPrefix.replace(new RegExp('\\$' + varName, 'g'), value);
            }
        }
        
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

// Build the initial tree and render it (only called once on load)
function buildInitialTree() {
    treeRoot = {};
    
    // For each target, determine what should be displayed
    for (const target of targetOrder) {
        const vars = extractVariables(target);
        
        if (vars.length === 0) {
            // No variables - show target only if path doesn't exist
            if (!pathExists(target)) {
                insertTargetIntoTree(target);
            }
        } else {
            // Has variables - insert the target pattern for the variable scope form
            insertTargetPattern(target);
        }
    }
    
    // Insert all known paths
    for (const path of knownPaths) {
        const metadata = getPathMetadata(path);
        insertPathIntoTree(path, metadata);
    }
}

// Insert a target into the tree data structure
function insertTargetIntoTree(target) {
    const parts = target.split('/');
    let current = treeRoot;
    const orderIndex = getTargetOrderIndex(target);

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLeaf = i === parts.length - 1;

        if (!current._children) {
            current._children = {};
        }

        if (isLeaf) {
            const nodeKey = `target:${part}`;
            current._children[nodeKey] = {
                _name: part,
                _isTarget: true,
                _order: orderIndex,
                _expanded: false,
                _fullPath: target
            };
        } else {
            const isVariableSegment = part.includes('$');
            const nodeKey = isVariableSegment ? `targetvar:${part}` : part;
            
            if (!current._children[nodeKey]) {
                current._children[nodeKey] = {
                    _name: part,
                    _isIntermediate: true,
                    _isVariableScope: isVariableSegment,
                    _expanded: true,
                    _order: orderIndex
                };
            }
            current = current._children[nodeKey];
        }
    }
}

// Insert a target pattern into the tree (for variable scope forms)
function insertTargetPattern(pattern) {
    const parts = pattern.split('/');
    let current = treeRoot;
    const orderIndex = getTargetOrderIndex(pattern);

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLeaf = i === parts.length - 1;

        if (!current._children) {
            current._children = {};
        }

        const isVariableSegment = part.includes('$');
        
        if (isLeaf) {
            // Don't add leaf target patterns, they're handled elsewhere
        } else {
            const nodeKey = isVariableSegment ? `targetvar:${part}` : part;
            
            if (!current._children[nodeKey]) {
                current._children[nodeKey] = {
                    _name: part,
                    _isIntermediate: true,
                    _isVariableScope: isVariableSegment,
                    _targetPattern: pattern,
                    _expanded: true,
                    _order: orderIndex
                };
            } else {
                if (isVariableSegment) {
                    current._children[nodeKey]._isVariableScope = true;
                    current._children[nodeKey]._targetPattern = pattern;
                }
                // Update order to be the minimum (earliest) of all children
                if (current._children[nodeKey]._order === undefined || 
                    orderIndex < current._children[nodeKey]._order) {
                    current._children[nodeKey]._order = orderIndex;
                }
            }
            current = current._children[nodeKey];
        }
    }
}

// Render the entire tree (only called once on initial load)
function renderTree(node, container) {
    if (!node._children) return;

    const sortedKeys = Object.keys(node._children).sort((a, b) => {
        const childA = node._children[a];
        const childB = node._children[b];
        return getOrderKey(a, childA).localeCompare(getOrderKey(b, childB));
    });

    for (const key of sortedKeys) {
        const child = node._children[key];
        let div;

        if (child._isTarget) {
            div = createTargetNode(child);
        } else if (child._isPath) {
            div = createPathNode(child, child._fullPath, child._metadata);
            nodeElements[child._fullPath] = div;
        } else if (child._isIntermediate) {
            div = createIntermediateNode(child);
        }

        // Notify components about new node
        const status = child._metadata?.status || (child._isTarget ? 'target' : null);
        for (const callback of componentCallbacks) {
            callback(div, status, true);
        }

        if (child._children) {
            const childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            renderTree(child, childContainer);
            div.appendChild(childContainer);
        }

        container.appendChild(div);
    }
}

// Initial display (only called once)
function initialDisplay() {
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
            buildInitialTree();
            initialDisplay();
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
