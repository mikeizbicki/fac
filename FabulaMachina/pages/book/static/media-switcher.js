/**
 * Media Switcher System
 *
 * OVERVIEW:
 * This system manages switching between different media types (start_frame/art.png and video/processed.mp4)
 * within frame sticky notes. It works by controlling visibility of existing DOM elements rather than
 * moving them around, which prevents layout issues.
 *
 * INTEGRATION WITH OTHER SCRIPTS:
 * - Must load AFTER script.js since it depends on frame type detection logic
 * - Integrates with script.js frame type change handlers via refreshSwitcher() calls
 * - Works alongside auto-updater.js for file change notifications on media
 * - Does not interfere with audio-controls.js or fac.js build systems
 *
 * TIMING CONSIDERATIONS:
 * - Initializes after a delay to ensure all DOM elements and other scripts are ready
 * - Must reinitialize when frame types change (called from script.js)
 * - Watches for frame type changes via MutationObserver as backup
 *
 * DOM STRUCTURE ASSUMPTIONS:
 * - Each frame has .img-container and .video-container elements
 * - Frame type is available via .frame-type-value text content
 * - Frame containers are positioned within .frame-margin sticky notes
 *
 * GOTCHAS:
 * - Original containers must remain in DOM to preserve layout and auto-updater functionality
 * - Visibility changes must account for existing CSS display rules
 * - Frame height adjustments in script.js may need to be called after media switches
 * - MutationObserver must be careful not to create infinite loops with other scripts
 */

class MediaSwitcher {
    constructor() {
        this.frameSwitchers = new Map(); // frameId -> FrameMediaSwitcher instance
        this.observer = null;
        console.log('MediaSwitcher: Initializing...');

        // Wait for other scripts to fully initialize
        setTimeout(() => {
            this.initialize();
        }, 600);
    }

    initialize() {
        this.setupAllFrames();
        this.setupFrameTypeObserver();
        console.log(`MediaSwitcher: Initialized ${this.frameSwitchers.size} frame switchers`);
    }

    setupAllFrames() {
        const frames = document.querySelectorAll('.frame');

        frames.forEach(frame => {
            this.setupFrameMediaSwitcher(frame);
        });
    }

    setupFrameMediaSwitcher(frame) {
        const frameId = frame.dataset.frameId;
        if (!frameId) return;

        // Clean up existing switcher if any
        if (this.frameSwitchers.has(frameId)) {
            this.frameSwitchers.get(frameId).destroy();
        }

        // Get frame type
        const frameTypeValue = frame.querySelector('.frame-type-value');
        if (!frameTypeValue) {
            console.warn(`MediaSwitcher: No frame type found for frame ${frameId}`);
            return;
        }

        const frameType = frameTypeValue.textContent.trim();

        // Get media containers
        const imgContainer = frame.querySelector('.img-container');
        const videoContainer = frame.querySelector('.video-container');

        if (!imgContainer || !videoContainer) {
            console.warn(`MediaSwitcher: Missing media containers for frame ${frameId}`);
            return;
        }

        // Define available media types based on frame type
        const mediaTypes = this.getMediaTypesForFrameType(frameType, imgContainer, videoContainer);

        if (mediaTypes.length > 1 || frameType === 'cut') {
            // Create switcher for this frame
            const switcher = new FrameMediaSwitcher(frameId, frameType, mediaTypes);
            this.frameSwitchers.set(frameId, switcher);

            // Default to video
            switcher.switchTo('video');
        } else {
            // Single media type - ensure it's visible and remove any existing switcher UI
            this.showSingleMediaType(mediaTypes[0]);
        }
    }

    getMediaTypesForFrameType(frameType, imgContainer, videoContainer) {
        if (frameType === 'cut') {
            return [
                {
                    key: 'start_frame',
                    label: 'start_frame',
                    container: imgContainer
                },
                {
                    key: 'video',
                    label: 'video',
                    container: videoContainer
                }
            ];
        } else {
            // continuous, callback, or other types only show video
            return [
                {
                    key: 'video',
                    label: 'video',
                    container: videoContainer
                }
            ];
        }
    }

    showSingleMediaType(mediaType) {
        // For single media types, just ensure the container is visible
        mediaType.container.style.display = 'block';

        // Remove any existing media buttons
        const existingButtons = mediaType.container.querySelector('.media-buttons');
        if (existingButtons) {
            existingButtons.remove();
        }
    }

