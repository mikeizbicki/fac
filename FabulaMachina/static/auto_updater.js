/**
 * AUTO-UPDATER SYSTEM
 *
 * MOTIVATION:
 * This system provides real-time automatic updates for images and other assets in the web interface.
 * When files are modified on the server (e.g., new artwork is generated, images are replaced),
 * the corresponding images in the browser should automatically refresh without requiring a page reload.
 * This creates a seamless workflow where users can see changes immediately as files are updated.
 *
 * ARCHITECTURE:
 * 1. CLIENT-SIDE: Uses MutationObserver to automatically detect <img> elements with the "auto-updater" class
 * 2. SUBSCRIPTION: For each detected image, extracts the file path and subscribes to server-side file watching
 * 3. COMMUNICATION: Uses Server-Sent Events (SSE) to receive real-time notifications from the server
 * 4. PATH NORMALIZATION: Handles URL timestamps and query parameters to maintain consistent file path tracking
 * 5. UPDATE HANDLING: When file change events are received, updates image src with cache-busting timestamp
 * 6. VISUAL FEEDBACK: Shows loading spinners, "file deleted" states, and other status indicators
 * 7. CLEANUP: Automatically unsubscribes from file watching when images are removed from the DOM
 *
 * USAGE:
 * Simply add the "auto-updater" class to any <img> element. The system will automatically:
 * - Subscribe to file change notifications for that image's src path
 * - Update the image when the file changes on the server
 * - Handle edge cases like rapid updates, missing files, and network errors
 * - Clean up subscriptions when the image is removed from the page
 */

// the debugLog function should be used instead of console.log for debug messages
const urlParams = new URLSearchParams(window.location.search);
const DEBUG = urlParams.get('debug') === 'true' ||
              localStorage.getItem('autoUpdaterDebug') === 'true';
const debugLog = DEBUG ? console.log.bind(console, 'AutoUpdater:') : () => {};


class AutoUpdater {
    constructor() {
        this.eventSource = null;
        this.subscribedPaths = new Set();
        this.imageElements = new Map(); // path -> Set of img elements
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.clientId = null;
        this.pendingSubscriptions = new Set(); // Paths waiting for client ID
        this.pendingUpdates = new Map(); // path -> timeout ID (for debouncing)

        debugLog('AutoUpdater: Initializing...');
        this.startObserving(); // Start observing first
        this.connect(); // Then connect
    }

    // Helper method to normalize paths (remove query parameters and fragments)
    normalizePath(src) {
        if (!src) return null;

        let path;
        if (src.startsWith('/')) {
            path = src;
        } else {
            path = new URL(src, window.location.href).pathname;
        }

        // remove the api andpoint info /api/get_target from the path
        path = path.replace(/^\/api\/get_target/, '');

        // Remove query parameters and fragments
        return path.split('?')[0].split('#')[0];
    }

    connect() {
        debugLog('AutoUpdater: Attempting to connect...');
        if (this.eventSource) {
            this.eventSource.close();
        }

        this.eventSource = new EventSource('/api/auto_updater/events');

        this.eventSource.onopen = () => {
            debugLog('AutoUpdater: Connected successfully');
            this.reconnectAttempts = 0;
        };

        this.eventSource.onmessage = (event) => {
            debugLog('AutoUpdater: Received message:', event.data);
            try {
                const message = JSON.parse(event.data);
                if (message.type === 'connected') {
                    this.clientId = message.client_id;
                    debugLog('AutoUpdater: Got client ID:', this.clientId);
                    // Now that we have client ID, process pending subscriptions
                    this.processPendingSubscriptions();
                } else {
                    this.handleMessage(message);
                }
            } catch (e) {
                console.error('AutoUpdater: Invalid message format:', e);
            }
        };

        this.eventSource.onerror = (event) => {
            console.warn('AutoUpdater: Connection error', event);
            this.eventSource.close();
            this.clientId = null; // Reset client ID on disconnect
            this.scheduleReconnect();
        };
    }

