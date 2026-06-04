// screenplay_stickynote.js
//
// Shared sticky-note rendering for screenplay-like views (screenplay.js,
// storyboard.js, screenplay_view.js). Each sticky note shows metadata
// for one beat plus its related build targets (beat_type,
// length_seconds, startframe.png, raw.mp4) using the nodes.js API.
//
// All registered paths for a view are tracked in a Set that the caller
// owns, so the view can unregister cleanly on re-render.

(function() {
    // Cache of the /list_targets response. The targets displayed in
    // each sticky note are derived dynamically from this data, so as
    // the backend's fac.yaml changes, sticky notes pick up new
    // targets/subfolders without any code changes here.
    let _targetsCache = null;
    let _targetsPromise = null;
    function getTargets() {
        if (_targetsCache) return Promise.resolve(_targetsCache);
        if (_targetsPromise) return _targetsPromise;
        _targetsPromise = fetch('/list_targets')
            .then(r => r.json())
            .then(data => { _targetsCache = data; return data; })
            .catch(err => {
                console.error('Failed to load /list_targets:', err);
                _targetsPromise = null;
                return {};
            });
        return _targetsPromise;
    }
    // Kick off the fetch eagerly at module load time so the first
    // sticky-note render usually finds the data already cached.
    getTargets();

    // Shared IntersectionObserver: defers blob fetches for media
    // wrappers until they actually scroll into view. Without this,
    // initial screenplay load fires hundreds of fetchImage/fetchVideo
    // calls at once (across both vertical and horizontal views),
    // which bogs down the browser for many seconds. Each registered
    // element carries a _lazyFetch callback we invoke once when it
    // first becomes visible, then we stop observing it.
    let _lazyObserver = null;
    function _getLazyObserver() {
        if (_lazyObserver) return _lazyObserver;
        if (typeof IntersectionObserver === 'undefined') return null;
        _lazyObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                const el = entry.target;
                const fn = el._lazyFetch;
                if (fn) {
                    el._lazyFetch = null;
                    try { fn(); } catch (e) { console.error(e); }
                }
                _lazyObserver.unobserve(el);
            });
        }, { rootMargin: '200px' });
        return _lazyObserver;
    }
    function _scheduleLazyFetch(el, fn) {
        const obs = _getLazyObserver();
        if (!obs) {
            // No IntersectionObserver support: fall back to a small
            // setTimeout so we at least don't block the initial paint.
            setTimeout(fn, 0);
            return;
        }
        el._lazyFetch = fn;
        obs.observe(el);
    }
    function _cancelLazyFetch(el) {
        if (!el) return;
        el._lazyFetch = null;
        const obs = _lazyObserver;
        if (obs) obs.unobserve(el);
    }

    // Global subfolder open-state. Opening a subfolder reveals it on
    // EVERY sticky note simultaneously. To restrict this to a single
    // sticky, swap _currentOpenSubfolder for a per-sticky local
    // variable and update toggleSubfolder/applyOpenSubfolder
    // accordingly.
    let _currentOpenSubfolder = null;
    function toggleSubfolder(name) {
        _currentOpenSubfolder =
            (_currentOpenSubfolder === name) ? null : name;
        applyOpenSubfolder();
    }
    function closeSubfolder() {
        _currentOpenSubfolder = null;
        applyOpenSubfolder();
    }
    function applyOpenSubfolder() {
        document.querySelectorAll('.sticky-subfolder-panel')
            .forEach(panel => {
                panel.classList.toggle(
                    'open',
                    panel.dataset.subfolder === _currentOpenSubfolder);
            });
    }

    // Track every concrete path we've seen via SSE that lives under
    // beats/<beat_id>/... . These are the "resolved" paths for
    // variable target patterns like beats/$BEAT_ID/dialog/$LANG.wav,
    // and we want to display them inside the sticky-note folder tree
    // alongside the (still-variable) target patterns from
    // /list_targets.
    //
    // Map: beat_id -> Map(path -> mimeType)
    const _beatPaths = new Map();
    function _recordBeatPath(path, mimeType) {
        const m = path.match(/^beats\/([^/]+)\/(.+)$/);
        if (!m) return null;
        const beat_id = m[1];
        let inner = _beatPaths.get(beat_id);
        if (!inner) {
            inner = new Map();
            _beatPaths.set(beat_id, inner);
        }
        const existed = inner.has(path);
        inner.set(path, mimeType || '');
        return { beat_id, isNew: !existed };
    }
    function _getBeatPaths(beat_id) {
        return _beatPaths.get(beat_id) || new Map();
    }

    // Debounce repopulate calls. During initial SSE replay we can
    // see hundreds of beats/* events back-to-back; calling
    // _repopulateBeatStickies synchronously on each one pegs the
    // main thread (each call re-walks /list_targets, tears down and
    // re-creates DOM for every on-screen sticky for that beat, and
    // re-registers blob-cache containers). Coalesce dirty beat_ids
    // into a Set drained on the next macrotask so we do at most one
    // repopulate per beat per burst.
    const _dirtyBeats = new Set();
    let _repopulateTimer = null;
    function _scheduleRepopulate(beat_id) {
        _dirtyBeats.add(beat_id);
        if (_repopulateTimer !== null) return;
        _repopulateTimer = setTimeout(() => {
            _repopulateTimer = null;
            const ids = Array.from(_dirtyBeats);
            _dirtyBeats.clear();
            for (const id of ids) {
                try { _repopulateBeatStickies(id); }
                catch (e) { console.error(e); }
            }
        }, 100);
    }

    // Register a global SSE handler so we learn about every
    // beats/<beat_id>/... path the backend reports, even before any
    // sticky note for that beat has been rendered. Without this, the
    // per-view path handler in screenplay_view.js only forwards
    // events for paths already in its registeredPaths set, which
    // never includes resolved variable-target paths until they
    // appear on screen -- a chicken-and-egg.
    if (window.registerPathHandler) {
        window.registerPathHandler(function(path, metadata) {
            if (!/^beats\//.test(path)) return;
            const r = _recordBeatPath(path, metadata && metadata['mime-type']);
            if (r && r.isNew) _scheduleRepopulate(r.beat_id);
        });
    }

    // Given /list_targets data and a concrete beat_id, return an
    // ordered list describing what to render in the media section:
    //   - { type: 'direct',    name, path, mimeType }
    //   - { type: 'subfolder', name, items: [...] }  (recursively nested)
    // Targets that still contain unsubstituted variables (besides
    // $BEAT_ID) after substitution are displayed as-is with their
    // variable names visible in the path; they represent target
    // patterns rather than concrete file paths.
    // Item order matches first-appearance order in /list_targets.
    function processBeatTargets(targetsData, beat_id, knownPaths) {
        const prefix = 'beats/$BEAT_ID/';
        // Build the entry list in /list_targets order. For each
        // target pattern, immediately follow it with the alphabetic
        // list of concrete paths (from SSE) that resolve it, so the
        // resolutions visually sit underneath their pattern.
        const entries = [];
        const claimedPaths = new Set();
        const targetEntries = []; // [{ target, suffix, path, mimeType }, ...]
        for (const [target, config] of Object.entries(targetsData || {})) {
            if (!target.startsWith(prefix)) continue;
            const suffix = target.substring(prefix.length);
            const path = target.replace(/\$BEAT_ID/g, beat_id);
            const mimeType = (config && config['mime-type']) || '';
            targetEntries.push({ target, suffix, path, mimeType });
        }

        // Build a regex per target pattern (anchored, $VAR -> [^/]+).
        function targetToRegex(targetSuffix) {
            const escaped = targetSuffix
                .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
                .replace(/\\\$[A-Z_][A-Z0-9_]*/g, '([^/]+)');
            return new RegExp('^' + escaped + '$');
        }

        const beatPrefix = 'beats/' + beat_id + '/';
        for (const te of targetEntries) {
            entries.push({
                parts: te.suffix.split('/'),
                path: te.path,
                mimeType: te.mimeType,
            });
            if (!knownPaths) continue;
            // Find resolutions of this target pattern: concrete
            // paths under beats/<beat_id>/ whose suffix matches the
            // target's regex but that aren't equal to the (already-
            // emitted) literal target path.
            const re = targetToRegex(te.suffix);
            const resolutions = [];
            for (const [p, mt] of knownPaths) {
                if (claimedPaths.has(p)) continue;
                if (p === te.path) {
                    claimedPaths.add(p);
                    continue;
                }
                if (!p.startsWith(beatPrefix)) continue;
                const sfx = p.substring(beatPrefix.length);
                if (!re.test(sfx)) continue;
                resolutions.push({ p, mt, sfx });
                claimedPaths.add(p);
            }
            resolutions.sort((a, b) => a.p < b.p ? -1 : a.p > b.p ? 1 : 0);
            for (const r of resolutions) {
                entries.push({
                    parts: r.sfx.split('/'),
                    path: r.p,
                    mimeType: r.mt,
                });
            }
        }

        // Any concrete paths that didn't match any target pattern
        // (shouldn't normally happen, but be safe) are appended at
        // the end in alphabetic order.
        if (knownPaths) {
            const leftovers = [];
            for (const [p, mt] of knownPaths) {
                if (claimedPaths.has(p)) continue;
                if (!p.startsWith(beatPrefix)) continue;
                leftovers.push({ p, mt });
            }
            leftovers.sort((a, b) => a.p < b.p ? -1 : a.p > b.p ? 1 : 0);
            for (const r of leftovers) {
                const sfx = r.p.substring(beatPrefix.length);
                entries.push({
                    parts: sfx.split('/'),
                    path: r.p,
                    mimeType: r.mt,
                });
            }
        }

        // Recursively bucket entries into items/subfolders based on
        // the first path component. Subfolder order is the order in
        // which the subfolder name first appears.
        function build(entries) {
            const items = [];
            const subfolderMap = new Map();
            for (const e of entries) {
                if (e.parts.length === 1) {
                    items.push({
                        type: 'direct',
                        name: e.parts[0],
                        path: e.path,
                        mimeType: e.mimeType,
                    });
                } else {
                    const subName = e.parts[0];
                    let folder = subfolderMap.get(subName);
                    if (!folder) {
                        folder = {
                            type: 'subfolder',
                            name: subName,
                            _entries: [],
                        };
                        subfolderMap.set(subName, folder);
                        items.push(folder);
                    }
                    folder._entries.push({
                        parts: e.parts.slice(1),
                        path: e.path,
                        mimeType: e.mimeType,
                    });
                }
            }
            // Recurse into each subfolder.
            for (const item of items) {
                if (item.type === 'subfolder') {
                    item.items = build(item._entries);
                    delete item._entries;
                }
            }
            return items;
        }
        return build(entries);
    }

    function isBeatTargetPath(path) {
        return /^beats\//.test(path);
    }

    function createMetaRow(label, value, options) {
        const row = document.createElement('div');
        row.className = 'sticky-meta-row';
        const labelSpan = document.createElement('span');
        labelSpan.className = 'sticky-meta-label';
        labelSpan.textContent = label;
        row.appendChild(labelSpan);
        const valueSpan = document.createElement('span');
        valueSpan.className = 'sticky-meta-value';
        valueSpan.textContent = value;
        row.appendChild(valueSpan);
        if (options && options.editable) {
            row.classList.add('sticky-meta-editable');
            attachBeatRefDropdown(row, options);
        }
        return row;
    }

    // Attach a hover-activated dropdown menu to a meta row that lets
    // the user reassign a beat reference field (continues_from_beat_id
    // or include_beat_id). The dropdown lists all previous beats (plus
    // a "no beat_id" option at the top) with their startframe.png
    // thumbnails. Clicking an entry rewrites the XML; the SSE update
    // triggers the re-render.
    function attachBeatRefDropdown(row, opts) {
        // opts: { field, currentValue, beat, beats, orientation,
        //         onSelect(newValue) }
        const { field, currentValue, beat, beats, orientation, onSelect } = opts;

        let menu = null;
        let outsideClickHandler = null;

        function closeMenu() {
            if (menu && menu.parentElement) menu.parentElement.removeChild(menu);
            menu = null;
            if (outsideClickHandler) {
                document.removeEventListener('mousedown', outsideClickHandler, true);
                outsideClickHandler = null;
            }
        }

        function buildMenu() {
            const m = document.createElement('div');
            m.className = 'sticky-beatref-menu';
            m.dataset.orientation = orientation || 'vertical';

            // Build entry list: "none" first, then all beats that come
            // before `beat` in the beats array.
            const entries = [{ beat_id: '', label: '— (no beat_id)' }];
            const myIdx = beats.findIndex(b => b.beat_id === beat.beat_id);
            for (let i = 0; i < myIdx; i++) {
                entries.push({ beat_id: beats[i].beat_id, label: beats[i].beat_id });
            }

            let selectedEl = null;
            entries.forEach(entry => {
                const item = document.createElement('div');
                item.className = 'sticky-beatref-item';
                if (entry.beat_id === (currentValue || '')) {
                    item.classList.add('selected');
                    selectedEl = item;
                }

                const idLabel = document.createElement('div');
                idLabel.className = 'sticky-beatref-id';
                idLabel.textContent = entry.beat_id || '—';
                item.appendChild(idLabel);

                const thumb = document.createElement('div');
                thumb.className = 'sticky-beatref-thumb';
                if (!entry.beat_id) {
                    thumb.classList.add('sticky-beatref-thumb-empty');
                    thumb.textContent = 'no beat_id';
                } else {
                    const targetPath = 'beats/' + entry.beat_id
                        + '/beat_type=standard/startframe.png';
                    thumb.dataset.path = targetPath;
                    const imgContainer = document.createElement('div');
                    imgContainer.className = 'image-container';
                    thumb.appendChild(imgContainer);

                    const overlay = document.createElement('div');
                    overlay.className = 'node-status-overlay';
                    const overlayText = document.createElement('div');
                    overlayText.className = 'node-status-overlay-text';
                    overlay.appendChild(overlayText);
                    thumb.appendChild(overlay);

                    const state = window.getPathState && window.getPathState(targetPath);
                    const status = (state && state.status) || 'notbuilt';
                    thumb.dataset.status = status;
                    overlayText.textContent = status.toUpperCase();

                    if (window.registerImageContainer) {
                        window.registerImageContainer(targetPath, imgContainer, 'leaf-image');
                    }
                    if (status !== 'notbuilt' && window.fetchImage) {
                        window.fetchImage(targetPath, false).then(url => {
                            if (window._refreshImageContainers) {
                                window._refreshImageContainers(targetPath, url);
                            }
                        }).catch(() => {});
                    }
                }
                item.appendChild(thumb);

                item.addEventListener('click', e => {
                    e.stopPropagation();
                    if (entry.beat_id === (currentValue || '')) return;
                    onSelect(entry.beat_id);
                    closeMenu();
                });
                m.appendChild(item);
            });

            row.appendChild(m);

            // Center the selected entry within the menu's scroll area.
            if (selectedEl) {
                if (m.dataset.orientation === 'horizontal') {
                    m.scrollLeft = selectedEl.offsetLeft
                        - (m.clientWidth / 2) + (selectedEl.offsetWidth / 2);
                } else {
                    m.scrollTop = selectedEl.offsetTop
                        - (m.clientHeight / 2) + (selectedEl.offsetHeight / 2);
                }
            }
            clampMenuToViewport(m);
            return m;
    // After the menu has been appended and its centering transform
    // applied, measure where it actually sits in the viewport and
    // nudge it (via an additional inline translate) so it is fully
    // visible. This may shift it off-center but ensures it isn't
    // clipped against any edge of the viewport.
    function clampMenuToViewport(m) {
        // Defer one frame so layout is settled.
        requestAnimationFrame(() => {
            const rect = m.getBoundingClientRect();
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const margin = 4;
            let dx = 0, dy = 0;
            if (rect.left < margin) {
                dx = margin - rect.left;
            } else if (rect.right > vw - margin) {
                dx = (vw - margin) - rect.right;
            }
            if (rect.top < margin) {
                dy = margin - rect.top;
            } else if (rect.bottom > vh - margin) {
                dy = (vh - margin) - rect.bottom;
            }
            if (dx === 0 && dy === 0) return;
            // Preserve the existing centering transform from the
            // stylesheet by appending a new translate. We read the
            // computed transform so we can compose, but since the
            // centering is a pure translate set via CSS, we instead
            // detect orientation and re-apply the right composition.
            const orient = m.dataset.orientation;
            if (orient === 'horizontal') {
                // Original: translateX(-50%). Add pixel offsets.
                m.style.transform =
                    `translateX(-50%) translate(${dx}px, ${dy}px)`;
            } else {
                // Original: translateY(-50%). Add pixel offsets.
                m.style.transform =
                    `translateY(-50%) translate(${dx}px, ${dy}px)`;
            }
        });
    }

        }

        row.addEventListener('click', e => {
            e.stopPropagation();
            if (menu) {
                closeMenu();
                return;
            }
            menu = buildMenu();
            // Install an outside-click handler that closes the menu
            // whenever the user clicks anywhere that isn't the menu
            // or this row.
            outsideClickHandler = (ev) => {
                if (!menu) return;
                if (menu.contains(ev.target) || row.contains(ev.target)) return;
                closeMenu();
            };
            document.addEventListener('mousedown', outsideClickHandler, true);
        });
        return row;
    }

    // Build a header bar with filename + build/delete buttons for a
    // sticky-media-wrapper. This duplicates the relevant bits of
    // build.js's tree-node header menu without depending on the
    // tree-node DOM, because sticky wrappers intentionally don't
    // reuse tree-nodes (see comment in createMediaNode).
    function createMediaHeader(targetPath, filename, mimeType) {
        const header = document.createElement('div');
        header.className = 'sticky-media-header';

        const label = document.createElement('span');
        label.className = 'sticky-media-label';
        label.textContent = filename;
        header.appendChild(label);

        const menu = document.createElement('div');
        menu.className = 'sticky-media-menu';

        const buildBtn = document.createElement('button');
        buildBtn.innerHTML = '🔨';
        buildBtn.title = 'Build';
        buildBtn.addEventListener('click', e => {
            e.stopPropagation();
            // Optimistic state update on every sticky wrapper for this path.
            document.querySelectorAll(
                `.sticky-media-wrapper[data-path="${targetPath}"]`)
                .forEach(w => { w.dataset.status = 'command_sent(build)'; });
            fetch('/add_target', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: targetPath }),
            }).then(r => {
                if (!r.ok) throw new Error('Failed to queue build');
                return r.json();
            }).catch(err => {
                console.error('Error queuing build:', err);
                alert('Failed to queue build: ' + err.message);
            });
        });
        menu.appendChild(buildBtn);

        // Edit button for text-backed targets. The actual edit UI is
        // wired up in createMediaNode (which owns the text container)
        // via the data-edit-trigger attribute.
        if (mimeType && mimeType.startsWith('text/')) {
            const editBtn = document.createElement('button');
            editBtn.innerHTML = '✏️';
            editBtn.title = 'Edit';
            editBtn.dataset.editTrigger = targetPath;
            editBtn.addEventListener('click', e => {
                e.stopPropagation();
                startStickyTextEdit(targetPath, editBtn);
            });
            menu.appendChild(editBtn);
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = 'Delete';
        deleteBtn.addEventListener('click', e => {
            e.stopPropagation();
            if (!confirm(`Are you sure you want to delete "${targetPath}"?`)) return;
            document.querySelectorAll(
                `.sticky-media-wrapper[data-path="${targetPath}"]`)
                .forEach(w => { w.dataset.status = 'command_sent(delete)'; });
            fetch(`/delete_file/${encodeURIComponent(targetPath)}`, { method: 'DELETE' })
                .then(r => {
                    if (!r.ok) throw new Error('Failed to delete file');
                    return r.json();
                }).catch(err => {
                    console.error('Error deleting file:', err);
                    alert('Failed to delete file: ' + err.message);
                });
        });
        menu.appendChild(deleteBtn);

        header.appendChild(menu);
        return header;
    }

    // Inline-edit a text-backed sticky-media wrapper. Mirrors the
    // flow in build.js for tree-node text editing, but operates on
    // the .sticky-text-content element inside the wrapper. Edits
    // the specific wrapper containing the edit button that was
    // clicked (located via closest()), so clicking the button in
    // either view edits that view's wrapper.
    function startStickyTextEdit(targetPath, triggerEl) {
        const wrapper = triggerEl
            && triggerEl.closest('.sticky-media-wrapper');
        if (!wrapper) return;
        const textContainer = wrapper.querySelector('.sticky-text-content');
        if (!textContainer) return;
        if (wrapper.dataset.editing === 'true') return;
        wrapper.dataset.editing = 'true';

        const originalText = textContainer.textContent === '—'
            ? '' : textContainer.textContent;

        const textarea = document.createElement('textarea');
        textarea.className = 'sticky-text-editor';
        textarea.value = originalText;

        const actions = document.createElement('div');
        actions.className = 'sticky-text-edit-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'sticky-text-cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', e => {
            e.stopPropagation();
            textarea.remove();
            actions.remove();
            textContainer.style.display = '';
            wrapper.dataset.editing = 'false';
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'sticky-text-submit';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', e => {
            e.stopPropagation();
            submitBtn.disabled = true;
            cancelBtn.disabled = true;
            wrapper.dataset.status = 'command_sent(edit)';
            fetch(`/edit_file/${encodeURIComponent(targetPath)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: textarea.value }),
            }).then(r => {
                if (!r.ok) throw new Error('Failed to edit file');
                return r.json();
            }).then(() => {
                // SSE-driven handleTargetUpdate will repaint content.
                textarea.remove();
                actions.remove();
                textContainer.style.display = '';
                wrapper.dataset.editing = 'false';
            }).catch(err => {
                console.error('Error editing file:', err);
                alert('Failed to edit file: ' + err.message);
                submitBtn.disabled = false;
                cancelBtn.disabled = false;
            });
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        textContainer.style.display = 'none';
        textContainer.parentElement.insertBefore(textarea, textContainer.nextSibling);
        textContainer.parentElement.insertBefore(actions, textarea.nextSibling);
        textarea.focus();
    }

    function createMediaNode(targetPath, filename, mimeType, registeredPaths) {
        // Build a self-contained sticky-media display: a media
        // container (image/video) plus a status overlay that mirrors
        // the tree-node overlay system. We deliberately do NOT use
        // createNode / cloneNode here -- earlier versions tried to
        // reuse the tree-node from the targets tab so they could share
        // the build/edit/delete header menu, but this caused three
        // related bugs:
        //   1. The first sticky view (vertical) registered as the
        //      "real" node; later views (horizontal) cloned the DOM
        //      with cloneNode(true), which doesn't copy event
        //      handlers and doesn't get future updateNode() updates.
        //      That left the horizontal view with a permanent stale
        //      status overlay and broken header buttons.
        //   2. The cloned tree-node carried a clickable expand/
        //      collapse header which broke screenplay layout (and
        //      moved sticky positions out from under arrow anchors).
        //   3. The display:none hidden tree-nodes inside meta rows
        //      added complexity for no UI benefit.
        // The new wrapper is purely a media+overlay surface, with no
        // tree-node coupling.
        const wrapper = document.createElement('div');
        wrapper.className = 'sticky-media-wrapper';
        wrapper.dataset.path = targetPath;
        wrapper.dataset.mimeType = mimeType;

        // Header (filename + build/delete buttons).
        wrapper.appendChild(createMediaHeader(targetPath, filename, mimeType));

        const isImage = mimeType.startsWith('image/');
        const isVideo = mimeType.startsWith('video/');
        const isAudio = mimeType.startsWith('audio/');
        const isText = mimeType.startsWith('text/');
        if (isImage) wrapper.classList.add('has-image');
        else if (isVideo) wrapper.classList.add('has-video');
        else if (isAudio) wrapper.classList.add('has-audio');
        else if (isText) wrapper.classList.add('has-text');

        const mediaContainer = document.createElement('div');
        mediaContainer.className = isImage
            ? 'image-container'
            : (isVideo ? 'video-container'
               : (isAudio ? 'audio-container' : 'text-container'));
        wrapper.appendChild(mediaContainer);

        // Status overlay. data-status on .sticky-media-wrapper drives
        // its visibility via overlay.css, matching the tree-node UX.
        const overlay = document.createElement('div');
        overlay.className = 'node-status-overlay';
        const overlayText = document.createElement('div');
        overlayText.className = 'node-status-overlay-text';
        overlay.appendChild(overlayText);
        wrapper.appendChild(overlay);

        const state = window.getPathState && window.getPathState(targetPath);
        const status = (state && state.status) || 'notbuilt';
        wrapper.dataset.status = status;
        overlayText.textContent = status.toUpperCase();

        // Register the media container so any blob-cache refresh
        // (typically triggered by the targets tab when an SSE event
        // arrives) repaints us automatically.
        if (isImage) {
            if (window.registerImageContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
            }
            if (status !== 'notbuilt') {
                _scheduleLazyFetch(wrapper, () => {
                    if (!window.fetchImage) return;
                    window.fetchImage(targetPath, false).then(url => {
                        // registerImageContainer only paints
                        // synchronously when the blob cache is
                        // already warm. The first lazy fetch for a
                        // path must therefore explicitly refresh
                        // every registered container, otherwise
                        // both this sticky AND the targets-tab
                        // tree-node (which share the same
                        // registered-container map) stay blank.
                        if (window._refreshImageContainers) {
                            window._refreshImageContainers(targetPath, url);
                        }
                    }).catch(() => {});
                });
            }
        } else if (isVideo) {
            if (window.registerVideoContainer) {
                window.registerImageContainer(targetPath, mediaContainer, 'leaf-image');
                window.registerVideoContainer(targetPath, mediaContainer, 'leaf-video');
            }
            if (status !== 'notbuilt') {
                _scheduleLazyFetch(wrapper, () => {
                    if (!window.fetchVideo) return;
                    window.fetchVideo(targetPath, false).then(url => {
                        if (window._refreshVideoContainers) {
                            window._refreshVideoContainers(targetPath, url);
                        }
                    }).catch(() => {});
                });
            }
        } else if (isAudio) {
            if (window.registerAudioContainer) {
                window.registerAudioContainer(targetPath, mediaContainer, 'leaf-audio');
            }
            if (status !== 'notbuilt') {
                _scheduleLazyFetch(wrapper, () => {
                    if (!window.fetchAudio) return;
                    window.fetchAudio(targetPath, false).then(url => {
                        if (window._refreshAudioContainers) {
                            window._refreshAudioContainers(targetPath, url);
                        }
                    }).catch(() => {});
                });
            }
        } else if (isText) {
            // Text targets: render the file content (or em-dash if
            // not yet built) directly in the container. The
            // monitor_files SSE will repaint this via
            // handleTargetUpdate when content arrives.
            mediaContainer.classList.add('sticky-text-content');
            const state = window.getPathState && window.getPathState(targetPath);
            const content = (state && state.content) ? state.content.trim() : '';
            mediaContainer.textContent = content || '—';
        }
        registeredPaths.add(targetPath);
        return wrapper;
    }

    // Build a clickable button that opens (toggles) a subfolder
    // panel. Subfolder open-state is global, so clicking this in
    // one sticky note reveals the subfolder in all of them.
    function createSubfolderButton(item) {
        const btn = document.createElement('div');
        btn.className = 'sticky-subfolder-button';
        btn.dataset.subfolder = item.name;
        const icon = document.createElement('span');
        icon.className = 'sticky-subfolder-icon';
        icon.textContent = '📁';
        btn.appendChild(icon);
        const label = document.createElement('span');
        label.className = 'sticky-subfolder-label';
        label.textContent = ' ' + item.name + '/';
        btn.appendChild(label);
        btn.addEventListener('click', e => {
            e.stopPropagation();
            toggleSubfolder(item.name);
        });
        return btn;
    }

    // Build the nested panel that appears when a subfolder button
    // is clicked. Mirrors the parent sticky's color (set inline by
    // the caller) and is distinguished from the parent by an inset
    // box-shadow defined in screenplay_view.css.
    function createSubfolderPanel(item, color, registeredPaths) {
        const panel = document.createElement('div');
        panel.className = 'sticky-subfolder-panel';
        panel.dataset.subfolder = item.name;
        if (color) panel.style.background = color;
        if (_currentOpenSubfolder === item.name) panel.classList.add('open');
        // Clicks inside the panel itself should not bubble to the
        // enclosing subfolder button (which would toggle it closed).
        panel.addEventListener('click', e => e.stopPropagation());

        const closeBtn = document.createElement('button');
        closeBtn.className = 'sticky-subfolder-close';
        closeBtn.textContent = '✕';
        closeBtn.title = 'Close';
        closeBtn.addEventListener('click', e => {
            e.stopPropagation();
            closeSubfolder();
        });
        panel.appendChild(closeBtn);

        const title = document.createElement('div');
        title.className = 'sticky-subfolder-title';
        title.textContent = item.name + '/';
        panel.appendChild(title);

        // Render the subfolder's items inline. Direct items get a
        // media node; nested subfolders are rendered as inline
        // folder sections within the same panel (not as new
        // overlay panels).
        item.items.forEach(child => {
            if (child.type === 'direct') {
                panel.appendChild(createMediaNode(
                    child.path, child.name, child.mimeType,
                    registeredPaths));
            } else {
                panel.appendChild(createInlineSubfolderSection(
                    child, color, registeredPaths));
            }
        });
        return panel;
    }

    // Render a subfolder as an inline section within an enclosing
    // panel. Unlike createSubfolderPanel (which is a toggleable
    // overlay), this is always-visible and supports arbitrary
    // nesting depth. The body is collapsed by default and expands
    // when the heading is clicked. Clicks on items inside the body
    // do not bubble up to collapse the section.
    function createInlineSubfolderSection(item, color, registeredPaths) {
        const section = document.createElement('div');
        section.className = 'sticky-subfolder-inline';

        const title = document.createElement('div');
        title.className = 'sticky-subfolder-inline-title';
        title.textContent = '▸ 📁 ' + item.name + '/';
        section.appendChild(title);

        const body = document.createElement('div');
        body.className = 'sticky-subfolder-inline-body';
        item.items.forEach(child => {
            if (child.type === 'direct') {
                body.appendChild(createMediaNode(
                    child.path, child.name, child.mimeType,
                    registeredPaths));
            } else {
                body.appendChild(createInlineSubfolderSection(
                    child, color, registeredPaths));
            }
        });
        section.appendChild(body);
        body.addEventListener('click', e => e.stopPropagation());

        title.addEventListener('click', e => {
            e.stopPropagation();
            const open = section.classList.toggle('open');
            title.textContent = (open ? '▾ 📁 ' : '▸ 📁 ')
                + item.name + '/';
        });
        return section;
    }

    // Build a sticky note element for a given beat. The background
    // color is set inline so callers can supply per-island colors.
    function createStickyNote(beat, color, registeredPaths, context) {
        const sticky = document.createElement('div');
        sticky.className = 'screenplay-sticky-note';
        if (color) sticky.style.background = color;
        sticky.dataset.beat_id = beat.beat_id;

        const grid = document.createElement('div');
        grid.className = 'sticky-meta-grid';
        grid.appendChild(createMetaRow('BEAT_ID', beat.beat_id));
        const ctxBeats = (context && context.beats) || [];
        const ctxOrient = (context && context.orientation) || 'vertical';
        const onSelectFactory = (field) => (newValue) => {
            if (context && typeof context.onUpdateBeatRef === 'function') {
                context.onUpdateBeatRef(beat.beat_id, field, newValue);
            }
        };
        grid.appendChild(createMetaRow(
            'CONTINUES_FROM',
            beat.continues_from_beat_id || '—',
            {
                editable: !!context,
                field: 'continues_from_beat_id',
                currentValue: beat.continues_from_beat_id || '',
                beat, beats: ctxBeats, orientation: ctxOrient,
                onSelect: onSelectFactory('continues_from_beat_id'),
            }));
        grid.appendChild(createMetaRow(
            'INCLUDES',
            beat.include_beat_id || '—',
            {
                editable: !!context,
                field: 'include_beat_id',
                currentValue: beat.include_beat_id || '',
                beat, beats: ctxBeats, orientation: ctxOrient,
                onSelect: onSelectFactory('include_beat_id'),
            }));
        sticky.appendChild(grid);

        const media = document.createElement('div');
        media.className = 'sticky-media-section';
        sticky.appendChild(media);

        // Targets are loaded dynamically from /list_targets so that
        // whatever the backend currently defines for this beat shows
        // up here automatically. The fetch is cached so this Promise
        // typically resolves synchronously on the microtask queue.
        // The media element may have been detached by the time the
        // promise resolves (if the view re-rendered), so we guard
        // with isConnected before mutating.
        getTargets().then(data => {
            if (!media.isConnected) return;
            const items = processBeatTargets(
                data, beat.beat_id, _getBeatPaths(beat.beat_id));
            items.forEach(item => {
                if (item.type === 'direct') {
                    media.appendChild(createMediaNode(
                        item.path, item.name,
                        item.mimeType, registeredPaths));
                } else {
                    const btn = createSubfolderButton(item);
                    // Nest the panel inside the button so its
                    // absolute positioning is relative to the button.
                    btn.appendChild(createSubfolderPanel(
                        item, color, registeredPaths));
                    media.appendChild(btn);
                }
            });
            sticky.dataset.populated = '1';
        });

        return sticky;
    }

    function clearRegisteredPaths(board, registeredPaths) {
        // Unregister every media container we attached to sticky
        // notes before the board is torn down, so the blob-cache
        // doesn't keep trying to repaint into orphaned DOM nodes.
        if (board) {
            board.querySelectorAll('.sticky-media-wrapper').forEach(w => {
                const path = w.dataset.path;
                if (!path) return;
                _cancelLazyFetch(w);
                const img = w.querySelector('.image-container');
                const vid = w.querySelector('.video-container');
                if (img && window.unregisterImageContainer) {
                    window.unregisterImageContainer(path, img);
                }
                if (vid && window.unregisterVideoContainer) {
                    window.unregisterVideoContainer(path, vid);
                }
            });
        }
        registeredPaths.clear();
    }

    function handleTargetUpdate(path, metadata) {
        // Update every sticky-media-wrapper for this path: refresh
        // data-status (which the overlay CSS keys off), set the
        // overlay text, and re-trigger the flash animation.
        const wrappers = document.querySelectorAll(
            `.sticky-media-wrapper[data-path="${path}"]`);
        wrappers.forEach(wrapper => {
            const status = metadata.status || 'notbuilt';
            wrapper.dataset.status = status;
            const overlayText = wrapper.querySelector('.node-status-overlay-text');
            if (overlayText) overlayText.textContent = status.toUpperCase();

            // For text-backed wrappers, also refresh the textual content.
            const textContainer = wrapper.querySelector('.sticky-text-content');
            if (textContainer) {
                if (status === 'notbuilt' || !metadata.content) {
                    textContainer.textContent = '—';
                } else {
                    textContainer.textContent = metadata.content.trim() || '—';
                }
            }

            const overlay = wrapper.querySelector('.node-status-overlay');
            if (overlay) {
                overlay.classList.remove('status-flash');
                // Force a reflow so the animation restarts even on
                // back-to-back status changes.
                void overlay.offsetWidth;
                overlay.classList.add('status-flash');
            }

            // Propagate a transient flash to any enclosing subfolder
            // (button or inline section). The status-flash class is
            // animation-only and self-removes after ~1s, so it gives
            // visual feedback without leaving a persistent gray
            // overlay on the folder itself.
            let parent = wrapper.parentElement;
            while (parent) {
                if (parent.classList
                    && (parent.classList.contains('sticky-subfolder-panel')
                        || parent.classList.contains('sticky-subfolder-button')
                        || parent.classList.contains('sticky-subfolder-inline'))) {
                    parent.classList.remove('sticky-subfolder-flash');
                    void parent.offsetWidth;
                    parent.classList.add('sticky-subfolder-flash');
                    
                    /*
                    // FIXME:
                    // the code below sometimes causes the following error.
                    // Uncaught TypeError: can't access property "classList" of null
                    setTimeout(() => {
                        parent.classList.remove('sticky-subfolder-flash');
                    }, 1100);
                    */
                }
                parent = parent.parentElement;
            }
        });

        // When the targets tab already has a tree-node for this path
        // its updateNode -> images.js/videos.js callback chain
        // refreshes the blob cache (and thus every container, sticky
        // or otherwise, registered for that path). When no tree-node
        // exists yet -- e.g. the screenplay rendered before the
        // targets tab finished its initial build -- we kick off the
        // refresh ourselves so the sticky still shows the right thing.
        if (!window.hasNode || !window.hasNode(path)) {
            const mimeType = metadata['mime-type'] || '';
            if (metadata.status === 'built') {
                if (mimeType.startsWith('image/') && window.fetchImage) {
                    window.fetchImage(path, true).then(url => {
                        if (window._refreshImageContainers) {
                            window._refreshImageContainers(path, url);
                        }
                    }).catch(() => {});
                } else if (mimeType.startsWith('video/') && window.fetchVideo) {
                    window.fetchVideo(path, true).then(url => {
                        if (window._refreshVideoContainers) {
                            window._refreshVideoContainers(path, url);
                        }
                    }).catch(() => {});
                }
            } else if (metadata.status === 'notbuilt') {
                if (mimeType.startsWith('image/') && window.clearImageFromContainers) {
                    window.clearImageFromContainers(path);
                } else if (mimeType.startsWith('video/') && window.clearVideoFromContainers) {
                    window.clearVideoFromContainers(path);
                }
            }
        }
    }

    // When a previously-unseen concrete path is recorded for a
    // beat, walk every on-screen sticky for that beat and rebuild
    // its media section so the new path appears in the correct
    // folder. Existing media wrappers are torn down first via
    // unregister so the blob cache stops repainting them.
    function _repopulateBeatStickies(beat_id) {
        const stickies = document.querySelectorAll(
            `.screenplay-sticky-note[data-beat_id="${beat_id}"]`);
        if (stickies.length === 0) return;
        getTargets().then(data => {
            stickies.forEach(sticky => {
                if (!sticky.isConnected) return;
                const media = sticky.querySelector('.sticky-media-section');
                if (!media) return;
                // Unregister all existing media wrappers under this
                // sticky so their image/video containers drop out of
                // the blob cache.
                media.querySelectorAll('.sticky-media-wrapper').forEach(w => {
                    const p = w.dataset.path;
                    if (!p) return;
                    const img = w.querySelector('.image-container');
                    const vid = w.querySelector('.video-container');
                    if (img && window.unregisterImageContainer) {
                        window.unregisterImageContainer(p, img);
                    }
                    if (vid && window.unregisterVideoContainer) {
                        window.unregisterVideoContainer(p, vid);
                    }
                });
                while (media.firstChild) media.removeChild(media.firstChild);
                const color = sticky.style.background;
                // We don't have access to the original
                // registeredPaths set for this sticky's view, so we
                // use a throwaway set; the view's existing set still
                // contains the old paths it registered (they remain
                // valid as long as the wrappers it created stay
                // mounted, which they will under other stickies).
                const regSet = new Set();
                const items = processBeatTargets(
                    data, beat_id, _getBeatPaths(beat_id));
                items.forEach(item => {
                    if (item.type === 'direct') {
                        media.appendChild(createMediaNode(
                            item.path, item.name, item.mimeType, regSet));
                    } else {
                        const btn = createSubfolderButton(item);
                        btn.appendChild(createSubfolderPanel(
                            item, color, regSet));
                        media.appendChild(btn);
                    }
                });
            });
        });
    }

    window.ScreenplayStickyNote = {
        createStickyNote,
        clearRegisteredPaths,
        handleTargetUpdate,
        isBeatTargetPath,
    };
})();
