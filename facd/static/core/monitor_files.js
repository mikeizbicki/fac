// monitor_files.js
//
// This module connects to the /monitor_files SSE endpoint and dispatches
// path events to registered handlers. It is purely responsible for the SSE
// connection and data parsing—it does not track state or manage the DOM.
//
// API:
// window.registerPathHandler(callback) - Register a callback for path events:
//   callback(path, metadata) called on each SSE message
//   - path: string path of the file
//   - metadata: { target, status, "mime-type", content }
//
// window.getPathState(path) - Return the most recent metadata for `path`
//   that we've ever seen on the SSE stream, or undefined. This lets
//   late-rendering views (e.g. the screenplay tabs, which only render
//   after the shooting-script.xml event arrives) pick up the current
//   state of any path whose SSE event was delivered earlier in this
//   connection's replay.
//
// The handlers are responsible for determining what to do with the event,
// including tracking whether a path is "new" in their own context.

(function() {
    const pathHandlers = [];
    const pathStates = new Map();
    let isUnloading = false;

    window.addEventListener('beforeunload', () => {
        isUnloading = true;
    });

    window.registerPathHandler = function(callback) {
        pathHandlers.push(callback);
        setTimeout(() => {
            for (const [path, metadata] of pathStates.entries()) {
                callback(path, metadata);
            }
        }, 0);
    };

    window.getPathState = function(path) {
        return pathStates.get(path);
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

            pathStates.set(path, metadata);

            for (const handler of pathHandlers) {
                handler(path, metadata);
            }
        };

        eventSource.onerror = () => {
            if (isUnloading) {
                return;
            }
            console.error('monitor_files SSE connection error, reconnecting...');
            eventSource.close();
            setTimeout(monitorFiles, 3000);
        };
    }

    // Start monitoring when script loads
    monitorFiles();
})();
