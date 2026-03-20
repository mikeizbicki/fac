// nodes.js
//
// This module provides a centralized API for managing tree nodes in the UI.
// It maintains a registry of all nodes and provides factory functions for
// creating standardized DOM structures that ui_common components can hook into.
//
// Node Registry API:
// -------------------
// window.createNode(path, options) - Create and register a new node
//   options: {
//     type: 'path' | 'target',  // 'path' for files, 'target' for build targets
//     mimeType: string,         // MIME type (paths only)
//     status: string,           // 'fresh', 'stale', 'building', 'queued', 'deleted'
//     content: string,          // File content for text files
//     isLeaf: boolean,          // Whether this is a leaf node (default: true)
//     order: number,            // Sort order for sibling nodes
//     parent: Element,          // Parent container to append to
//     label: string,            // Display label (defaults to last path segment)
//   }
//   Returns: the created DOM element
//
// window.updateNode(path, metadata) - Update an existing node's metadata
//   metadata: { status, mimeType, content, ... }
//   Notifies all registered components of the change
//
// window.removeNode(path, options) - Remove a node from the registry and DOM
//   options: { animate: boolean }  // Whether to animate removal (default: true)
//   Returns: Promise that resolves when removal is complete
//
// window.getNode(path) - Get a node element by path
//   Returns: Element or undefined
//
// window.hasNode(path) - Check if a node exists
//   Returns: boolean
//
// window.getAllNodes() - Get all registered nodes
//   Returns: Map<path, Element>
//
// window.clearAllNodes() - Clear all nodes from registry (does not remove from DOM)
//
// Component System API:
// ---------------------
// window.registerComponent(callback) - Register a callback for node events:
//   callback(nodeEl, status, isNew) called on node changes
//   - nodeEl: DOM element with data-path, data-status, etc.
//   - status: "fresh" | "stale" | "building" | "queued" | "deleted" | etc.
//   - isNew: true if node was just added to DOM
//
// window.notifyComponents(nodeEl, status, isNew) - Trigger all callbacks for a node
//
// Node DOM Structure:
// -------------------
// Nodes are div elements with class 'tree-node' and the following structure:
//   <div class="tree-node [path|target] [leaf|intermediate] [expanded]"
//        data-path="..."
//        data-is-target="true"      (targets only)
//        data-mime-type="..."       (paths only)
//        data-status="..."          (paths only)
//        data-content="..."         (text files only)
//        data-order="...">
//     <div class="tree-header">
//       <button class="tree-toggle">▶</button>
//       <span class="tree-label">filename</span>
//     </div>
//     <div class="metadata">...</div>           (paths only)
//     <div class="image-container">...</div>    (images only)
//     <div class="video-container">...</div>    (videos only)
//     <div class="tree-children">...</div>      (intermediate only)
//   </div>
//
// IMPORTANT:
// Coding agents must not change this API without asking for permission.

