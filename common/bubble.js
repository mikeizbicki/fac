(function() {
  function initSpeechBubble() {
    try {
      // Create and append speech bubble element
      const speechBubble = document.createElement('div');
      speechBubble.id = 'word-speech-bubble';
      document.body.appendChild(speechBubble);

      // Track the currently active word span
      let activeWordSpan = null;

      // Process text nodes - wrap words in spans
      function processTextNodes() {
        // Get all text-containing elements
        const textElements = document.querySelectorAll('p, h1, h2, h3, h4, h5, h6, span, div, a, li');

        textElements.forEach(function(element) {
          // Skip elements that already have been processed
          if (element.getAttribute('data-word-hover-processed') === 'true') return;
          if (element.closest('script, style')) return; // Skip script and style elements

          element.setAttribute('data-word-hover-processed', 'true');

          // Don't process if this is already a word span we created
          if (element.classList.contains('word-hover-span')) return;

          const text = element.textContent.trim();
          if (!text) return;

          // Don't process elements with no direct text nodes
          let hasDirectTextNode = false;
          for (let i = 0; i < element.childNodes.length; i++) {
            if (element.childNodes[i].nodeType === Node.TEXT_NODE &&
                element.childNodes[i].textContent.trim()) {
              hasDirectTextNode = true;
              break;
            }
          }
          if (!hasDirectTextNode) return;

          // Replace text nodes with wrapped words
          const childNodes = Array.from(element.childNodes);

          childNodes.forEach(function(node) {
            if (node.nodeType === Node.TEXT_NODE) {
              const words = node.textContent.split(/(\s+)/); // Split by whitespace but keep separators
              const fragment = document.createDocumentFragment();

              words.forEach(function(word) {
                if (word.trim()) {
                  // Create container for word and its bubble
                  const container = document.createElement('span');
                  container.classList.add('word-container');
                  container.style.display = 'inline-block';
                  container.style.position = 'relative';
                  
                  // Create span for the word
                  const span = document.createElement('span');
                  span.textContent = word;
                  span.classList.add('word-hover-span');
                  
                  // Create bubble for this word
                  const bubble = document.createElement('div');
                  bubble.classList.add('word-speech-bubble');
                  bubble.textContent = word.trim();
                  
                  // Append everything
                  container.appendChild(span);
                  container.appendChild(bubble);
                  fragment.appendChild(container);
                } else {
                  // Preserve whitespace
                  fragment.appendChild(document.createTextNode(word));
                }
              });

              node.parentNode.replaceChild(fragment, node);
            }
          });
        });
      }

      // Handle mouse leaving the word or bubble
      document.addEventListener('mouseover', function(e) {
        if (e.target.classList.contains('word-hover-span')) {
          // Already handled by the mouseenter event
        } else if (e.target !== speechBubble && !speechBubble.contains(e.target)) {
          // Mouse is not over a word span or the bubble
          speechBubble.style.display = 'none';
          activeWordSpan = null;
        }
      });

      // Add event listener to the bubble itself
      speechBubble.addEventListener('mouseleave', function() {
        if (!activeWordSpan) {
          speechBubble.style.display = 'none';
        }
      });

      // Initial setup
      processTextNodes();

      // Setup mutation observer to handle dynamically added content
      const observer = new MutationObserver(function(mutations) {
        processTextNodes();
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true
      });

      console.log('Word speech bubble initialized successfully');
    } catch (error) {
      console.error('Error initializing word speech bubble:', error);
    }
  }

  // Wait for DOM to be fully loaded before initializing
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSpeechBubble);
  } else {
    // DOM is already ready
    initSpeechBubble();
  }
})();


function adjustBubblePosition() {
  document.querySelectorAll('.word-speech-bubble').forEach(bubble => {
    const rect = bubble.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

    // Adjust horizontal position if needed
    if (rect.right > viewportWidth) {
      const overflow = rect.right - viewportWidth;
      bubble.style.left = `-${overflow}px`;
    }

    // Adjust vertical position if needed
    if (rect.bottom > viewportHeight) {
      bubble.style.top = 'auto';
      bubble.style.bottom = '100%';
    }
  });
}

// Add event listener to check positions on hover
document.addEventListener('mouseover', function(e) {
  if (e.target.classList.contains('word-hover-span') ||
      e.target.classList.contains('word-speech-bubble')) {
    // Use requestAnimationFrame for performance
    requestAnimationFrame(adjustBubblePosition);
  }
});
