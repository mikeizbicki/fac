// targets.js
//
// This file manages a hierarchical tree view of build targets and file paths.
// It fetches target definitions from /list_targets and monitors file changes
// via the monitor_files.js module. The tree displays both targets
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
// Tree Invariant:
// ---------------
// We maintain an invariant that for every path, exactly one node will be
// displayed in the tree. For example, consider the set of targets:
//   "/characters/$CHARACTER/about.json"
//   "/characters/$CHARACTER/voice.json"
//   "/characters/$CHARACTER/character_sheet.png"
// If the path "/characters/Barbaros/about.json" exists, then we will have
// a corresponding path node but no corresponding target node. But if
// "/characters/Barbaros/about.json" exists and "/characters/Barbaros/voice.json"
// does not exist, then we will need a target node for "/characters/Barbaros/voice.json".
//
// IMPORTANT:
// Coding agents must not change this API without asking for permission.

let targets = {};
let targetOrder = [];
let knownPaths = new Set();
let nodeElements = {};
let targetNodeElements = {};
let pathMetadata = {};

// Pending operations queue per path to handle race conditions
let pendingOperations = {};
let processingPaths = new Set();

// Variable helpers
function extractVariables(pattern) {
    const vars = [];
    let match;
    const regex = /\$([A-Z_][A-Z0-9_]*)/g;
    while ((match = regex.exec(pattern)) !== null) {
        if (!vars.includes(match[1])) vars.push(match[1]);
    }
    return vars;
}

function targetToRegex(pattern) {
    let regexStr = pattern
        .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        .replace(/\\\$[A-Z_][A-Z0-9_]*/g, '([^/]+)');
    return new RegExp('^' + regexStr + '$');
}

function findMatchingTarget(path) {
    for (const target of targetOrder) {
        if (targetToRegex(target).test(path)) return target;
    }
    return null;
}

function getTargetOrderIndex(target) {
    const index = targetOrder.indexOf(target);
    return index >= 0 ? index : targetOrder.length;
}

function getPathOrderIndex(path) {
    const target = findMatchingTarget(path);
    return target ? getTargetOrderIndex(target) : targetOrder.length;
}

// Get all targets that match a given path prefix (for showing missing targets)
function getTargetsUnderPrefix(prefix) {
    return targetOrder.filter(t => t.startsWith(prefix + '/') || t === prefix);
}

// Get sibling targets that share the same variable scope
function getSiblingTargets(targetPattern) {
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return [targetPattern];
    
    // Find the variable segment position
    const parts = targetPattern.split('/');
    let varIndex = -1;
    for (let i = 0; i < parts.length; i++) {
        if (parts[i].includes('$')) {
            varIndex = i;
            break;
        }
    }
    if (varIndex < 0) return [targetPattern];
    
    const prefix = parts.slice(0, varIndex).join('/');
    return targetOrder.filter(t => {
        const tParts = t.split('/');
        if (tParts.length <= varIndex) return false;
        const tPrefix = tParts.slice(0, varIndex).join('/');
        return tPrefix === prefix && tParts[varIndex].includes('$');
    });
}

// Tree node operations
function toggleNodeByElement(nodeEl) {
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
    if (!pendingOperations[path]) pendingOperations[path] = [];
    pendingOperations[path].push(operation);
    if (!processingPaths.has(path)) processNextOperation(path);
}

function updateNodeStatus(path, status, isNew) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;
    nodeEl.dataset.status = status;
    window.notifyComponents(nodeEl, status, isNew);
}

