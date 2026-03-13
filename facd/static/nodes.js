// nodes.js
//
// This module maintains the component callback registry and provides
// a helper function to notify all components about node changes.
//
// API:
// window.registerComponent(callback) - Register a callback for node events:
//   callback(nodeEl, status, isNew) called on node changes
//   - nodeEl: DOM element with data-path, data-status, etc.
//   - status: "fresh" | "stale" | "building" | "queued" | "deleted" | etc.
//   - isNew: true if node was just added to DOM
//
// window.notifyComponents(nodeEl, status, isNew) - Trigger all callbacks for a node

(function() {
    const componentCallbacks = [];

    window.registerComponent = function(callback) {
        componentCallbacks.push(callback);
    };

    window.notifyComponents = function(nodeEl, status, isNew) {
        for (const callback of componentCallbacks) {
            callback(nodeEl, status, isNew);
        }
    };
})();
