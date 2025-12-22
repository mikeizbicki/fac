/**
 * FAC BUILD SYSTEM - CLIENT SIDE
 * 
 * This JavaScript module provides the frontend interface for triggering FAC builds
 * from the web UI. It integrates with the existing FabulaMachina Flask application
 * to allow users to rebuild individual assets (images, audio, etc.) on demand.
 * 
 * ARCHITECTURE OVERVIEW:
 * - Scans DOM for elements with class "fac-build" and data-fac-target attributes
 * - Adds build control buttons (🔨 build, 🔄 rebuild, 📝 rebuild with notes) to each element
 * - Communicates with backend via REST API (/api/fac/build) and Server-Sent Events (/api/fac/build/logs)
 * - Shows real-time build status overlays on the UI elements being built
 * - Prevents concurrent builds (only one build allowed at a time)
 * 
 * INTEGRATION WITH FABULAMACHINA:
 * - Works alongside existing auto-updater system for file change notifications
 * - Uses same overlay system as auto-updater for consistent UI feedback
 * - Elements must have both "fac-build" and "auto-updater" classes to work properly
 * - Build targets are specified via data-fac-target attribute (e.g., "books/level1/book1/frames/frame1/art.png")
 * 
 * EVENT FLOW:
 * 1. User clicks build button → sends POST to /api/fac/build
 * 2. Server responds with build_id → client opens SSE stream to /api/fac/build/logs/{build_id}
 * 3. Server sends real-time log messages and status updates via SSE
 * 4. Client shows overlays and updates UI based on build progress
 * 5. Build completes → client closes SSE stream and shows final status
 * 
 * ERROR HANDLING:
 * - Network errors: Shows "Build request failed" overlay
 * - Server errors: Displays error message from server response
 * - Concurrent builds: Shows alert and prevents new build
 * - Log stream errors: Automatically closes stream and resets state
 */

class FacBuildSystem {
    constructor() {
        this.buildInProgress = false;
        this.eventSource = null;
        this.currentTarget = null;
        this.observer = null;
        console.log('FAC Build: Initializing build system...');
        
        // Wait for DOM to be fully loaded before scanning for elements
        setTimeout(() => {
            this.initializeBuildElements();
        }, 1000);
    }

    /**
     * Scans the DOM for fac-build elements and adds build control menus
     */
    initializeBuildElements() {
        console.log('FAC Build: Scanning for buildable elements...');
        const facBuilds = document.querySelectorAll('.fac-build');
        console.log(`FAC Build: Found ${facBuilds.length} fac-build elements`);
        
        facBuilds.forEach((element, index) => {
            this.addBuildControls(element, index);
        });

        // Watch for dynamically added fac-build elements
        this.setupDOMObserver();
    }

