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
// The handlers are responsible for determining what to do with the event,
// including tracking whether a path is "new" in their own context.

(function() {
    const pathHandlers = [];

    window.registerPathHandler = function(callback) {
        pathHandlers.push(callback);
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

            for (const handler of pathHandlers) {
                handler(path, metadata);
            }
        };

        eventSource.onerror = () => {
            console.error('monitor_files SSE connection error, reconnecting...');
            eventSource.close();
            setTimeout(monitorFiles, 3000);
        };
    }

    // Start monitoring when script loads
    monitorFiles();
})();