function handleDeleteOperation(path, onComplete) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) { onComplete(); return; }

    // Skip animation if there's a pending create
    if (pendingOperations[path] && pendingOperations[path].length > 0) {
        nodeEl.dataset.status = 'deleted';
        window.notifyComponents(nodeEl, 'deleted', false);
        onComplete();
        return;
    }

    nodeEl.dataset.status = 'deleted';
    window.notifyComponents(nodeEl, 'deleted', false);
    nodeEl.classList.add('fading-out');
    
    setTimeout(() => {
        if (pendingOperations[path] && pendingOperations[path].length > 0) {
            nodeEl.classList.remove('fading-out');
            onComplete();
            return;
        }
        removeNodeFromDom(path);
        
        // Show target node if needed
        const matchingTarget = findMatchingTarget(path);
        if (matchingTarget && matchingTarget === path) {
            showTargetNode(matchingTarget);
        }
        onComplete();
    }, 1500);
}

function handleCreateOrUpdateOperation(path, metadata, isNew, onComplete) {
    window.markPathSeen(path);
    knownPaths.add(path);
    pathMetadata[path] = metadata;
    
    if (isNew) {
        const matchingTarget = findMatchingTarget(path);
        
        // Hide target node for this concrete path if it exists
        // This ensures we don't show both target and path nodes for the same path
        if (targetNodeElements[path]) {
            hideTargetNode(path);
        }
        
        insertNodeIntoDom(path, metadata);
        
        // Show sibling targets for variable paths
        if (matchingTarget && extractVariables(matchingTarget).length > 0) {
            showSiblingTargets(path, matchingTarget);
        }
    } else {
        updateExistingNode(path, metadata);
        updateNodeStatus(path, metadata.status, false);
    }
    onComplete();
}

function showSiblingTargets(path, matchingTarget) {
    const siblings = getSiblingTargets(matchingTarget);
    const parts = path.split('/');
    
    // Find variable position
    const targetParts = matchingTarget.split('/');
    let varIndex = -1;
    for (let i = 0; i < targetParts.length; i++) {
        if (targetParts[i].includes('$')) {
            varIndex = i;
            break;
        }
    }
    if (varIndex < 0) return;
    
    const varValue = parts[varIndex];
    
    for (const sibling of siblings) {
        const sibParts = sibling.split('/');
        // Build concrete path for this sibling
        let concretePath = sibling;
        for (let i = 0; i < sibParts.length; i++) {
            if (sibParts[i].includes('$')) {
                concretePath = concretePath.replace(sibParts[i], varValue);
            }
        }
        
        // Only show target node if path doesn't exist
        // This maintains the invariant: one node per path
        if (!knownPaths.has(concretePath)) {
            if (!targetNodeElements[concretePath]) {
                insertTargetNodeIntoDom(concretePath, sibling);
            } else {
                // Unhide if it was hidden
                targetNodeElements[concretePath].style.display = '';
            }
        }
    }
}

function showTargetNode(target) {
    if (targetNodeElements[target]) {
        targetNodeElements[target].style.display = '';
        return;
    }
    insertTargetNodeIntoDom(target, target);
}

function hideTargetNode(path) {
    const el = targetNodeElements[path];
    if (el) el.style.display = 'none';
}

function removeNodeFromDom(path) {
    const nodeEl = nodeElements[path];
    if (nodeEl) {
        const parent = nodeEl.parentElement;
        nodeEl.remove();
        cleanupEmptyContainers(parent);
    }
    delete nodeElements[path];
    knownPaths.delete(path);
    window.markPathUnseen(path);
    delete pathMetadata[path];
}

function cleanupEmptyContainers(container) {
    while (container && container.classList.contains('tree-children')) {
        if (container.children.length === 0) {
            const parentNode = container.parentElement;
            if (parentNode?.classList.contains('tree-node') && 
                parentNode.classList.contains('intermediate')) {
                const grandParent = parentNode.parentElement;
                parentNode.remove();
                container = grandParent;
            } else break;
        } else break;
    }
}

function getOrderKey(node) {
    const order = node._order !== undefined ? node._order : 9999999999;
    return String(order).padStart(10, '0') + ':' + (node._name || '');
}