    /**
     * Sets up MutationObserver to handle dynamically added fac-build elements
     */
    setupDOMObserver() {
        // Disconnect existing observer if any
        if (this.observer) {
            this.observer.disconnect();
        }

        this.observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.classList && node.classList.contains('fac-build')) {
                            this.addBuildControls(node);
                        }
                        // Check children
                        if (node.querySelectorAll) {
                            const newFacBuilds = node.querySelectorAll('.fac-build');
                            newFacBuilds.forEach(element => {
                                this.addBuildControls(element);
                            });
                        }
                    }
                });
            });
        });

        this.observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    /**
     * Adds build control buttons to a fac-build element
     * Creates three buttons: build (🔨), rebuild (🔄), rebuild with notes (📝)
     */
    addBuildControls(element, index) {
        const target = element.dataset.facTarget;
        if (!target) {
            console.warn('FAC Build: Element missing data-fac-target attribute:', element);
            return;
        }

        console.log(`FAC Build: Adding controls for target: ${target}`);

        // Create container for build buttons
        const controls = document.createElement('div');
        controls.className = 'fac-build-controls';

        // Build button (🔨) - builds only if file doesn't exist or is out of date
        const buildBtn = document.createElement('button');
        buildBtn.innerHTML = '🔨';
        buildBtn.title = 'Build';
        buildBtn.className = 'fac-build-btn';
        buildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log(`FAC Build: Build clicked for ${target}`);
            this.triggerBuild(target, false);
        });

        // Rebuild button (🔄) - forces rebuild even if file is up to date
        const rebuildBtn = document.createElement('button');
        rebuildBtn.innerHTML = '🔄';
        rebuildBtn.title = 'Rebuild (force)';
        rebuildBtn.className = 'fac-build-btn';
        rebuildBtn.style.cssText = buildBtn.style.cssText;
        rebuildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log(`FAC Build: Rebuild clicked for ${target}`);
            this.triggerBuild(target, true);
        });

        // Rebuild with notes button (📝) - rebuild with additional context
        const notesBtn = document.createElement('button');
        notesBtn.innerHTML = '📝';
        notesBtn.title = 'Rebuild with notes';
        notesBtn.className = 'fac-build-btn';
        notesBtn.style.cssText = buildBtn.style.cssText;
        notesBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const notes = prompt('Enter additional notes for the build:');
            if (notes !== null && notes.trim() !== '') {
                console.log(`FAC Build: Rebuild with notes clicked for ${target}`);
                this.triggerBuild(target, true, notes);
            }
        });

        // Add hover effects
        [buildBtn, rebuildBtn, notesBtn].forEach(btn => {
            btn.addEventListener('mouseenter', () => {
                btn.style.background = 'rgba(255, 255, 255, 1)';
                btn.style.transform = 'scale(1.5)';
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.background = 'rgba(255, 255, 255, 0.9)';
                btn.style.transform = 'scale(1)';
            });
        });

        controls.appendChild(buildBtn);
        controls.appendChild(rebuildBtn);
        controls.appendChild(notesBtn);

        // Create a wrapper that contains both the element and controls
        const wrapper = document.createElement('div');
        wrapper.className = 'fac-build-wrapper';
        wrapper.style.cssText = 'position: relative; display: inline-block;';

        // Move the fac-build element into the wrapper
        element.parentNode.insertBefore(wrapper, element);
        wrapper.appendChild(element);
        wrapper.appendChild(controls);
        /*
        // Add to parent container
        const container = element.parentElement || element;
        const containerStyle = window.getComputedStyle(container);
        if (containerStyle.position === 'static') {
            container.style.position = 'relative';
        }
        container.appendChild(controls);
        */
        console.log(`FAC Build: Controls added for target: ${target}`);
    }

    /**
     * Triggers a build request to the Flask backend
     * @param {string} target - The fac target to build (e.g., "books/level1/book1/frames/frame1/art.png")
     * @param {boolean} overwrite - Whether to force rebuild even if file is up to date
     * @param {string|null} notes - Additional notes to include in the build context
     */
    async triggerBuild(target, overwrite = false, notes = null) {
        console.log(`FAC Build: Triggering build - target=${target}, overwrite=${overwrite}, notes=${notes ? 'provided' : 'none'}`);
        
        if (this.buildInProgress) {
            alert('A build is already in progress. Please wait for it to complete.');
            return;
        }

        // Switch to console tab to show build output
        if (window.sidebar) {
            window.sidebar.switchTab('console');
        }
        // Show immediate feedback
        this.showBuildStatus(target, 'Sending request...', 'permanent');

        const payload = { target, overwrite };
        if (notes) payload.notes = notes;

        try {
            const response = await fetch('/api/fac/build', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();
            console.log('FAC Build: Server response:', result);

            if (response.ok) {
                this.buildInProgress = true;
                this.currentTarget = target;
                this.showBuildStatus(target, 'Building...', 'permanent');
                this.startLogStream(result.build_id);
            } else {
                throw new Error(result.error || 'Build request failed');
            }

        } catch (error) {
            console.error('FAC Build: Request failed:', error);
            this.showBuildStatus(target, `Error: ${error.message}`, 'permanent');
            setTimeout(() => this.clearBuildStatus(target), 5000);
        }
    }

    /**
     * Opens Server-Sent Events stream to receive real-time build logs and status updates
     * @param {string} buildId - Unique identifier for the build session
     */
    startLogStream(buildId) {
        console.log(`FAC Build: Opening log stream for build ${buildId}`);
        
        if (this.eventSource) {
            this.eventSource.close();
        }

        this.eventSource = new EventSource(`/api/fac/build/logs/${buildId}`);
        this.eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            switch (data.type) {
                case 'log':
                    console.log(`FAC Build [${data.level}]: ${data.message}`);
                    break;
                    
                case 'build_started':
                    console.log('FAC Build: Build started on server');
                    this.showBuildStatus(this.currentTarget, 'Building...', data.display_type || 'permanent');
                    break;
                    
                case 'build_completed':
                    console.log('FAC Build: Build completed successfully');
                    this.showBuildStatus(this.currentTarget, 'Build completed!', data.display_type || 'permanent');
                    this.resetBuildState();
                    break;
                    
                case 'build_error':
                    console.error('FAC Build: Build failed:', data.error);
                    this.showBuildStatus(this.currentTarget, 'Build failed!', data.display_type || 'permanent');
                    this.resetBuildState();
                    break;
                    
                case 'heartbeat':
                    break;
                    
                default:
                    console.log('FAC Build: Unknown message type:', data);
            }
        };

        this.eventSource.onerror = (event) => {
            console.error('FAC Build: Log stream error:', event);
            this.resetBuildState();
        };
    }

    /**
     * Resets build state and closes SSE connection
     */
    resetBuildState() {
        this.buildInProgress = false;
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this.currentTarget = null;
    }

    /**
     * Shows build status overlay on target elements
     * @param {string} target - The fac target to show status for
     * @param {string} message - Status message to display
     * @param {string} displayType - 'permanent' or 'flash'
     */
    showBuildStatus(target, message, displayType = 'permanent') {
        console.log(`FAC Build: Status update - ${target}: ${message} (${displayType})`);
        
        const elements = document.querySelectorAll(`[data-fac-target="${target}"]`);
        elements.forEach(element => {
            this.clearBuildStatus(target); // Remove existing status first
            
            const status = document.createElement('div');
            status.className = 'fac-build-status';
            status.textContent = message;
            status.style.cssText = `
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 8px 12px;
                border-radius: 4px;
                z-index: 2000;
                font-size: 12px;
                font-weight: bold;
                white-space: nowrap;
                pointer-events: none;
                opacity: 1;
                transition: opacity 1s ease-out;
            `;
            
            const container = element.parentElement || element;
            if (window.getComputedStyle(container).position === 'static') {
                container.style.position = 'relative';
            }
            container.appendChild(status);
            
            // Dim the element during build
            element.style.opacity = '0.6';
            
            // Handle flash messages
            if (displayType === 'flash') {
                setTimeout(() => {
                    status.style.opacity = '0';
                    // Remove element after fade completes
                    setTimeout(() => {
                        if (status.parentNode) {
                            status.parentNode.removeChild(status);
                        }
                        // Restore element opacity
                        element.style.opacity = '';
                    }, 1000); // 1 second fade duration
                }, 1000); // 1 second display duration
            }
        });
    }

    /**
     * Removes build status overlays from target elements
     * @param {string} target - The fac target to clear status for
     */
    clearBuildStatus(target) {
        const elements = document.querySelectorAll(`[data-fac-target="${target}"]`);
        elements.forEach(element => {
            element.style.opacity = '';
            const container = element.parentElement || element;
            const statuses = container.querySelectorAll('.fac-build-status');
            statuses.forEach(status => status.remove());
        });
    }
}

// Initialize the build system when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('FAC Build: DOM loaded, initializing build system...');
    window.facBuildSystem = new FacBuildSystem();
});
