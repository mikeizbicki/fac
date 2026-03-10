// videos.js
//
// This component handles display of video files in the target tree.
// When a path node has mime-type video/*, it fetches the video from
// /contents and displays it as a video element with controls.
//
// For leaf nodes: video is visible only when expanded.
// Works in both standard tree view and custom views like screenplay.

(function() {
    const videoCache = {};

    function fetchAndCacheVideo(path) {
        if (videoCache[path]) {
            return Promise.resolve(videoCache[path]);
        }
        return fetch(`/contents?path=${encodeURIComponent(path)}`)
            .then(response => response.blob())
            .then(blob => {
                const url = URL.createObjectURL(blob);
                videoCache[path] = url;
                return url;
            });
    }

    function isVideoMimeType(mimeType) {
        return mimeType && mimeType.startsWith('video/');
    }

    function createVideoElement(src, className) {
        const video = document.createElement('video');
        video.src = src;
        video.className = className;
        video.controls = true;
        video.preload = 'metadata';
        return video;
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
        
        const metadata = nodeEl.querySelector('.metadata');
        if (metadata) {
            metadata.appendChild(videoContainer);
        } else {
            nodeEl.appendChild(videoContainer);
        }

        fetchAndCacheVideo(path).then(url => {
            const video = createVideoElement(url, 'leaf-video');
            videoContainer.appendChild(video);
        });
    }

    function updateVideoForStatus(nodeEl, status) {
        const mimeType = nodeEl.dataset.mimeType;
        if (!isVideoMimeType(mimeType)) return;

        const path = nodeEl.dataset.path;
        if (!path) return;

        const videoContainer = nodeEl.querySelector('.video-container');
        if (!videoContainer) return;

        if (status === 'fresh') {
            // Refresh the video when content changes
            delete videoCache[path];
            videoContainer.innerHTML = '';
            fetchAndCacheVideo(path).then(url => {
                const video = createVideoElement(url, 'leaf-video');
                videoContainer.appendChild(video);
            });
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
