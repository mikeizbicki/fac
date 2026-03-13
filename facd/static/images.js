// images.js
//
// This component handles display of image files in the target tree.
// When a path node has mime-type image/*, it fetches the image from
// /contents and displays it as an img tag.
//
// For leaf nodes: image is visible only when expanded.
// For intermediate nodes: when collapsed, shows all descendant images
// side-by-side in a single row with max 2in dimension.
//
// Provides global API for image loading to avoid duplicate fetches:
// - window.imageCache: Map of path -> { url, version }
// - window.fetchImage(path, forceRefresh): Returns promise of blob URL
// - window.registerImageContainer(path, container, className): Auto-updates on refresh

(function() {
    const imageCache = {};
    const imageVersion = {};
    const registeredContainers = {}; // path -> [{container, className}]

    window.imageCache = imageCache;

    window.fetchImage = function(path, forceRefresh) {
        if (!forceRefresh && imageCache[path]) {
            return Promise.resolve(imageCache[path]);
        }
        // Revoke old URL if refreshing
        if (forceRefresh && imageCache[path]) {
            URL.revokeObjectURL(imageCache[path]);
            delete imageCache[path];
        }
        return fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                imageCache[path] = url;
                imageVersion[path] = (imageVersion[path] || 0) + 1;
                return url;
            });
    };

    window.registerImageContainer = function(path, container, className) {
        if (!registeredContainers[path]) {
            registeredContainers[path] = [];
        }
        // Avoid duplicate registrations
        const existing = registeredContainers[path].find(r => r.container === container);
        if (!existing) {
            registeredContainers[path].push({ container, className });
        }
    };

    window.unregisterImageContainer = function(path, container) {
        if (registeredContainers[path]) {
            registeredContainers[path] = registeredContainers[path].filter(r => r.container !== container);
        }
    };

    window.clearImageFromContainers = function(path) {
        if (registeredContainers[path]) {
            for (const { container } of registeredContainers[path]) {
                container.innerHTML = '';
            }
        }
    };

    function refreshAllContainers(path, url) {
        if (!registeredContainers[path]) return;
        for (const { container, className } of registeredContainers[path]) {
            container.innerHTML = '';
            const img = document.createElement('img');
            img.src = url;
            img.className = className;
            container.appendChild(img);
        }
    }

    function isImageMimeType(mimeType) {
        return mimeType && mimeType.startsWith('image/');
    }

    function setupLeafImage(nodeEl) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isImageMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        let imageContainer = nodeEl.querySelector('.image-container');
        if (imageContainer) return;

        imageContainer = document.createElement('div');
        imageContainer.className = 'image-container';
        
        // Insert image container as first child for full-bleed effect
        nodeEl.insertBefore(imageContainer, nodeEl.firstChild);
        
        // Add class to indicate this node has an image
        nodeEl.classList.add('has-image');

        window.registerImageContainer(path, imageContainer, 'leaf-image');

        window.fetchImage(path, false).then(url => {
            refreshAllContainers(path, url);
        }).catch(() => {});
    }

    function updateImageForStatus(nodeEl, status) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isImageMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        if (status === 'fresh') {
            // Refresh the image when content changes
            window.fetchImage(path, true).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        } else if (status === 'deleted') {
            window.clearImageFromContainers(path);
        }
    }

    function getDescendantImagePaths(nodeEl) {
        const paths = [];
        const leafNodes = nodeEl.querySelectorAll('.tree-node.path.leaf');
        leafNodes.forEach(leaf => {
            const mimeType = leaf.dataset.mimeType;
            const path = leaf.dataset.path;
            if (isImageMimeType(mimeType) && path) {
                paths.push(path);
            }
        });
        return paths;
    }

    function updateCollapsedPreview(nodeEl) {
        if (!nodeEl.classList.contains('intermediate')) return;

        let preview = nodeEl.querySelector(':scope > .collapsed-image-preview');
        
        if (nodeEl.classList.contains('expanded')) {
            if (preview) {
                preview.remove();
            }
            return;
        }

        const imagePaths = getDescendantImagePaths(nodeEl);
        if (imagePaths.length === 0) {
            if (preview) preview.remove();
            return;
        }

        if (!preview) {
            preview = document.createElement('div');
            preview.className = 'collapsed-image-preview';
            const header = nodeEl.querySelector('.tree-header');
            if (header) {
                header.after(preview);
            } else {
                nodeEl.appendChild(preview);
            }
        }

        preview.innerHTML = '';

        imagePaths.forEach(path => {
            window.fetchImage(path, false).then(url => {
                if (!nodeEl.classList.contains('expanded')) {
                    const img = document.createElement('img');
                    img.src = url;
                    img.className = 'preview-image';
                    img.title = path;
                    preview.appendChild(img);
                }
            }).catch(() => {});
        });
    }

    function updateAllIntermediateNodes() {
        document.querySelectorAll('.tree-node.intermediate').forEach(updateCollapsedPreview);
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (nodeEl.classList.contains('leaf') && nodeEl.classList.contains('path')) {
            if (isNew) {
                setupLeafImage(nodeEl);
            } else {
                updateImageForStatus(nodeEl, status);
            }
        }

        if (isNew || nodeEl.classList.contains('intermediate')) {
            setTimeout(updateAllIntermediateNodes, 0);
        }
    });

    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const target = mutation.target;
                if (target.classList.contains('intermediate')) {
                    updateCollapsedPreview(target);
                }
            }
        });
    });

    observer.observe(document.body, {
        attributes: true,
        subtree: true,
        attributeFilter: ['class']
    });
})();
