document.addEventListener('keydown', function(event) {
  // Check if arrow keys or page up/down were pressed
  if (event.keyCode === 40 || event.key === 'ArrowDown' ||
      event.keyCode === 38 || event.key === 'ArrowUp' ||
      event.keyCode === 33 || event.key === 'PageUp' ||
      event.keyCode === 34 || event.key === 'PageDown') {

    // Prevent default scrolling behavior
    event.preventDefault();

    // Find the current position
    const scrollPosition = window.scrollY;
    let targetHeading = null;

    // Handle arrow keys (all h tags)
    if (event.keyCode === 40 || event.key === 'ArrowDown' ||
        event.keyCode === 38 || event.key === 'ArrowUp') {
      // Get all heading elements
      const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');

      if (event.keyCode === 40 || event.key === 'ArrowDown') {
        // DOWN ARROW: Find the next heading to scroll to
        for (let i = 0; i < headings.length; i++) {
          const headingPosition = headings[i].getBoundingClientRect().top + window.scrollY;

          // If this heading is below current position, scroll to it
          if (headingPosition > scrollPosition + 10) {
            targetHeading = headings[i];
            break;
          }
        }
      }
      else if (event.keyCode === 38 || event.key === 'ArrowUp') {
        // UP ARROW: Find the previous heading to scroll to
        let previousHeading = null;

        for (let i = 0; i < headings.length; i++) {
          const headingPosition = headings[i].getBoundingClientRect().top + window.scrollY;

          // If this heading is at or above current position (with small buffer)
          if (headingPosition < scrollPosition - 10) {
            previousHeading = headings[i];
          } else {
            break; // We've gone past the current position
          }
        }

        // If we found a previous heading, use it
        if (previousHeading) {
          targetHeading = previousHeading;
        }
      }
    }
    // Handle Page Up/Down (only h2 tags)
    else if (event.keyCode === 33 || event.key === 'PageUp' ||
             event.keyCode === 34 || event.key === 'PageDown') {
      // Get only h2 elements
      const h2Headings = document.querySelectorAll('h2');

      if (event.keyCode === 34 || event.key === 'PageDown') {
        // PAGE DOWN: Find the next h2 to scroll to
        for (let i = 0; i < h2Headings.length; i++) {
          const headingPosition = h2Headings[i].getBoundingClientRect().top + window.scrollY;

          // If this h2 is below current position, scroll to it
          if (headingPosition > scrollPosition + 10) {
            targetHeading = h2Headings[i];
            break;
          }
        }
      }
      else if (event.keyCode === 33 || event.key === 'PageUp') {
        // PAGE UP: Find the previous h2 to scroll to
        let previousHeading = null;

        for (let i = 0; i < h2Headings.length; i++) {
          const headingPosition = h2Headings[i].getBoundingClientRect().top + window.scrollY;

          // If this h2 is at or above current position (with small buffer)
          if (headingPosition < scrollPosition - 10) {
            previousHeading = h2Headings[i];
          } else {
            break; // We've gone past the current position
          }
        }

        // If we found a previous h2, use it
        if (previousHeading) {
          targetHeading = previousHeading;
        }
      }
    }

    // Scroll to the target heading if one was found
    if (targetHeading) {
      //targetHeading.scrollIntoView({behavior: 'smooth'});
      targetHeading.scrollIntoView({behavior: 'instant'});
    }
  }
});
