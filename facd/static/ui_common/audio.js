// audio.js
//
// This component handles display of audio files in the target tree.
// When a path node has mime-type audio/*, it registers for audio loading
// and displays it as an audio element with controls.
//
// For leaf nodes: audio is visible only when expanded.
//
// Provides global API for audio loading to avoid duplicate fetches:
// - window.audioCache: Map of path -> url
// - window.fetchAudio(path, forceRefresh): Returns promise of blob URL
// - window.registerAudioContainer(path, container, className): Auto-updates on refresh

(function() {
    const audioCache = {};
    const registeredContainers = {}; // path -> [{container, className}]

    window.audioCache = audioCache;

    window.fetchAudio = function(path, forceRefresh) {
        if (!forceRefresh && audioCache[path]) {
            return Promise.resolve(audioCache[path]);
        }
        // Keep the existing URL cached until the refreshed blob
        // arrives, so concurrent registerAudioContainer callers can
        // still paint with the old URL instead of an empty cache.
        const oldUrl = forceRefresh ? audioCache[path] : null;
        // Bypass the browser cache: file contents at a given path can
        // change rapidly (e.g. delete then rebuild) and the browser
        // will otherwise happily serve a stale cached audio file.
        const cacheBust = `&_t=${Date.now()}`;
        return fetch(`/contents?path=${encodeURIComponent(path)}${cacheBust}`, { cache: 'no-store' })
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                audioCache[path] = url;
                if (oldUrl && oldUrl !== url) {
                    URL.revokeObjectURL(oldUrl);
                }
                return url;
            });
    };

    window.registerAudioContainer = function(path, container, className) {
        if (!registeredContainers[path]) {
            registeredContainers[path] = [];
        }
        const existing = registeredContainers[path].find(r => r.container === container);
        if (!existing) {
            registeredContainers[path].push({ container, className });
        }
        // If a blob URL is already cached for this path, paint into the
        // new container immediately so views that join late still show
        // the audio without waiting for another fetch round-trip.
        if (audioCache[path]) {
            paintContainer(container, className, audioCache[path]);
        }
    };

    window.unregisterAudioContainer = function(path, container) {
        if (registeredContainers[path]) {
            registeredContainers[path] = registeredContainers[path].filter(r => r.container !== container);
        }
    };

    window.clearAudioFromContainers = function(path) {
        if (registeredContainers[path]) {
            for (const { container } of registeredContainers[path]) {
                container.innerHTML = '';
            }
        }
    };

    function paintContainer(container, className, url) {
        container.innerHTML = '';
        const audio = document.createElement('audio');
        audio.src = url;
        audio.className = className;
        audio.controls = true;
        audio.preload = 'metadata';
        container.appendChild(audio);
    }

    function refreshAllContainers(path, url) {
        if (!registeredContainers[path]) return;
        for (const { container, className } of registeredContainers[path]) {
            paintContainer(container, className, url);
        }
    }

    window._refreshAudioContainers = refreshAllContainers;

    function isAudioMimeType(mimeType) {
        return mimeType && mimeType.startsWith('audio/');
    }

    function setupLeafAudio(nodeEl) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isAudioMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        // Find the audio container created by nodes.js
        let audioContainer = nodeEl.querySelector('.audio-container');
        if (!audioContainer) {
            // Fallback: create container if not present
            audioContainer = document.createElement('div');
            audioContainer.className = 'audio-container';
            // Insert after the tree-header so the player sits below
            // the node's title bar rather than above it.
            const header = nodeEl.querySelector(':scope > .tree-header');
            if (header && header.nextSibling) {
                nodeEl.insertBefore(audioContainer, header.nextSibling);
            } else {
                nodeEl.appendChild(audioContainer);
            }
            nodeEl.classList.add('has-audio');
        }

        window.registerAudioContainer(path, audioContainer, 'leaf-audio');

        // Skip the initial fetch when the backend already reports the
        // file as 'notbuilt'.
        const initialStatus = nodeEl.dataset.status;
        if (initialStatus === 'notbuilt') {
            window.clearAudioFromContainers(path);
        } else {
            window.fetchAudio(path, false).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        }
    }

    function updateAudioForStatus(nodeEl, status) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isAudioMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        if (status === 'built') {
            window.fetchAudio(path, true).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        } else if (status === 'notbuilt') {
            window.clearAudioFromContainers(path);
        }
        // For any other state the currently-displayed audio stays
        // until the next 'built' refresh.
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (nodeEl.classList.contains('leaf') && nodeEl.classList.contains('path')) {
            if (isNew) {
                setupLeafAudio(nodeEl);
            } else {
                updateAudioForStatus(nodeEl, status);
            }
        }
    });
})();
