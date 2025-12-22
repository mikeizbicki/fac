// Audio management system - Universal version
let currentAudio = null;
let currentAudioButton = null;

function initializeAudioControls() {
    const audioControls = document.querySelectorAll('.audio-controls');
    audioControls.forEach(control => {
        setupAudioControl(control);
    });
}

function setupAudioControl(audioControl) {
    // Check if button already exists
    let audioButton = audioControl.querySelector('.audio-button');

    // Create button if it doesn't exist
    if (!audioButton) {
        audioButton = document.createElement('button');
        audioButton.className = 'audio-button';
        audioButton.textContent = '🔊 Play Audio';
        audioButton.style.display = 'none'; // Hidden until we verify audio exists
        audioControl.appendChild(audioButton);
    }

    const audioPath = audioControl.dataset.audioPath;
    if (!audioPath) {
        console.warn('Audio control missing data-audio-path attribute');
        return;
    }

    // Check if audio file exists
    fetch(audioPath, { method: 'HEAD' })
        .then(response => {
            audioButton.style.display = response.ok ? 'block' : 'none';
        })
        .catch(() => {
            audioButton.style.display = 'none';
        });

    // Set up click handler
    audioButton.addEventListener('click', function() {
        handleAudioButtonClick(audioButton, audioPath);
    });
}

function handleAudioButtonClick(button, audioPath) {
    // If this is the currently playing audio, stop it
    if (currentAudio && currentAudioButton === button) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        button.textContent = '🔊 Play Audio';
        currentAudio = null;
        currentAudioButton = null;
        return;
    }

    // Stop any currently playing audio
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        if (currentAudioButton) {
            currentAudioButton.textContent = '🔊 Play Audio';
        }
    }

    // Start new audio
    const audio = new Audio(audioPath);
    currentAudio = audio;
    currentAudioButton = button;

    button.textContent = '⏹️ Audio Playing';

    audio.play().catch(e => {
        console.log('Audio playback failed:', e);
        button.textContent = '🔊 Play Audio';
        currentAudio = null;
        currentAudioButton = null;
    });

    // Reset button when audio ends
    audio.addEventListener('ended', () => {
        button.textContent = '🔊 Play Audio';
        currentAudio = null;
        currentAudioButton = null;
    });
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initializeAudioControls);

// Export function for manual initialization of new controls
window.initializeAudioControl = setupAudioControl;

