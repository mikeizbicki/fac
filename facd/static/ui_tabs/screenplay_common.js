// screenplay_common.js
//
// Shared logic for screenplay-like tab views (screenplay.js, storyboard.js).
// Provides:
//   - XML parsing/reconstruction of shooting-script.xml
//   - Fountain rendering helpers
//   - Save-to-backend helpers
//   - DAG / island computation for beat_id graphs
//   - A fixed palette of island colors
//
// This module exposes itself as window.ScreenplayCommon so individual tab
// files can call into it. It deliberately does no DOM rendering of beats;
// the per-tab files are responsible for that.

(function() {
    // Fixed palette of 8 island colors. Used both for sticky-note
    // backgrounds and for matching arrow strokes. Recycled cyclically.
    const ISLAND_COLORS = [
        '#ffffa5', // yellow (default screenplay sticky)
        '#ffd1a5', // peach
        '#a5e8ff', // sky blue
        '#c5ffa5', // light green
        '#ffa5d1', // pink
        '#d1a5ff', // lavender
        '#a5ffd1', // mint
        '#ffe5a5', // sand
    ];

    function parseScreenplayXml(xmlContent) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(xmlContent, 'text/xml');
        const beats = [];
        doc.querySelectorAll('beat').forEach(el => {
            const beat_id = el.getAttribute('beat_id');
            const continues_from_beat_id = el.getAttribute('continues_from_beat_id') || '';
            const include_beat_id = el.getAttribute('include_beat_id') || '';
            const text = el.textContent || '';
            if (beat_id) beats.push({
                beat_id,
                continues_from_beat_id,
                include_beat_id,
                text,
            });
        });
        return beats;
    }

    function escapeXmlAttr(str) {
        return str.replace(/&/g, '&amp;')
                  .replace(/"/g, '&quot;')
                  .replace(/'/g, '&apos;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;');
    }

    function escapeXmlText(str) {
        return str.replace(/&/g, '&amp;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;');
    }

    function reconstructXml(beats) {
        let xml = '<script>\n';
        beats.forEach(beat => {
            let attrs = ` beat_id="${escapeXmlAttr(beat.beat_id)}"`;
            if (beat.continues_from_beat_id) {
                attrs += ` continues_from_beat_id="${escapeXmlAttr(beat.continues_from_beat_id)}"`;
            }
            if (beat.include_beat_id) {
                attrs += ` include_beat_id="${escapeXmlAttr(beat.include_beat_id)}"`;
            }
            xml += `<beat${attrs}>${escapeXmlText(beat.text)}</beat>\n`;
        });
        xml += '</script>\n';
        return xml;
    }

    function renderFountain(text) {
        if (typeof fountain === 'undefined') {
            const escaped = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\n/g, '<br>\n');
            return `<pre class="fountain-fallback">${escaped}</pre>`;
        }
        return fountain.parse(text).html.script || '';
    }

    function saveScreenplay(beats, message) {
        const xmlContent = reconstructXml(beats);
        return fetch('/edit_file/' + encodeURIComponent('shooting-script.xml'), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: xmlContent, message: message })
        })
        .then(response => {
            if (!response.ok) throw new Error('Failed to save screenplay');
            return response.json();
        });
    }

    function generateNewBeatId(baseBeatId, direction, existingIds) {
        const suffix = direction === 'above' ? '-' : '+';
        let counter = 1;
        let newId = baseBeatId + suffix + counter;
        while (existingIds.has(newId)) {
            counter++;
            newId = baseBeatId + suffix + counter;
        }
        return newId;
    }

    // --- Beat mutation helpers (return updated beat arrays) ---

    function deleteBeatFromArray(beats, beatIndex) {
        const beat = beats[beatIndex];
        if (!beat) return null;
        const deletedRefBeat = beat.continues_from_beat_id;
        return beats
            .filter((_, i) => i !== beatIndex)
            .map(s => {
                if (s.continues_from_beat_id === beat.beat_id) {
                    return { ...s, continues_from_beat_id: deletedRefBeat };
                }
                return s;
            });
    }

    function mergeBeatsInArray(beats, firstIndex, secondIndex) {
        const firstBeat = beats[firstIndex];
        const secondBeat = beats[secondIndex];
        if (!firstBeat || !secondBeat) return null;
        const mergedText = firstBeat.text + '\n' + secondBeat.text;
        const updated = [];
        for (let i = 0; i < beats.length; i++) {
            if (i === firstIndex) {
                updated.push({ ...firstBeat, text: mergedText });
            } else if (i === secondIndex) {
                continue;
            } else {
                const s = beats[i];
                if (s.continues_from_beat_id === secondBeat.beat_id) {
                    updated.push({ ...s, continues_from_beat_id: firstBeat.beat_id });
                } else {
                    updated.push(s);
                }
            }
        }
        return updated;
    }

    function insertBeatAbove(beats, beatIndex) {
        const beat = beats[beatIndex];
        if (!beat) return null;
        const existingIds = new Set(beats.map(s => s.beat_id));
        const newBeatId = generateNewBeatId(beat.beat_id, 'above', existingIds);
        const newBeat = {
            beat_id: newBeatId,
            continues_from_beat_id: beat.continues_from_beat_id,
            include_beat_id: '',
            text: '',
            isNew: true,
        };
        const updated = [...beats];
        updated.splice(beatIndex, 0, newBeat);
        updated[beatIndex + 1] = {
            ...updated[beatIndex + 1],
            continues_from_beat_id: newBeatId,
        };
        return { beats: updated, newIndex: beatIndex, newBeatId };
    }

    function insertBeatBelow(beats, beatIndex) {
        const beat = beats[beatIndex];
        if (!beat) return null;
        const existingIds = new Set(beats.map(s => s.beat_id));
        const newBeatId = generateNewBeatId(beat.beat_id, 'below', existingIds);
        const newBeat = {
            beat_id: newBeatId,
            continues_from_beat_id: beat.beat_id,
            include_beat_id: '',
            text: '',
            isNew: true,
        };
        const updated = [...beats];
        updated.splice(beatIndex + 1, 0, newBeat);
        for (let i = 0; i < updated.length; i++) {
            if (i !== beatIndex + 1 && updated[i].continues_from_beat_id === beat.beat_id) {
                updated[i] = { ...updated[i], continues_from_beat_id: newBeatId };
            }
        }
        return { beats: updated, newIndex: beatIndex + 1, newBeatId };
    }

    // --- DAG / island computation ---
    //
    // Computes connected components of the beat graph where edges are
    // continues_from_beat_id and include_beat_id references. Beats are
    // identified by their index in the document-order array.
    //
    // Returns:
    //   {
    //     islandOf: Map(beat_id -> island_index),   // 0-based island id
    //     islandCount: number,
    //     colorOf:  Map(beat_id -> hex color),
    //     indexOf:  Map(beat_id -> beat array index),
    //   }
    //
    // Island indices are assigned in order of first appearance in the
    // document so colors are stable as beats are edited.
    function computeIslands(beats) {
        const indexOf = new Map();
        beats.forEach((b, i) => indexOf.set(b.beat_id, i));

        // Build undirected adjacency.
        // For each beat, prefer continues_from_beat_id; only fall
        // back to include_beat_id when continues_from_beat_id is
        // not present.
        const adj = new Map();
        beats.forEach(b => adj.set(b.beat_id, []));
        beats.forEach(b => {
            let ref = null;
            if (b.continues_from_beat_id) {
                ref = b.continues_from_beat_id;
            } else if (b.include_beat_id) {
                ref = b.include_beat_id;
            }
            if (ref && adj.has(ref)) {
                adj.get(b.beat_id).push(ref);
                adj.get(ref).push(b.beat_id);
            }
        });

        const islandOf = new Map();
        let islandCount = 0;

        // Assign islands in document order using BFS.
        for (const b of beats) {
            if (islandOf.has(b.beat_id)) continue;
            const island = islandCount++;
            const queue = [b.beat_id];
            islandOf.set(b.beat_id, island);
            while (queue.length) {
                const cur = queue.shift();
                for (const nbr of adj.get(cur) || []) {
                    if (!islandOf.has(nbr)) {
                        islandOf.set(nbr, island);
                        queue.push(nbr);
                    }
                }
            }
        }

        const colorOf = new Map();
        islandOf.forEach((isl, bid) => {
            colorOf.set(bid, ISLAND_COLORS[isl % ISLAND_COLORS.length]);
        });

        return { islandOf, islandCount, colorOf, indexOf };
    }

    // Compute the "include depth" for each beat. A beat with no
    // include_beat_id has depth 0. A beat that include_beat_id's
    // another beat has depth = (target's depth) + 1. This is used to
    // gray out included beats progressively: deeper = more gray.
    function computeIncludeDepths(beats) {
        const indexOf = new Map();
        beats.forEach((b, i) => indexOf.set(b.beat_id, i));
        const depth = new Map();
        function compute(beat_id, visiting) {
            if (depth.has(beat_id)) return depth.get(beat_id);
            if (visiting.has(beat_id)) return 0; // cycle guard
            const idx = indexOf.get(beat_id);
            if (idx === undefined) return 0;
            const b = beats[idx];
            if (!b.include_beat_id || !indexOf.has(b.include_beat_id)) {
                depth.set(beat_id, 0);
                return 0;
            }
            visiting.add(beat_id);
            const d = compute(b.include_beat_id, visiting) + 1;
            visiting.delete(beat_id);
            depth.set(beat_id, d);
            return d;
        }
        beats.forEach(b => compute(b.beat_id, new Set()));
        return depth;
    }

    // Mix a hex color toward gray by `amount` (0..1). amount=0 returns
    // the original color; amount=1 returns mid-gray.
    function grayifyColor(hex, amount) {
        if (amount <= 0) return hex;
        const a = Math.min(amount, 0.85);
        const m = hex.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        if (!m) return hex;
        let r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
        const gray = 180;
        r = Math.round(r * (1 - a) + gray * a);
        g = Math.round(g * (1 - a) + gray * a);
        b = Math.round(b * (1 - a) + gray * a);
        const h = n => n.toString(16).padStart(2, '0');
        return '#' + h(r) + h(g) + h(b);
    }

    // Compute paper-group boundaries for the storyboard's horizontal view.
    // Two adjacent beats (i, i+1) share a paper iff they are connected
    // by either continues_from_beat_id or include_beat_id.
    //
    // Returns an array of groups, each:
    //   { start, end, separators: [type, ...] }
    // where separators[k] describes the join between beats start+k and
    // start+k+1, and is either 'continues' or 'includes'.
    function computePaperGroups(beats) {
        const groups = [];
        if (beats.length === 0) return groups;
        let start = 0;
        let separators = [];
        for (let i = 1; i < beats.length; i++) {
            const cur = beats[i];
            const prev = beats[i - 1];
            let kind = null;
            if (cur.continues_from_beat_id === prev.beat_id) kind = 'continues';
            else if (cur.include_beat_id === prev.beat_id) kind = 'includes';
            if (kind === null) {
                groups.push({ start, end: i - 1, separators });
                start = i;
                separators = [];
            } else {
                separators.push(kind);
            }
        }
        groups.push({ start, end: beats.length - 1, separators });
        return groups;
    }

    window.ScreenplayCommon = {
        ISLAND_COLORS,
        parseScreenplayXml,
        reconstructXml,
        renderFountain,
        saveScreenplay,
        generateNewBeatId,
        deleteBeatFromArray,
        mergeBeatsInArray,
        insertBeatAbove,
        insertBeatBelow,
        computeIslands,
        computePaperGroups,
        computeIncludeDepths,
        grayifyColor,
        escapeXmlAttr,
        escapeXmlText,
    };
})();
