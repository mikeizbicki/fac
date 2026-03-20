// targets.js
//
// This file manages a hierarchical tree view of build targets and file paths.
// It fetches target definitions from /list_targets and monitors file changes
// via the monitor_files.js module. The tree displays both targets (build recipes
// with potential variables like $CHAPTER) and paths (actual files generated
// from those targets).
//
// This component registers itself as a tab in the main pane.
//
// Tree Invariant:
// ---------------
// We maintain an invariant that for every path, exactly one node will be
// displayed in the tree. This is now enforced by nodes.js - when we call
// createNode() with type 'target', it will return null if a path node
// already exists, and when we call createNode() with type 'path', it will
// convert any existing target node.

(function() {

let targets = {};
let targetOrder = [];
let pathMetadata = {};
let rootContainer = null;
let isInitialized = false;  // Track whether initial tree build has happened

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

// Get sibling targets that share the same first variable scope
function getSiblingTargets(targetPattern) {
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return [targetPattern];

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

// Find or create intermediate node in container
function findOrCreateIntermediateNode(container, name, fullPath, order, isVarScope, targetPattern) {
    // Check if node already exists in registry
    const existing = window.getNode(fullPath);
    if (existing) {
        return existing;
    }

    // Node doesn't exist in registry, create it
    const div = window.createIntermediateNode(fullPath, {
        order: order,
        parent: container,
        label: name,
        isVariableScope: isVarScope,
    });

    if (isVarScope && targetPattern) {
        createVariableScopeForm(div, targetPattern);
    }

    return div;
}

function insertPathNode(path, metadata) {
    const parts = path.split('/');
    let currentContainer = rootContainer;
    const orderIndex = getPathOrderIndex(path);
    let currentPath = '';

    // Create intermediate nodes
    for (let i = 0; i < parts.length - 1; i++) {
        currentPath = currentPath ? currentPath + '/' + parts[i] : parts[i];
        const domNode = findOrCreateIntermediateNode(
            currentContainer,
            parts[i],
            currentPath,
            orderIndex,
            false,
            null
        );
        currentContainer = window.getNodeChildContainer(domNode);
    }

    // Create leaf node - nodes.js handles target->path conversion
    window.createNode(path, {
        type: 'path',
        mimeType: metadata['mime-type'],
        status: metadata.status,
        content: metadata.content,
        isLeaf: true,
        order: orderIndex,
        parent: currentContainer,
        label: parts[parts.length - 1],
    });
}

function insertTargetNode(concretePath, targetPattern) {
    const parts = concretePath.split('/');
    const targetParts = targetPattern.split('/');
    let currentContainer = rootContainer;
    const orderIndex = getTargetOrderIndex(targetPattern);
    let currentPath = '';

    for (let i = 0; i < parts.length - 1; i++) {
        currentPath = currentPath ? currentPath + '/' + parts[i] : parts[i];
        const isVarScope = targetParts[i + 1]?.includes('$');
        const domNode = findOrCreateIntermediateNode(
            currentContainer,
            parts[i],
            currentPath,
            orderIndex,
            isVarScope,
            isVarScope ? targetPattern : null
        );
        currentContainer = window.getNodeChildContainer(domNode);
    }

    // Create target node - nodes.js will return null if path already exists
    window.createNode(concretePath, {
        type: 'target',
        isLeaf: true,
        order: orderIndex,
        parent: currentContainer,
        label: parts[parts.length - 1],
    });
}

function showSiblingTargets(path, matchingTarget) {
    const siblings = getSiblingTargets(matchingTarget);
    const parts = path.split('/');
    const targetParts = matchingTarget.split('/');

    let firstVarIndex = -1;
    let firstVarValue = null;
    for (let i = 0; i < targetParts.length && i < parts.length; i++) {
        if (targetParts[i].includes('$')) {
            firstVarIndex = i;
            firstVarValue = parts[i];
            break;
        }
    }
    if (firstVarIndex < 0) return;

    for (const sibling of siblings) {
        const sibParts = sibling.split('/');
        const concreteParts = sibParts.map((part, i) => {
            if (i === firstVarIndex && part.includes('$')) {
                return firstVarValue;
            }
            return part;
        });
        const concretePathStr = concreteParts.join('/');

        // nodes.js will handle not creating if path already exists
        if (!window.hasNode(concretePathStr)) {
            insertTargetNode(concretePathStr, sibling);
        }
    }
}

function showTargetNodeForPath(path) {
    const matchingTarget = findMatchingTarget(path);
    if (!matchingTarget) return;

    // For non-variable targets, just show the target itself
    if (extractVariables(matchingTarget).length === 0) {
        insertTargetNode(matchingTarget, matchingTarget);
        return;
    }

    // For variable targets, show the concrete path as a target
    insertTargetNode(path, matchingTarget);
}

function handlePathEvent(path, metadata) {
    // Queue metadata but don't process events until initial tree is built
    if (!isInitialized) {
        if (metadata.status !== 'deleted') {
            pathMetadata[path] = metadata;
            window.markPathAsFile(path);
        }
        return;
    }

    const status = metadata.status;

    if (status === 'deleted') {
        window.unmarkPathAsFile(path);
        delete pathMetadata[path];

        // Convert to target node instead of removing completely
        const matchingTarget = findMatchingTarget(path);
        if (matchingTarget) {
            window.removeNode(path, { animate: true, convertToTarget: false }).then(() => {
                showTargetNodeForPath(path);
            });
        } else {
            window.removeNode(path, { animate: true });
        }
    } else {
        const isNew = !window.isFilePath(path);
        pathMetadata[path] = metadata;
        window.markPathAsFile(path);

        if (isNew) {
            const matchingTarget = findMatchingTarget(path);

            insertPathNode(path, metadata);

            // Show sibling targets for variable paths
            if (matchingTarget && extractVariables(matchingTarget).length > 0) {
                showSiblingTargets(path, matchingTarget);
            }
        } else {
            window.updateNode(path, {
                status: metadata.status,
                mimeType: metadata['mime-type'],
                content: metadata.content,
            });
        }
    }
}

function createVariableScopeForm(container, targetPattern) {
    const vars = extractVariables(targetPattern);
    if (vars.length === 0) return;

    // Get or create children container
    let childContainer = container.querySelector(':scope > .tree-children');
    if (!childContainer) {
        childContainer = document.createElement('div');
        childContainer.className = 'tree-children';
        container.appendChild(childContainer);
    }

    // Check if form already exists
    if (childContainer.querySelector('.variable-scope-form')) {
        return;
    }

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
        const varValues = {};
        for (const [varName, input] of Object.entries(inputs)) {
            const value = input.value.trim();
            if (value) varValues[varName] = value;
        }

        let buildPath = targetPattern;
        for (const [varName, value] of Object.entries(varValues)) {
            buildPath = buildPath.replace(new RegExp('\\$' + varName, 'g'), value);
        }

        const parts = buildPath.split('/');
        const newParts = [];
        for (const part of parts) {
            if (part.includes('$')) {
                newParts.push('**');
                break;
            }
            newParts.push(part);
        }
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

    // Insert form at beginning of children container
    childContainer.insertBefore(formDiv, childContainer.firstChild);
}

function buildInitialTree() {
    // Clear both DOM and node registry
    rootContainer.innerHTML = '';
    window.clearAllNodes();

    // Re-mark all known paths as files
    for (const path of Object.keys(pathMetadata)) {
        window.markPathAsFile(path);
    }

    // Insert non-variable targets that don't have existing paths
    for (const target of targetOrder) {
        const vars = extractVariables(target);
        if (vars.length === 0 && !window.isFilePath(target)) {
            insertTargetNode(target, target);
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
                    if (!seenPrefixes.has(prefix) && prefix) {
                        seenPrefixes.add(prefix);
                        insertVariableScopeNode(prefix, target);
                    }
                    break;
                }
                prefix = prefix ? prefix + '/' + parts[i] : parts[i];
            }
        }
    }

    // Insert all known paths
    const pathsToInsert = Object.keys(pathMetadata);
    for (const path of pathsToInsert) {
        const metadata = pathMetadata[path];
        if (metadata) {
            insertPathNode(path, metadata);

            const matchingTarget = findMatchingTarget(path);
            if (matchingTarget && extractVariables(matchingTarget).length > 0) {
                showSiblingTargets(path, matchingTarget);
            }
        }
    }

    // Mark as initialized so future SSE events are processed immediately
    isInitialized = true;
}

function insertVariableScopeNode(prefix, targetPattern) {
    let currentContainer = rootContainer;
    const parts = prefix.split('/').filter(p => p);
    const orderIndex = getTargetOrderIndex(targetPattern);
    let currentPath = '';

    for (let i = 0; i < parts.length; i++) {
        currentPath = currentPath ? currentPath + '/' + parts[i] : parts[i];
        const isLast = i === parts.length - 1;
        const domNode = findOrCreateIntermediateNode(
            currentContainer,
            parts[i],
            currentPath,
            orderIndex,
            isLast,
            isLast ? targetPattern : null
        );
        currentContainer = window.getNodeChildContainer(domNode);
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

function init(tabContainer) {
    rootContainer = document.createElement('div');
    rootContainer.className = 'targets-container';
    rootContainer.id = 'targets-container';
    tabContainer.appendChild(rootContainer);

    // Register path handler for SSE events
    window.registerPathHandler(handlePathEvent);

    loadTargets();
}

// Register as a tab
window.registerTab({
    id: 'targets',
    label: 'Targets',
    pane: 'main',
    render: init
});

})();
