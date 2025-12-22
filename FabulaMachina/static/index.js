document.addEventListener('DOMContentLoaded', function() {
    // Handle collapsible sections
    document.querySelectorAll('.section-header').forEach(header => {
        header.addEventListener('click', function() {
            const targetId = this.dataset.target;
            const content = document.getElementById(targetId);
            const triangle = this.querySelector('.triangle');
            
            if (content.classList.contains('expanded')) {
                content.classList.remove('expanded');
                triangle.classList.remove('expanded');
            } else {
                content.classList.add('expanded');
                triangle.classList.add('expanded');
            }
        });
    });

    // Handle URL hash to auto-expand sections
    function handleHash() {
        const hash = window.location.hash;
        if (hash) {
            const sectionId = hash.substring(1) + '-section';
            const section = document.getElementById(sectionId);
            if (section) {
                section.classList.add('expanded');
                const header = document.querySelector(`[data-target="${sectionId}"]`);
                if (header) {
                    header.querySelector('.triangle').classList.add('expanded');
                }
            }
        }
    }

    // Handle hash on page load
    handleHash();

    // Handle hash changes
    window.addEventListener('hashchange', handleHash);
});