(function() {
    // Node registry: path -> Element
    const nodeRegistry = new Map();

    // Component callbacks
    const componentCallbacks = [];

    // Pending removal animations
    const pendingRemovals = new Map();

    //
    // Component System
    //

    window.registerComponent = function(callback) {
        componentCallbacks.push(callback);
    };

    window.notifyComponents = function(nodeEl, status, isNew) {
        for (const callback of componentCallbacks) {
            callback(nodeEl, status, isNew);
        }
    };

    //
    // Node Registry Queries
    //

    window.getNode = function(path) {
        return nodeRegistry.get(path);
    };

    window.hasNode = function(path) {
        return nodeRegistry.has(path);
    };

    window.getAllNodes = function() {
        return new Map(nodeRegistry);
    };

    window.clearAllNodes = function() {
        // Cancel any pending removals
        for (const [path, pending] of pendingRemovals) {
            clearTimeout(pending.timeoutId);
        }
        pendingRemovals.clear();
        nodeRegistry.clear();
    };

    //
    // Node Factory
    //

    window.createNode = function(path, options = {}) {
        const {
            type = 'path',
            mimeType = '',
            status = '',
            content,
            isLeaf = true,
            order = 0,
            parent = null,
            label = path.split('/').pop() || path,
        } = options;

        // If node already exists, just update it
        if (nodeRegistry.has(path)) {
            const existing = nodeRegistry.get(path);
            window.updateNode(path, { status, mimeType, content });
            return existing;
        }

        // Cancel any pending removal for this path
        if (pendingRemovals.has(path)) {
            clearTimeout(pendingRemovals.get(path).timeoutId);
            const oldEl = pendingRemovals.get(path).element;
            oldEl.classList.remove('fading-out');
            pendingRemovals.delete(path);
        }

        const div = document.createElement('div');
        div.className = 'tree-node';
        div.classList.add(type);
        div.classList.add(isLeaf ? 'leaf' : 'intermediate');
        if (!isLeaf) div.classList.add('expanded');

        div.dataset.path = path;
        div.dataset.order = order;

        if (type === 'target') {
            div.dataset.isTarget = 'true';
        } else {
            if (mimeType) div.dataset.mimeType = mimeType;
            if (status) div.dataset.status = status;
            if (content !== undefined) div.dataset.content = content;
        }

        // Create header
        const header = document.createElement('div');
        header.className = 'tree-header';
        header.addEventListener('click', () => {
            div.classList.toggle('expanded');
        });

        const toggle = document.createElement('button');
        toggle.className = 'tree-toggle';
        toggle.innerHTML = '&#9654;';
        header.appendChild(toggle);

        const labelSpan = document.createElement('span');
        labelSpan.className = 'tree-label';
        labelSpan.textContent = label;
        header.appendChild(labelSpan);

        div.appendChild(header);

        // Create metadata container for paths
        if (type === 'path') {
            div.appendChild(createMetadataContainer(mimeType, status, content));
        }

        // Create media containers based on mime type
        if (mimeType) {
            if (mimeType.startsWith('image/')) {
                const imageContainer = document.createElement('div');
                imageContainer.className = 'image-container';
                div.insertBefore(imageContainer, div.firstChild);
                div.classList.add('has-image');
            } else if (mimeType.startsWith('video/')) {
                const videoContainer = document.createElement('div');
                videoContainer.className = 'video-container';
                div.insertBefore(videoContainer, div.firstChild);
                div.classList.add('has-video');
            }
        }

        // Register the node
        nodeRegistry.set(path, div);

        // Append to parent if provided
        if (parent) {
            insertNodeInOrder(parent, div, order);
        }

        // Notify components
        window.notifyComponents(div, status || (type === 'target' ? 'target' : 'unknown'), true);

        return div;
    };

    function createMetadataContainer(mimeType, status, content) {
        const container = document.createElement('div');
        container.className = 'metadata';

        // Add mime-type info
        if (mimeType) {
            const mimeDiv = document.createElement('div');
            mimeDiv.className = 'meta-info';
            mimeDiv.setAttribute('data-label', 'mime-type');
            mimeDiv.textContent = mimeType;
            container.appendChild(mimeDiv);
        }

        // Add status info
        if (status) {
            const statusDiv = document.createElement('div');
            statusDiv.className = 'meta-info';
            statusDiv.setAttribute('data-label', 'status');
            statusDiv.textContent = status;
            container.appendChild(statusDiv);
        }

        // Add content for text files
        const showContent = mimeType && mimeType.startsWith('text/');
        if (showContent && content !== undefined) {
            const wrapper = document.createElement('div');
            wrapper.className = 'content-wrapper';
            const contentDiv = document.createElement('div');
            contentDiv.className = 'content';
            contentDiv.textContent = content;
            wrapper.appendChild(contentDiv);
            container.appendChild(wrapper);
        }

        return container;
    }

    function insertNodeInOrder(container, newNode, newOrder) {
        const children = container.querySelectorAll(':scope > .tree-node');
        for (const child of children) {
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

    //
    // Node Updates
    //

    window.updateNode = function(path, metadata) {
        const nodeEl = nodeRegistry.get(path);
        if (!nodeEl) return false;

        const { status, mimeType, content, ...rest } = metadata;

        // Update data attributes
        if (mimeType !== undefined) nodeEl.dataset.mimeType = mimeType;
        if (status !== undefined) nodeEl.dataset.status = status;
        if (content !== undefined) nodeEl.dataset.content = content;

        // Update metadata display
        const metadataContainer = nodeEl.querySelector(':scope > .metadata');
        if (metadataContainer) {
            // Update or create mime-type
            if (mimeType !== undefined) {
                updateOrCreateMetaInfo(metadataContainer, 'mime-type', mimeType);
            }

            // Update or create status
            if (status !== undefined) {
                updateOrCreateMetaInfo(metadataContainer, 'status', status);
            }

            // Update content for text files
            const currentMime = nodeEl.dataset.mimeType || '';
            if (currentMime.startsWith('text/') && content !== undefined) {
                let wrapper = metadataContainer.querySelector('.content-wrapper');
                if (wrapper) {
                    const contentDiv = wrapper.querySelector('.content');
                    if (contentDiv) contentDiv.textContent = content;
                } else {
                    wrapper = document.createElement('div');
                    wrapper.className = 'content-wrapper';
                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'content';
                    contentDiv.textContent = content;
                    wrapper.appendChild(contentDiv);
                    metadataContainer.appendChild(wrapper);
                }
            }

            // Update any additional metadata
            for (const [key, value] of Object.entries(rest)) {
                if (!key.startsWith('_')) {
                    updateOrCreateMetaInfo(metadataContainer, key, value);
                }
            }
        }

        // Notify components of the update
        window.notifyComponents(nodeEl, status || nodeEl.dataset.status, false);

        return true;
    };

    function updateOrCreateMetaInfo(container, label, value) {
        let metaDiv = container.querySelector(`.meta-info[data-label="${label}"]`);
        if (metaDiv) {
            metaDiv.textContent = value;
        } else {
            metaDiv = document.createElement('div');
            metaDiv.className = 'meta-info';
            metaDiv.setAttribute('data-label', label);
            metaDiv.textContent = value;
            // Insert before content-wrapper if it exists
            const contentWrapper = container.querySelector('.content-wrapper');
            if (contentWrapper) {
                container.insertBefore(metaDiv, contentWrapper);
            } else {
                container.appendChild(metaDiv);
            }
        }
    }

    //
    // Node Removal
    //

    window.removeNode = function(path, options = {}) {
        const { animate = true } = options;

        const nodeEl = nodeRegistry.get(path);
        if (!nodeEl) return Promise.resolve(false);

        return new Promise((resolve) => {
            // Notify components of deletion
            nodeEl.dataset.status = 'deleted';
            window.notifyComponents(nodeEl, 'deleted', false);

            if (!animate) {
                removeNodeImmediate(path, nodeEl);
                resolve(true);
                return;
            }

            // Start fade animation
            nodeEl.classList.add('fading-out');

            const timeoutId = setTimeout(() => {
                // Check if a new node was created for this path during animation
                if (pendingRemovals.has(path)) {
                    removeNodeImmediate(path, nodeEl);
                    pendingRemovals.delete(path);
                }
                resolve(true);
            }, 1500);

            pendingRemovals.set(path, { element: nodeEl, timeoutId });
        });
    };

    function removeNodeImmediate(path, nodeEl) {
        const parent = nodeEl.parentElement;
        nodeEl.remove();
        nodeRegistry.delete(path);

        // Clean up empty containers
        cleanupEmptyContainers(parent);
    }

    function cleanupEmptyContainers(container) {
        while (container && container.classList.contains('tree-children')) {
            if (container.children.length === 0) {
                const parentNode = container.parentElement;
                if (parentNode?.classList.contains('tree-node') &&
                    parentNode.classList.contains('intermediate')) {
                    const grandParent = parentNode.parentElement;
                    // Also remove from registry if it's there
                    const parentPath = parentNode.dataset.path;
                    if (parentPath) nodeRegistry.delete(parentPath);
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

    //
    // Helper: Create intermediate node
    //

    window.createIntermediateNode = function(path, options = {}) {
        const {
            order = 0,
            parent = null,
            label = path.split('/').pop() || path,
            isVariableScope = false,
        } = options;

        // Check if already exists
        const existing = nodeRegistry.get(path);
        if (existing) return existing;

        const div = document.createElement('div');
        div.className = 'tree-node intermediate expanded';
        div.dataset.path = path;
        div.dataset.order = order;
        if (isVariableScope) div.classList.add('variable-scope');

        const header = document.createElement('div');
        header.className = 'tree-header';
        header.addEventListener('click', () => {
            div.classList.toggle('expanded');
        });

        const toggle = document.createElement('button');
        toggle.className = 'tree-toggle';
        toggle.innerHTML = '&#9654;';
        header.appendChild(toggle);

        const labelSpan = document.createElement('span');
        labelSpan.className = 'tree-label';
        labelSpan.textContent = label;
        header.appendChild(labelSpan);

        div.appendChild(header);

        // Create children container
        const children = document.createElement('div');
        children.className = 'tree-children';
        div.appendChild(children);

        nodeRegistry.set(path, div);

        if (parent) {
            insertNodeInOrder(parent, div, order);
        }

        return div;
    };

    //
    // Helper: Get or create child container
    //

    window.getNodeChildContainer = function(nodeEl) {
        let childContainer = nodeEl.querySelector(':scope > .tree-children');
        if (!childContainer) {
            childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            nodeEl.appendChild(childContainer);
        }
        return childContainer;
    };

})();
