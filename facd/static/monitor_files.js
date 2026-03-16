// monitor_files.js
//
// This module connects to the /monitor_files SSE endpoint and dispatches
// path events to registered handlers. It tracks which paths have been seen
// to provide an isNew flag to handlers.
//
// API:
// window.registerPathHandler(callback) - Register a callback for path events:
//   callback(path, metadata, isNew) called on each SSE message
//   - path: string path of the file
//   - metadata: { target, status, "mime-type", content }
//   - isNew: true if this path has not been seen before

(function() {
    const seenPaths = new Set();
    const pathHandlers = [];

    window.registerPathHandler = function(callback) {
        pathHandlers.push(callback);
    };

    window.markPathSeen = function(path) {
        seenPaths.add(path);
    };

    window.markPathUnseen = function(path) {
        seenPaths.delete(path);
    };

    window.isPathSeen = function(path) {
        return seenPaths.has(path);
    };

    function monitorFiles() {
        const eventSource = new EventSource('/monitor_files');

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const path = data.path;

            const metadata = {
                target: data.target,
                status: data.status,
                'mime-type': data['mime-type'],
                content: data.content
            };

            const isNew = !seenPaths.has(path);

            // Don't update seenPaths here - let targets.js manage it
            // to handle delete+create race conditions properly

            for (const handler of pathHandlers) {
                handler(path, metadata, isNew);
            }
        };
    }

    // Start monitoring when script loads
    monitorFiles();
})();