function insertNodeIntoDom(path, metadata) {
    const parts = path.split('/');
    const container = document.getElementById('targets-container');
    let currentContainer = container;
    const orderIndex = getPathOrderIndex(path);

    // Navigate/create intermediate nodes
    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        let domNode = findChildByName(currentContainer, part);
        
        if (!domNode) {
            domNode = createIntermediateNode(part, orderIndex, false);
            insertNodeInOrder(currentContainer, domNode, orderIndex);
        }
        
        let childContainer = domNode.querySelector(':scope > .tree-children');
        if (!childContainer) {
            childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            domNode.appendChild(childContainer);
        }
        currentContainer = childContainer;
    }

    const leafNode = createPathNode(parts[parts.length - 1], path, metadata, orderIndex);
    nodeElements[path] = leafNode;
    insertNodeInOrder(currentContainer, leafNode, orderIndex);
    window.notifyComponents(leafNode, metadata?.status || null, true);
}

function insertTargetNodeIntoDom(concretePath, targetPattern) {
    const parts = concretePath.split('/');
    const container = document.getElementById('targets-container');
    let currentContainer = container;
    const orderIndex = getTargetOrderIndex(targetPattern);

    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        let domNode = findChildByName(currentContainer, part);
        
        if (!domNode) {
            const isVarScope = targetPattern.split('/')[i]?.includes('$');
            domNode = createIntermediateNode(part, orderIndex, isVarScope, targetPattern);
            insertNodeInOrder(currentContainer, domNode, orderIndex);
        }
        
        let childContainer = domNode.querySelector(':scope > .tree-children');
        if (!childContainer) {
            childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            domNode.appendChild(childContainer);
        }
        currentContainer = childContainer;
    }

    const targetNode = createTargetNode(parts[parts.length - 1], concretePath, orderIndex);
    targetNodeElements[concretePath] = targetNode;
    insertNodeInOrder(currentContainer, targetNode, orderIndex);
    window.notifyComponents(targetNode, 'target', true);
}

function findChildByName(container, name) {
    for (const child of container.querySelectorAll(':scope > .tree-node')) {
        const label = child.querySelector(':scope > .tree-header > .tree-label');
        if (label?.textContent === name) return child;
    }
    return null;
}

function insertNodeInOrder(container, newNode, newOrder) {
    for (const child of container.querySelectorAll(':scope > .tree-node')) {
        const childOrder = parseInt(child.dataset.order || '9999999999');
        const childLabel = child.querySelector(':scope > .tree-header > .tree-label')?.textContent || '';
        const newLabel = newNode.querySelector(':scope > .tree-header > .tree-label')?.textContent || '';
        
        if (newOrder < childOrder || (newOrder === childOrder && newLabel < childLabel)) {
            container.insertBefore(newNode, child);
            return;
        }
    }
    container.appendChild(newNode);
}

function createIntermediateNode(name, order, isVarScope, targetPattern) {
    const div = document.createElement('div');
    div.className = 'tree-node intermediate expanded';
    div.dataset.order = order;
    if (isVarScope) div.classList.add('variable-scope');

    const header = document.createElement('div');
    header.className = 'tree-header';
    header.addEventListener('click', () => toggleNodeByElement(div));

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = name;
    header.appendChild(label);

    div.appendChild(header);

    if (isVarScope && targetPattern) {
        createVariableScopeForm(div, targetPattern);
    }
    return div;
}

function createPathNode(name, path, metadata, order) {
    const div = document.createElement('div');
    div.className = 'tree-node path leaf';
    div.dataset.path = path;
    div.dataset.order = order;

    if (metadata) {
        if (metadata['mime-type']) div.dataset.mimeType = metadata['mime-type'];
        if (metadata.status) div.dataset.status = metadata.status;
        if (metadata.content !== undefined) div.dataset.content = metadata.content;
    }

    const header = document.createElement('div');
    header.className = 'tree-header';
    header.addEventListener('click', () => toggleNodeByElement(div));

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = name;
    header.appendChild(label);

    div.appendChild(header);

    if (metadata) {
        div.appendChild(createMetadataContainer(metadata));
    }
    return div;
}

