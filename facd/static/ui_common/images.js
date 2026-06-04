// images.js
//
// This component handles display of image files in the target tree.
// When a path node has mime-type image/*, it registers for image loading
// and displays it as an img tag.
//
// For leaf nodes: image is visible only when expanded.
// For intermediate nodes: when collapsed, shows all descendant images
// side-by-side in a single row with max 2in dimension.
//
// Provides global API for image loading to avoid duplicate fetches:
// - window.imageCache: Map of path -> url
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
        // On force-refresh, keep the existing cached URL in place
        // until the new blob actually arrives, then swap and revoke
        // the old one. Revoking + deleting up front created a race
        // window in which any concurrent registerImageContainer
        // caller (e.g. screenplay re-render triggered by the same
        // SSE 'built' event) would find imageCache[path] empty and
        // paint nothing, leaving the container permanently blank.
        const oldUrl = forceRefresh ? imageCache[path] : null;
        // Bypass the browser cache: file contents at a given path can
        // change rapidly (e.g. delete then rebuild) and the browser
        // will otherwise happily serve a stale cached image, leading
        // to deleted files that appear to "still exist" after refresh.
        const cacheBust = `&_t=${Date.now()}`;
        return fetch(`/contents?path=${encodeURIComponent(path)}${cacheBust}`, { cache: 'no-store' })
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                imageCache[path] = url;
                imageVersion[path] = (imageVersion[path] || 0) + 1;
                if (oldUrl && oldUrl !== url) {
                    URL.revokeObjectURL(oldUrl);
                }
                return url;
            });
    };

    window.registerImageContainer = function(path, container, className) {
        if (!registeredContainers[path]) {
            registeredContainers[path] = [];
        }
        const existing = registeredContainers[path].find(r => r.container === container);
        if (!existing) {
            registeredContainers[path].push({ container, className });
        }
        // If a blob URL is already cached for this path, paint into the
        // new container immediately so views that join late still show
        // the image without waiting for another fetch round-trip.
        if (imageCache[path]) {
            paintContainer(container, className, imageCache[path]);
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

    function paintContainer(container, className, url) {
        container.innerHTML = '';
        const img = document.createElement('img');
        img.src = url;
        img.className = className;
        container.appendChild(img);
    }

    function refreshAllContainers(path, url) {
        if (!registeredContainers[path]) return;
        for (const { container, className } of registeredContainers[path]) {
            paintContainer(container, className, url);
        }
    }

    window._refreshImageContainers = refreshAllContainers;

    function isImageMimeType(mimeType) {
        return mimeType && mimeType.startsWith('image/');
    }

    function setupLeafImage(nodeEl) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isImageMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        // Find the image container created by nodes.js
        let imageContainer = nodeEl.querySelector('.image-container');
        if (!imageContainer) {
            // Fallback: create container if not present
            imageContainer = document.createElement('div');
            imageContainer.className = 'image-container';
            nodeEl.insertBefore(imageContainer, nodeEl.firstChild);
            nodeEl.classList.add('has-image');
        }

        window.registerImageContainer(path, imageContainer, 'leaf-image');

        // Only fetch when the backend reports the file as 'built'.
        // Fetching for other statuses (notbuilt, stale, buildable,
        // waiting, etc.) just produces noisy 404s in the console
        // because the file does not yet exist on disk. The component
        // will be re-invoked with status='built' once the file is
        // ready, at which point updateImageForStatus will fetch it.
        const initialStatus = nodeEl.dataset.status;
        if (initialStatus === 'built') {
            window.fetchImage(path, false).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        } else {
            window.clearImageFromContainers(path);
        }
    }

    function updateImageForStatus(nodeEl, status) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isImageMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        if (status === 'built') {
            // Force-refresh: a freshly-built file may have the same
            // path as an older one already cached in the browser, so
            // we explicitly bust the cache here.
            window.fetchImage(path, true).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        } else if (status === 'notbuilt') {
            window.clearImageFromContainers(path);
        }
        // For any other backend state (stale, unresolved, waiting,
        // phantom, buildable, build_required, command_sent(...), ...)
        // the currently-displayed image stays as-is until the next
        // 'built' transition refreshes it.
    }

    // Allow views that build their own leaf-style media elements
    // (notably the screenplay sticky notes) to plug into the same
    // setup/update flow used for tree-node leaves, so the
    // "only fetch on built" policy lives in exactly one place. The
    // element must expose data-path / data-mime-type / data-status
    // and contain a child .image-container.
    window.refreshImageNode = function(nodeEl, isNew) {
        if (isNew) {
            setupLeafImage(nodeEl);
        } else {
            updateImageForStatus(nodeEl, nodeEl.dataset.status);
        }
    };

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
            if (preview) preview.remove();
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
