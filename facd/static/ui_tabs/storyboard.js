// storyboard.js
//
// Horizontal orientation of the unified screenplay view. All logic
// lives in screenplay_view.js; this file just registers the tab.

(function() {
    const view = window.ScreenplayView.createView('horizontal');
    window.registerTab({
        id: 'storyboard',
        label: 'Storyboard',
        pane: 'main',
        render: view.init,
    });
})();