function createTargetNode(name, path, order) {
    const div = document.createElement('div');
    div.className = 'tree-node target leaf';
    div.dataset.path = path;
    div.dataset.isTarget = 'true';
    div.dataset.order = order;

    const header = document.createElement('div');
    header.className = 'tree-header';
    header.addEventListener('click', () => toggleNodeByElement(div));

    const toggle = document.createElement('button');
    toggle.className = 'tree-toggle';
    toggle.innerHTML = '&#9654;';
    header.appendChild(toggle);

    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = name;
    header.appendChild(label);

    div.appendChild(header);
    return div;
}

function createMetadataContainer(metadata) {
    const container = document.createElement('div');
    container.className = 'metadata';

    const mimeType = metadata['mime-type'] || '';
    const showContent = mimeType.startsWith('text/');

    for (const [key, value] of Object.entries(metadata)) {
        if (key === 'content' || key.startsWith('_')) continue;
        const metaDiv = document.createElement('div');
        metaDiv.className = 'meta-info';
        metaDiv.setAttribute('data-label', key);
        metaDiv.textContent = value;
        container.appendChild(metaDiv);
    }

    if (showContent && metadata.content !== undefined) {
        const wrapper = document.createElement('div');
        wrapper.className = 'content-wrapper';
        const contentDiv = document.createElement('div');
        contentDiv.className = 'content';
        contentDiv.textContent = metadata.content;
        wrapper.appendChild(contentDiv);
        container.appendChild(wrapper);
    }
    return container;
}

function updateExistingNode(path, metadata) {
    const nodeEl = nodeElements[path];
    if (!nodeEl) return;

    if (metadata['mime-type']) nodeEl.dataset.mimeType = metadata['mime-type'];
    if (metadata.status) nodeEl.dataset.status = metadata.status;
    if (metadata.content !== undefined) nodeEl.dataset.content = metadata.content;

    const existingMetadata = nodeEl.querySelector(':scope > .metadata');
    if (existingMetadata) {
        for (const [key, value] of Object.entries(metadata)) {
            if (key === 'content' || key.startsWith('_')) continue;
            let metaDiv = existingMetadata.querySelector(`.meta-info[data-label="${key}"]`);
            if (metaDiv) {
                metaDiv.textContent = value;
            } else {
                metaDiv = document.createElement('div');
                metaDiv.className = 'meta-info';
                metaDiv.setAttribute('data-label', key);
                metaDiv.textContent = value;
                existingMetadata.insertBefore(metaDiv, existingMetadata.querySelector('.content-wrapper'));
            }
        }

        const mimeType = metadata['mime-type'] || '';
        if (mimeType.startsWith('text/') && metadata.content !== undefined) {
            let wrapper = existingMetadata.querySelector('.content-wrapper');
            if (wrapper) {
                const contentDiv = wrapper.querySelector('.content');
                if (contentDiv) contentDiv.textContent = metadata.content;
            } else {
                wrapper = document.createElement('div');
                wrapper.className = 'content-wrapper';
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                contentDiv.textContent = metadata.content;
                wrapper.appendChild(contentDiv);
                existingMetadata.appendChild(wrapper);
            }
        }
    }
    pathMetadata[path] = metadata;
}

