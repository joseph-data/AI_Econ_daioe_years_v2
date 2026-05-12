(function () {

    // ── 1. Patch downloadImage to force a white canvas background ────────────
    // Plotly.toImage accepts setBackground:'white' which fills the canvas
    // before rendering, so transparent paper/plot colours become white.
    function patchDownloadImage() {
        if (!window.Plotly || !window.Plotly.downloadImage || window.Plotly._bgPatched) return;
        window.Plotly._bgPatched = true;

        var orig = Plotly.downloadImage;
        Plotly.downloadImage = function (gd, opts) {
            opts = Object.assign({}, opts || {}, { setBackground: 'white' });
            return orig.call(this, gd, opts);
        };
    }

    // ── 2. Also fix the SVG background rects directly (belt-and-suspenders) ──
    // plotly_beforeexport fires synchronously before Plotly serialises the SVG,
    // so any DOM changes here ARE captured in the exported image.
    function attachSvgHandlers(gd) {
        if (gd._exportHandlersAttached) return;
        gd._exportHandlersAttached = true;

        gd.on('plotly_beforeexport', function () {
            var rects = [];
            var mainSvg = gd.querySelector('svg.main-svg');
            if (mainSvg) {
                var paper = mainSvg.querySelector(':scope > rect');
                if (paper) rects.push(paper);
            }
            gd.querySelectorAll('.bg').forEach(function (r) { rects.push(r); });

            gd._exportRects = rects;
            gd._exportOrigFills = rects.map(function (r) {
                return { styleFill: r.style.fill, attrFill: r.getAttribute('fill') };
            });
            rects.forEach(function (r) {
                r.style.fill = 'white';
                r.setAttribute('fill', 'white');
            });

            try { Plotly.Fx.unhover(gd); } catch (e) {}
        });

        gd.on('plotly_afterexport', function () {
            if (!gd._exportRects) return;
            gd._exportRects.forEach(function (r, i) {
                var o = gd._exportOrigFills[i];
                r.style.fill = o.styleFill;
                if (o.attrFill === null) r.removeAttribute('fill');
                else r.setAttribute('fill', o.attrFill);
            });
        });
    }

    // Poll until Plotly is available, then patch
    var interval = setInterval(function () {
        if (window.Plotly && window.Plotly.downloadImage) {
            patchDownloadImage();
            clearInterval(interval);
        }
    }, 200);

    // Attach SVG handlers to every plot div, including ones added reactively
    var observer = new MutationObserver(function () {
        document.querySelectorAll('.js-plotly-plot').forEach(attachSvgHandlers);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll('.js-plotly-plot').forEach(attachSvgHandlers);

})();