    async processPendingSubscriptions() {
        debugLog(`AutoUpdater: Processing ${this.pendingSubscriptions.size} pending subscriptions`);
        const pathsToSubscribe = Array.from(this.pendingSubscriptions);
        this.pendingSubscriptions.clear();

        for (const path of pathsToSubscribe) {
            await this.subscribePath(path);
        }

        // Also resubscribe to any existing subscriptions after reconnect
        const existingPaths = Array.from(this.subscribedPaths);
        this.subscribedPaths.clear();
        for (const path of existingPaths) {
            await this.subscribePath(path);
        }
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
            setTimeout(() => {
                this.reconnectAttempts++;
                debugLog(`AutoUpdater: Reconnecting (attempt ${this.reconnectAttempts})`);
                this.connect();
            }, delay);
        } else {
            console.error('AutoUpdater: Max reconnection attempts reached');
        }
    }

    async subscribePath(path) {
        if (this.subscribedPaths.has(path)) {
            debugLog(`AutoUpdater: Already subscribed to ${path}`);
            return;
        }

        // If we don't have a client ID yet, queue the subscription
        if (!this.clientId) {
            debugLog(`AutoUpdater: Queueing subscription for ${path} (no client ID yet)`);
            this.pendingSubscriptions.add(path);
            return;
        }

        debugLog(`AutoUpdater: Attempting to subscribe to ${path}`);
        try {
            const response = await fetch('/api/auto_updater/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    path: path,
                    client_id: this.clientId
                })
            });

            const result = await response.json();
            if (response.ok && result.success) {
                this.subscribedPaths.add(path);
                debugLog(`AutoUpdater: Successfully subscribed to ${path}`);
            } else {
                console.error(`AutoUpdater: Failed to subscribe to ${path}:`, result.error);
            }
        } catch (e) {
            console.error(`AutoUpdater: Error subscribing to ${path}:`, e);
        }
    }

    async unsubscribePath(path) {
        if (!this.subscribedPaths.has(path)) {
            // Also remove from pending if it's there
            this.pendingSubscriptions.delete(path);
            return;
        }

        debugLog(`AutoUpdater: Unsubscribing from ${path}`);

        // If no client ID, just remove from local tracking
        if (!this.clientId) {
            this.subscribedPaths.delete(path);
            this.pendingSubscriptions.delete(path);
            return;
        }

        try {
            const response = await fetch('/api/auto_updater/unsubscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    path: path,
                    client_id: this.clientId
                })
            });

            if (response.ok) {
                this.subscribedPaths.delete(path);
                debugLog(`AutoUpdater: Unsubscribed from ${path}`);
            } else {
                console.error(`AutoUpdater: Failed to unsubscribe from ${path}`);
            }
        } catch (e) {
            console.error(`AutoUpdater: Error unsubscribing from ${path}:`, e);
        }
    }

    handleMessage(message) {
        debugLog('AutoUpdater: Handling message:', message);
        const { type, path, data } = message;

        if (type === 'heartbeat') {
            // Ignore heartbeats
            return;
        }

        const elements = this.imageElements.get(path);

        if (!elements) {
            debugLog(`AutoUpdater: No elements found for path ${path}`);
            return;
        }

        debugLog(`AutoUpdater: Found ${elements.size} elements for path ${path}`);

        switch (type) {
            case 'file_updated':
                this.handleFileUpdated(elements, path);
                break;
            case 'file_deleted':
                this.handleFileDeleted(elements);
                break;
            case 'file_updating':
                this.handleFileUpdating(elements);
                break;
            default:
                console.warn(`AutoUpdater: Unknown message type: ${type}`);
        }
    }

    handleFileUpdated(elements, path) {
        debugLog(`AutoUpdater: Updating ${elements.size} elements for ${path}`);

        // Cancel any pending update for this path
        if (this.pendingUpdates.has(path)) {
            clearTimeout(this.pendingUpdates.get(path));
        }

        // Debounce rapid updates to prevent NS_BINDING_ABORTED errors
        const timeoutId = setTimeout(() => {
            this.pendingUpdates.delete(path);

            elements.forEach(element => {
                this.removeOverlay(element);
                
                // Handle both images and videos
                if (element.tagName === 'VIDEO') {
                    // For videos, we need to reload the source and call load()
                    const currentSrc = element.querySelector('source')?.getAttribute('src') || element.src;
                    const normalizedPath = this.normalizePath(currentSrc);

                    if (normalizedPath === path) {
                        const url = new URL(currentSrc, window.location.href);
                        url.searchParams.set('t', Date.now());
                        
                        this.ignoreNextSrcChange = true;
                        
                        // Update both the source element and video src
                        const source = element.querySelector('source');
                        if (source) {
                            source.src = url.toString();
                        }
                        element.src = url.toString();
                        element.load(); // This is crucial for videos
                        
                        debugLog(`AutoUpdater: Updated video src to ${element.src}`);
                        
                        setTimeout(() => {
                            this.ignoreNextSrcChange = false;
                        }, 100);
                    }
                } else {
                    // Original image handling
                    const currentSrc = element.getAttribute('src');
                    const normalizedPath = this.normalizePath(currentSrc);

                    if (normalizedPath === path) {
                        const url = new URL(currentSrc, window.location.href);
                        url.searchParams.set('t', Date.now());

                        this.ignoreNextSrcChange = true;
                        element.src = url.toString();

                        debugLog(`AutoUpdater: Updated image src to ${element.src}`);

                        setTimeout(() => {
                            this.ignoreNextSrcChange = false;
                        }, 100);
                    }
                }
            });
        }, 100); // 100ms debounce

        this.pendingUpdates.set(path, timeoutId);
    }

    handleFileDeleted(elements) {
        debugLog(`AutoUpdater: Marking ${elements.size} elements as deleted`);
        elements.forEach(element => {
            this.removeOverlay(element);
            
            const mediaType = element.tagName === 'VIDEO' ? 'Video' : 'Image';
            this.showDeletedState(element, mediaType);
        });
    }

    showDeletedState(element, mediaType) {
        // First, aggressively remove any existing overlays for this element
        this.removeOverlay(element);
        
        const overlay = document.createElement('div');
        overlay.className = 'auto-updater-overlay deleted video-deleted';
        overlay.innerHTML = `
            <div class="status">${mediaType} Unavailable</div>
            <div class="substatus">File deleted</div>
        `;
        
        // Find the best container for positioning
        let container = element.parentElement;
        
        // For videos, try to find a container that's already relatively positioned
        if (element.tagName === 'VIDEO') {
            let current = element.parentElement;
            let depth = 0;
            while (current && depth < 3) {
                const style = window.getComputedStyle(current);
                if (style.position === 'relative' || current.classList.contains('video-container')) {
                    container = current;
                    break;
                }
                current = current.parentElement;
                depth++;
            }
        }
        
        // Position overlay directly over the element
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.zIndex = '999';
        
        // Ensure container is relatively positioned
        const containerStyle = window.getComputedStyle(container);
        if (containerStyle.position === 'static') {
            container.style.position = 'relative';
        }
        
        // Add a unique identifier to help with cleanup
        overlay.dataset.elementPath = this.normalizePath(
            element.tagName === 'VIDEO' ? 
                (element.querySelector('source')?.src || element.src) : 
                element.src
        );
        
        container.appendChild(overlay);
        debugLog(`AutoUpdater: Added ${mediaType} deleted overlay for ${overlay.dataset.elementPath}`);
    }


    handleFileUpdating(elements) {
        debugLog(`AutoUpdater: Showing updating state for ${elements.size} elements`);
        elements.forEach(img => {
            this.showUpdatingState(img);
        });
    }

    showUpdatingState(img) {
        this.removeOverlay(img);

        const overlay = document.createElement('div');
        overlay.className = 'auto-updater-overlay updating';
        overlay.innerHTML = `
            <div class="spinner"></div>
            <div class="status">Updating...</div>
        `;

        this.addOverlay(img, overlay);
    }

    addOverlay(img, overlay) {
        const container = img.parentElement;
        if (!container.style.position || container.style.position === 'static') {
            container.style.position = 'relative';
        }
        container.appendChild(overlay);
        img.style.opacity = '0.5';
    }

    removeOverlay(element) {
        element.style.opacity = '';
        
        // More aggressive overlay cleanup - search in parent containers too
        let container = element.parentElement;
        let searchDepth = 0;
        const maxSearchDepth = 3; // Limit how far we search up the DOM
        
        while (container && searchDepth < maxSearchDepth) {
            const overlays = container.querySelectorAll('.auto-updater-overlay');
            overlays.forEach(overlay => {
                // Check if this overlay is positioned over our element
                const overlayRect = overlay.getBoundingClientRect();
                const elementRect = element.getBoundingClientRect();
                
                // If overlay roughly matches element position, remove it
                const isPositionedOverElement = 
                    Math.abs(overlayRect.left - elementRect.left) < 10 &&
                    Math.abs(overlayRect.top - elementRect.top) < 10 &&
                    Math.abs(overlayRect.width - elementRect.width) < 20 &&
                    Math.abs(overlayRect.height - elementRect.height) < 20;
                    
                if (isPositionedOverElement || overlay.classList.contains('video-deleted')) {
                    overlay.remove();
                    debugLog(`AutoUpdater: Removed overlay from container at depth ${searchDepth}`);
                }
            });
            
            container = container.parentElement;
            searchDepth++;
        }
    }


    addImage(img) {
        const src = img.getAttribute('src') || (img.tagName === 'VIDEO' ? (img.querySelector('source')?.src || img.src) : null);
        debugLog(`AutoUpdater: Adding ${img.tagName.toLowerCase()} with src: ${src}`);
        if (!src) return;

        const path = this.normalizePath(src);
        if (!path) return;

        debugLog(`AutoUpdater: Resolved normalized path: ${path}`);

        if (!this.imageElements.has(path)) {
            this.imageElements.set(path, new Set());
            debugLog(`AutoUpdater: Created new element set for path: ${path}`);
        }

        const elementSet = this.imageElements.get(path);
        
        // Check if we already have this exact element (avoid duplicates)
        if (elementSet.has(img)) {
            debugLog(`AutoUpdater: Element already tracked for path: ${path}`);
            return;
        }

        elementSet.add(img);
        debugLog(`AutoUpdater: Added element, total for path ${path}: ${elementSet.size}`);

        // Clean up any existing overlays on this element before checking file existence
        this.removeOverlay(img);

        // Check if the file exists
        if (img.tagName === 'VIDEO') {
            this.checkVideoExists(img, src);
        } else {
            this.checkImageExists(img, src);
        }

        this.subscribePath(path);
    }


    async checkImageExists(img, src) {
        try {
            const response = await fetch(src, { method: 'HEAD' });
            if (!response.ok) {
                debugLog(`AutoUpdater: Image file not found: ${src}`);
                this.showDeletedState(img, 'Image');
            }
        } catch (error) {
            debugLog(`AutoUpdater: Error checking image file: ${src}`, error);
            this.showDeletedState(img, 'Image');
        }
    }

    async checkVideoExists(video, src) {
        try {
            const response = await fetch(src, { method: 'HEAD' });
            if (!response.ok) {
                debugLog(`AutoUpdater: Video file not found: ${src}`);
                this.showDeletedState(video, 'Video');
            }
        } catch (error) {
            debugLog(`AutoUpdater: Error checking video file: ${src}`, error);
            this.showDeletedState(video, 'Video');
        }
    }

    removeImage(element) {
        let src;
        if (element.tagName === 'VIDEO') {
            const source = element.querySelector('source');
            src = source ? source.getAttribute('src') : element.getAttribute('src');
        } else {
            src = element.getAttribute('src');
        }

        debugLog(`AutoUpdater: Removing ${element.tagName} element with src: ${src}`);
        if (!src) return;

        const path = this.normalizePath(src);
        if (!path) return;

        const elements = this.imageElements.get(path);

        if (elements) {
            elements.delete(element);
            debugLog(`AutoUpdater: Removed ${element.tagName} element, remaining for path ${path}: ${elements.size}`);
            if (elements.size === 0) {
                this.imageElements.delete(path);
                this.unsubscribePath(path);
                debugLog(`AutoUpdater: No more elements for path ${path}, unsubscribed`);
            }
        }
    }

    startObserving() {
        debugLog('AutoUpdater: Starting to observe DOM...');
        // Initial scan for existing images AND videos
        const existingElements = document.querySelectorAll('.auto-updater');
        debugLog(`AutoUpdater: Found ${existingElements.length} existing auto-updater elements`);
        existingElements.forEach(element => {
            this.addImage(element); // This method works for videos too
        });

        // Watch for new/removed elements
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                // Handle added nodes
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.matches && node.matches('img.auto-updater, video.auto-updater')) {
                            debugLog('AutoUpdater: New auto-updater element added');
                            this.addImage(node);
                        }
                        // Check children
                        if (node.querySelectorAll) {
                            const newElements = node.querySelectorAll('img.auto-updater, video.auto-updater');
                            debugLog(`AutoUpdater: Found ${newElements.length} new auto-updater elements in added subtree`);
                            newElements.forEach(element => {
                                this.addImage(element);
                            });
                        }
                    }
                });

                // Handle removed nodes
                mutation.removedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.matches && node.matches('img.auto-updater, video.auto-updater')) {
                            debugLog('AutoUpdater: Auto-updater element removed');
                            this.removeImage(node);
                        }
                        // Check children
                        if (node.querySelectorAll) {
                            const removedElements = node.querySelectorAll('img.auto-updater, video.auto-updater');
                            debugLog(`AutoUpdater: Found ${removedElements.length} auto-updater elements in removed subtree`);
                            removedElements.forEach(element => {
                                this.removeImage(element);
                            });
                        }
                    }
                });

                // Handle attribute changes (src changes) - but ignore our own changes
                if (mutation.type === 'attributes' &&
                    mutation.attributeName === 'src' &&
                    (mutation.target.classList.contains('auto-updater')) &&
                    !this.ignoreNextSrcChange) {

                    debugLog('AutoUpdater: Auto-updater element src changed');

                    const oldSrc = mutation.oldValue;
                    const newSrc = mutation.target.getAttribute('src');
                    const oldPath = this.normalizePath(oldSrc);
                    const newPath = this.normalizePath(newSrc);

                    // Only update tracking if the normalized path actually changed
                    if (oldPath !== newPath) {
                        this.removeImage(mutation.target);
                        this.addImage(mutation.target);
                    }
                }
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['src'],
            attributeOldValue: true  // We need the old value to compare paths
        });
        debugLog('AutoUpdater: DOM observer started');
    }
}

// CSS for overlays (unchanged)
const style = document.createElement('style');
style.textContent = `
    .auto-updater-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(255, 255, 255, 0.8);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .auto-updater-overlay .spinner {
        width: 20px;
        height: 20px;
        border: 2px solid #ccc;
        border-top: 2px solid #666;
        border-radius: 50%;
        animation: auto-updater-spin 1s linear infinite;
        margin-bottom: 5px;
    }

    .auto-updater-overlay .status {
        font-size: 10px;
        color: #666;
        font-family: Arial, sans-serif;
    }

    @keyframes auto-updater-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
document.head.appendChild(style);

// Initialize when DOM is ready
let autoUpdater;
document.addEventListener('DOMContentLoaded', () => {
    autoUpdater = new AutoUpdater();
    window.autoUpdater = autoUpdater; // Make it globally accessible
});

// Export for manual access if needed
window.AutoUpdater = AutoUpdater;