function createVariableScopeForm(container, targetPattern) {
    // Get variables only from this specific target pattern's scope
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return;

    const formDiv = document.createElement('div');
    formDiv.className = 'variable-scope-form';
    
    const varsContainer = document.createElement('div');
    varsContainer.className = 'variable-inputs';
    
    const inputs = {};
    for (const varName of vars) {
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
        // Get variable values
        const varValues = {};
        let hasValue = false;
        for (const [varName, input] of Object.entries(inputs)) {
            const value = input.value.trim();
            if (value) {
                varValues[varName] = value;
                hasValue = true;
            }
        }
        
        // Build the target path
        let buildPath = targetPattern;
        for (const [varName, value] of Object.entries(varValues)) {
            buildPath = buildPath.replace(new RegExp('\\$' + varName, 'g'), value);
        }
        
        // Replace remaining variables with ** for "build all"
        const parts = buildPath.split('/');
        const newParts = [];
        for (const part of parts) {
            if (part.includes('$')) {
                newParts.push('**');
                break;
            }
            newParts.push(part);
        }
        // Use ** at end to build all targets under this prefix
        if (newParts[newParts.length - 1] !== '**') {
            newParts.push('**');
        }
        buildPath = newParts.join('/');
        
        const params = new URLSearchParams();
        params.set('target', buildPath);
        if (promptInput.value.trim()) {
            params.set('include_prompt', promptInput.value.trim());
        }
        
        fetch('/add_target?' + params.toString(), { method: 'POST' })
            .then(response => {
                if (!response.ok) throw new Error('Failed to queue build');
                return response.json();
            })
            .then(() => {
                for (const input of Object.values(inputs)) input.value = '';
                promptInput.value = '';
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

function buildInitialTree() {
    const container = document.getElementById('targets-container');
    container.innerHTML = '';
    nodeElements = {};
    targetNodeElements = {};

    // Insert non-variable targets that don't have existing paths
    for (const target of targetOrder) {
        const vars = extractVariables(target);
        if (vars.length === 0 && !knownPaths.has(target)) {
            insertTargetNodeIntoDom(target, target);
        }
    }
    
    // Insert variable scope nodes for top-level variable targets
    const seenPrefixes = new Set();
    for (const target of targetOrder) {
        const vars = extractVariables(target);
        if (vars.length > 0) {
            const parts = target.split('/');
            let prefix = '';
            for (let i = 0; i < parts.length; i++) {
                if (parts[i].includes('$')) {
                    if (!seenPrefixes.has(prefix)) {
                        seenPrefixes.add(prefix);
                        // Create intermediate nodes up to variable scope
                        insertVariableScopeNode(prefix, target);
                    }
                    break;
                }
                prefix = prefix ? prefix + '/' + parts[i] : parts[i];
            }
        }
    }

    // Insert all known paths
    for (const path of knownPaths) {
        const metadata = pathMetadata[path];
        insertNodeIntoDom(path, metadata);
        
        // Show sibling targets for variable paths
        const matchingTarget = findMatchingTarget(path);
        if (matchingTarget && extractVariables(matchingTarget).length > 0) {
            showSiblingTargets(path, matchingTarget);
        }
    }
}

function insertVariableScopeNode(prefix, targetPattern) {
    const container = document.getElementById('targets-container');
    let currentContainer = container;
    const parts = prefix.split('/').filter(p => p);
    const orderIndex = getTargetOrderIndex(targetPattern);

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        let domNode = findChildByName(currentContainer, part);
        
        if (!domNode) {
            const isLast = i === parts.length - 1;
            domNode = createIntermediateNode(part, orderIndex, isLast, isLast ? targetPattern : null);
            insertNodeInOrder(currentContainer, domNode, orderIndex);
        }
        
        let childContainer = domNode.querySelector(':scope > .tree-children');
        if (!childContainer) {
            childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            domNode.appendChild(childContainer);
        }
        currentContainer = childContainer;
    }
}

function loadTargets() {
    fetch('/list_targets')
        .then(response => response.json())
        .then(data => {
            targets = data;
            targetOrder = Object.keys(data);
            buildInitialTree();
        });
}

// Register path handler for SSE events
window.registerPathHandler(function(path, metadata, isNew) {
    const status = metadata.status;
    const isActuallyNew = !knownPaths.has(path);

    if (status === 'deleted') {
        if (knownPaths.has(path)) {
            queueOperation(path, (onComplete) => handleDeleteOperation(path, onComplete));
        }
    } else {
        queueOperation(path, (onComplete) => handleCreateOrUpdateOperation(path, metadata, isActuallyNew, onComplete));
    }
});

loadTargets();
