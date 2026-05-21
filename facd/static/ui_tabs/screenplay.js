// screenplay.js
//
// Vertical orientation of the unified screenplay view.
// All logic lives in screenplay_view.js / screenplay_stickynote.js /
// screenplay_common.js; this file just registers the tab.

(function() {
    const view = window.ScreenplayView.createView('vertical');
    window.registerTab({
        id: 'screenplay',
        label: 'Screenplay',
        pane: 'main',
        render: view.init,
    });
})();
