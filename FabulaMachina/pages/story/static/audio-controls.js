/* Audio Controls for Dialog Frames */
class DialogAudioControls {
    constructor() {
        this.level = null;
        this.story = null;
        this.init();
    }

    init() {
        // Get level and story from container
        const container = document.getElementById('story-container');
        if (container) {
            this.level = container.dataset.level;
            this.story = container.dataset.story;
        }
    }

    addAudioButtonsToDialogs() {
        const frames = document.querySelectorAll('.frame');

        frames.forEach(frame => {
            const frameId = frame.dataset.frameId;
            const audioPath = `/api/get_target/stories/${this.level}/${this.story}/frames/${frameId}/page.wav`;

            // Find all dialog divs in this frame
            const dialogDivs = frame.querySelectorAll('.frame-content div.dialog');

            dialogDivs.forEach(dialogDiv => {
                // Check if controls already exist
                if (dialogDiv.querySelector('.dialog-hover-controls')) return;

                // Find the last p tag in this dialog
                const pTags = dialogDiv.querySelectorAll('p');
                const lastP = pTags[pTags.length - 1];

                if (lastP) {
                    this.createDialogControls(lastP, audioPath, frameId);
                }
            });
        });
    }

    createDialogControls(lastP, audioPath, frameId) {
        // Create the hover controls container
        const controlsContainer = document.createElement('div');
        controlsContainer.className = 'dialog-hover-controls';

        // Create audio button (always visible when hovering)
        const audioButton = document.createElement('button');
        audioButton.className = 'dialog-audio-button';
        audioButton.innerHTML = '🔊 Play Audio';

        // Create FAC build controls
        const facControls = document.createElement('div');
        facControls.className = 'dialog-fac-controls';

        // Build button
        const buildBtn = document.createElement('button');
        buildBtn.className = 'dialog-fac-button';
        buildBtn.innerHTML = '🔨 Build Audio';
        buildBtn.title = 'Build audio if missing or out of date';

        // Rebuild button
        const rebuildBtn = document.createElement('button');
        rebuildBtn.className = 'dialog-fac-button';
        rebuildBtn.innerHTML = '🔄 Rebuild Audio';
        rebuildBtn.title = 'Force rebuild audio even if up to date';

        // Rebuild with notes button
        const notesBtn = document.createElement('button');
        notesBtn.className = 'dialog-fac-button';
        notesBtn.innerHTML = '📝 Rebuild with Notes';
        notesBtn.title = 'Rebuild audio with additional context';

        // Add click handlers for FAC buttons
        const facTarget = `stories/${this.level}/${this.story}/frames/${frameId}/page.wav`;

        buildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.triggerFacBuild(facTarget, false);
        });

        rebuildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.triggerFacBuild(facTarget, true);
        });

        notesBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const notes = prompt('Enter additional notes for the audio build:');
            if (notes !== null && notes.trim() !== '') {
                this.triggerFacBuild(facTarget, true, notes);
            }
        });

        // Assemble the controls
        facControls.appendChild(buildBtn);
        facControls.appendChild(rebuildBtn);
        facControls.appendChild(notesBtn);

        controlsContainer.appendChild(audioButton);
        controlsContainer.appendChild(facControls);

        // Insert after the last p tag
        lastP.parentNode.insertBefore(controlsContainer, lastP.nextSibling);

        // Check if audio file exists and set up accordingly
        this.checkAudioExists(audioPath, audioButton);
    }

    async checkAudioExists(audioPath, audioButton) {
        try {
            const response = await fetch(audioPath, { method: 'HEAD' });
            if (response.ok) {
                // Audio exists - set up normal audio control
                this.setupAudioButton(audioButton, audioPath);
            } else {
                // Audio doesn't exist - disable button
                this.setupDisabledAudioButton(audioButton);
            }
        } catch (error) {
            // Audio doesn't exist - disable button
            this.setupDisabledAudioButton(audioButton);
        }
    }

    setupAudioButton(audioButton, audioPath) {
        audioButton.disabled = false;
        audioButton.classList.remove('disabled');

        // Set up click handler using existing audio system
        audioButton.addEventListener('click', () => {
            this.handleAudioButtonClick(audioButton, audioPath);
        });
    }

    setupDisabledAudioButton(audioButton) {
        audioButton.disabled = true;
        audioButton.classList.add('disabled');
        audioButton.innerHTML = '🔇 No Audio Available';
    }

    handleAudioButtonClick(button, audioPath) {
        // Use the existing global audio system from audio.js
        if (window.handleAudioButtonClick) {
            window.handleAudioButtonClick(button, audioPath);
        } else {
            // Fallback implementation
            console.warn('Global audio system not available, using fallback');
            this.fallbackAudioHandler(button, audioPath);
        }
    }

    fallbackAudioHandler(button, audioPath) {
        // Simple fallback if audio.js isn't available
        const audio = new Audio(audioPath);
        const originalText = button.innerHTML;

        button.innerHTML = '⏹️ Stop Audio';
        button.disabled = true;

        audio.play().then(() => {
            audio.addEventListener('ended', () => {
                button.innerHTML = originalText;
                button.disabled = false;
            });
        }).catch(err => {
            console.error('Audio playback failed:', err);
            button.innerHTML = '🔊 Audio Error';
            setTimeout(() => {
                button.innerHTML = originalText;
                button.disabled = false;
            }, 2000);
        });
    }

    triggerFacBuild(target, overwrite = false, notes = null) {
        // Use existing FAC build system if available
        if (window.facBuildSystem) {
            window.facBuildSystem.triggerBuild(target, overwrite, notes);
        } else {
            console.warn('FAC build system not available');
            alert('Build system not available. Please reload the page.');
        }
    }

    // Method to refresh audio buttons (call after content updates)
    refresh() {
        // Remove existing controls first
        this.removeAllAudioButtons();
        // Add new ones
        this.addAudioButtonsToDialogs();
    }

    // Method to remove all audio buttons (useful for cleanup)
    removeAllAudioButtons() {
        const dialogControls = document.querySelectorAll('.dialog-hover-controls');
        dialogControls.forEach(control => control.remove());
    }
}

// Initialize audio controls when DOM is ready
let dialogAudioControls = null;

document.addEventListener('DOMContentLoaded', function() {
    // Wait a bit to ensure other scripts are loaded
    setTimeout(() => {
        dialogAudioControls = new DialogAudioControls();
        dialogAudioControls.addAudioButtonsToDialogs();
    }, 500);
});

// Export for use in other scripts
window.DialogAudioControls = DialogAudioControls;
window.dialogAudioControls = dialogAudioControls;