    setupFrameTypeObserver() {
        // Watch for frame type changes to refresh switchers
        this.observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList' ||
                    (mutation.type === 'characterData' &&
                     mutation.target.parentElement &&
                     mutation.target.parentElement.classList.contains('frame-type-value'))) {

                    // Find the frame that changed
                    let frame = mutation.target;
                    while (frame && !frame.classList.contains('frame')) {
                        frame = frame.parentElement;
                    }

                    if (frame) {
                        const frameId = frame.dataset.frameId;
                        if (frameId) {
                            console.log(`MediaSwitcher: Frame type changed for ${frameId}, refreshing...`);
                            // Small delay to let other scripts finish their updates
                            setTimeout(() => {
                                this.setupFrameMediaSwitcher(frame);
                            }, 50);
                        }
                    }
                }
            });
        });

        this.observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    // Public method for external scripts to trigger refresh
    refreshSwitcher(frameId) {
        const frame = document.querySelector(`[data-frame-id="${frameId}"]`);
        if (frame) {
            console.log(`MediaSwitcher: Manually refreshing switcher for frame ${frameId}`);
            this.setupFrameMediaSwitcher(frame);
        }
    }

    destroy() {
        if (this.observer) {
            this.observer.disconnect();
        }

        this.frameSwitchers.forEach(switcher => switcher.destroy());
        this.frameSwitchers.clear();
    }
}

class FrameMediaSwitcher {
    constructor(frameId, frameType, mediaTypes) {
        this.frameId = frameId;
        this.frameType = frameType;
        this.mediaTypes = mediaTypes;
        this.currentMedia = null;
        this.buttonsContainer = null;

        console.log(`MediaSwitcher: Creating switcher for frame ${frameId} (${frameType}) with media:`, mediaTypes.map(m => m.key));

        this.createButtons();
    }

    createButtons() {
        // Only create buttons if we have multiple media types
        if (this.mediaTypes.length <= 1) return;

        // Create buttons container
        this.buttonsContainer = document.createElement('div');
        this.buttonsContainer.className = 'media-buttons';

        // Create button for each media type
        this.mediaTypes.forEach(mediaType => {
            const button = document.createElement('button');
            button.className = 'media-button';
            button.textContent = mediaType.label;
            button.dataset.mediaKey = mediaType.key;

            button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.switchTo(mediaType.key);
            });

            this.buttonsContainer.appendChild(button);
        });

        // Find a good container to attach buttons to
        // We'll attach to the first visible media container
        const visibleContainer = this.mediaTypes.find(m =>
            m.container.style.display !== 'none'
        )?.container || this.mediaTypes[0].container;

        // Position the container relatively if it isn't already
        const computedStyle = window.getComputedStyle(visibleContainer);
        if (computedStyle.position === 'static') {
            visibleContainer.style.position = 'relative';
        }

        visibleContainer.appendChild(this.buttonsContainer);
    }

    switchTo(mediaKey) {
        if (this.currentMedia === mediaKey) return;

        const previousMedia = this.currentMedia;

        console.log(`MediaSwitcher: Switching frame ${this.frameId} from ${previousMedia} to ${mediaKey}`);

        // Hide all media containers
        this.mediaTypes.forEach(mediaType => {
            mediaType.container.style.display = 'none';
        });

        // Show selected media container
        const selectedMediaType = this.mediaTypes.find(m => m.key === mediaKey);
        if (selectedMediaType) {
            selectedMediaType.container.style.display = 'block';

            // Move buttons to the now-visible container if needed
            if (this.buttonsContainer && this.buttonsContainer.parentElement !== selectedMediaType.container) {
                // Position the container relatively if it isn't already
                const computedStyle = window.getComputedStyle(selectedMediaType.container);
                if (computedStyle.position === 'static') {
                    selectedMediaType.container.style.position = 'relative';
                }
                selectedMediaType.container.appendChild(this.buttonsContainer);
            }
        }

        // Update button states
        if (this.buttonsContainer) {
            const allButtons = this.buttonsContainer.querySelectorAll('.media-button');
            allButtons.forEach(button => {
                if (button.dataset.mediaKey === mediaKey) {
                    button.classList.add('active');
                } else {
                    button.classList.remove('active');
                }
            });
        }

        this.currentMedia = mediaKey;

        // Trigger frame height adjustment if the function exists
        // This helps with layout recalculation after media switching
        if (typeof adjustFrameHeights === 'function') {
            setTimeout(() => {
                adjustFrameHeights();
            }, 50);
        }

        console.log(`MediaSwitcher: Successfully switched frame ${this.frameId} to ${mediaKey}`);
    }

    destroy() {
        if (this.buttonsContainer && this.buttonsContainer.parentElement) {
            this.buttonsContainer.remove();
        }

        // Restore all media containers to visible state
        this.mediaTypes.forEach(mediaType => {
            mediaType.container.style.display = '';
            mediaType.container.style.position = '';
        });

        console.log(`MediaSwitcher: Destroyed switcher for frame ${this.frameId}`);
    }
}

// Initialize when DOM is ready
let mediaSwitcher;
document.addEventListener('DOMContentLoaded', function() {
    mediaSwitcher = new MediaSwitcher();
    window.mediaSwitcher = mediaSwitcher; // Make globally accessible
});

// Export classes for external use
window.MediaSwitcher = MediaSwitcher;
window.FrameMediaSwitcher = FrameMediaSwitcher;
