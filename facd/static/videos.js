// videos.js
//
// This component handles display of video files in the target tree.
// When a path node has mime-type video/*, it fetches the video from
// /contents and displays it as a video element with controls.
//
// For leaf nodes: video is visible only when expanded.
// Works in both standard tree view and custom views like screenplay.
//
// Provides global API for video loading to avoid duplicate fetches:
// - window.videoCache: Map of path -> url
// - window.fetchVideo(path, forceRefresh): Returns promise of blob URL
// - window.registerVideoContainer(path, container, className): Auto-updates on refresh

(function() {
    const videoCache = {};
    const registeredContainers = {}; // path -> [{container, className}]

    window.videoCache = videoCache;

    window.fetchVideo = function(path, forceRefresh) {
        if (!forceRefresh && videoCache[path]) {
            return Promise.resolve(videoCache[path]);
        }
        // Revoke old URL if refreshing
        if (forceRefresh && videoCache[path]) {
            URL.revokeObjectURL(videoCache[path]);
            delete videoCache[path];
        }
        return fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => {
                if (!response.ok) throw new Error('Not found');
                return response.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                videoCache[path] = url;
                return url;
            });
    };

    window.registerVideoContainer = function(path, container, className) {
        if (!registeredContainers[path]) {
            registeredContainers[path] = [];
        }
        // Avoid duplicate registrations
        const existing = registeredContainers[path].find(r => r.container === container);
        if (!existing) {
            registeredContainers[path].push({ container, className });
        }
    };

    window.unregisterVideoContainer = function(path, container) {
        if (registeredContainers[path]) {
            registeredContainers[path] = registeredContainers[path].filter(r => r.container !== container);
        }
    };

    window.clearVideoFromContainers = function(path) {
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
            const video = document.createElement('video');
            video.src = url;
            video.className = className;
            video.controls = true;
            video.preload = 'metadata';
            container.appendChild(video);
        }
    }

    function isVideoMimeType(mimeType) {
        return mimeType && mimeType.startsWith('video/');
    }

    function setupLeafVideo(nodeEl) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isVideoMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        let videoContainer = nodeEl.querySelector('.video-container');
        if (videoContainer) return;

        videoContainer = document.createElement('div');
        videoContainer.className = 'video-container';
        
        // Insert video container as first child for full-bleed effect
        nodeEl.insertBefore(videoContainer, nodeEl.firstChild);
        
        // Add class to indicate this node has a video
        nodeEl.classList.add('has-video');

        window.registerVideoContainer(path, videoContainer, 'leaf-video');

        window.fetchVideo(path, false).then(url => {
            refreshAllContainers(path, url);
        }).catch(() => {});
    }

    function updateVideoForStatus(nodeEl, status) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isVideoMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        if (status === 'fresh') {
            // Refresh the video when content changes
            window.fetchVideo(path, true).then(url => {
                refreshAllContainers(path, url);
            }).catch(() => {});
        } else if (status === 'deleted') {
            window.clearVideoFromContainers(path);
        }
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (nodeEl.classList.contains('leaf') && nodeEl.classList.contains('path')) {
            if (isNew) {
                setupLeafVideo(nodeEl);
            } else {
                updateVideoForStatus(nodeEl, status);
            }
        }
    });
})();
