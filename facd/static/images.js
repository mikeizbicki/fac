// images.js
//
// This component handles display of image files in the target tree.
// When a path node has mime-type image/*, it fetches the image from
// /contents and displays it as an img tag.
//
// For leaf nodes: image is visible only when expanded.
// For intermediate nodes: when collapsed, shows all descendant images
// side-by-side in a single row with max 2in dimension.

(function() {
    const imageCache = {};

    function fetchAndCacheImage(path) {
        if (imageCache[path]) {
            return Promise.resolve(imageCache[path]);
        }
        return fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => response.blob())
            .then(blob => {
                const url = URL.createObjectURL(blob);
                imageCache[path] = url;
                return url;
            });
    }

    function isImageMimeType(mimeType) {
        return mimeType && mimeType.startsWith('image/');
    }

    function createImageElement(src, className) {
        const img = document.createElement('img');
        img.src = src;
        img.className = className;
        return img;
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
        
        const metadata = nodeEl.querySelector('.metadata');
        if (metadata) {
            metadata.appendChild(imageContainer);
        } else {
            nodeEl.appendChild(imageContainer);
        }

        fetchAndCacheImage(path).then(url => {
            const img = createImageElement(url, 'leaf-image');
            imageContainer.appendChild(img);
        });
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
            fetchAndCacheImage(path).then(url => {
                if (!nodeEl.classList.contains('expanded')) {
                    const img = createImageElement(url, 'preview-image');
                    img.title = path;
                    preview.appendChild(img);
                }
            });
        });
    }

    function updateAllIntermediateNodes() {
        document.querySelectorAll('.tree-node.intermediate').forEach(updateCollapsedPreview);
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (nodeEl.classList.contains('leaf') && nodeEl.classList.contains('path')) {
            setupLeafImage(nodeEl);
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
