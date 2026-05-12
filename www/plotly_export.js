(function () {
    function patchPlotly() {
        if (!window.Plotly || !window.Plotly.downloadImage || window.Plotly._downloadImagePatched) return;
        window.Plotly._downloadImagePatched = true;

        var orig = Plotly.downloadImage;
        Plotly.downloadImage = function (gd, opts) {
            var origPaper = (gd.layout || {}).paper_bgcolor;
            var origPlot  = (gd.layout || {}).plot_bgcolor;
            var isRadar   = (gd.data || []).some(function (t) { return t.type === 'scatterpolar'; });

            var whiteLayout = { paper_bgcolor: 'white', plot_bgcolor: 'white' };
            if (isRadar) whiteLayout['polar.bgcolor'] = 'white';

            var restoreLayout = { paper_bgcolor: origPaper, plot_bgcolor: origPlot };
            if (isRadar) restoreLayout['polar.bgcolor'] = origPaper;

            // unhover first so trace dimming is gone
            try { Plotly.Fx.unhover(gd); } catch (e) {}

            return Plotly.relayout(gd, whiteLayout)
                .then(function () { return orig(gd, opts); })
                .then(function (filename) {
                    Plotly.relayout(gd, restoreLayout);
                    return filename;
                })
                .catch(function (err) {
                    Plotly.relayout(gd, restoreLayout);
                    return Promise.reject(err);
                });
        };
    }

    var interval = setInterval(function () {
        if (window.Plotly && window.Plotly.downloadImage) {
            patchPlotly();
            clearInterval(interval);
        }
    }, 200);
})();
