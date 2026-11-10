/* JARVIS "Rainbow Flow" orb: hundreds of thin coloured lines flowing
   around one swirling contour - built from the user's reference
   photo (cyan top, purple/pink right, orange/yellow bottom, green
   left, black background, hollow starry centre).
   Only runs when the active theme defines --fl-on; otherwise the
   canvas hides itself so other themes are unaffected. */
(function () {
  var cv = document.getElementById('pcanvas');
  if (!cv) return;
  var cs = getComputedStyle(document.body);
  var ON = (cs.getPropertyValue('--fl-on') || '').trim();
  if (!ON) return;  /* another theme owns the canvas - touch nothing */
  cv.style.display = '';  /* particles.js hid the shared canvas; undo */

  var ctx = cv.getContext('2d');
  var S = 440, CX = S / 2, CY = S / 2;
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  cv.width = S * dpr; cv.height = S * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  /* colour stops around the circle, starting at the TOP and going
     clockwise (screen coordinates): cyan -> blue -> purple -> pink
     -> orange -> yellow -> green -> teal -> back to cyan. */
  var STOPS = [
    [0.00, [34, 211, 238]], [0.14, [56, 189, 248]],
    [0.27, [167, 139, 250]], [0.40, [244, 114, 182]],
    [0.52, [251, 146, 60]], [0.64, [250, 204, 21]],
    [0.77, [163, 230, 53]], [0.90, [52, 211, 153]],
    [1.00, [34, 211, 238]]
  ];
  function colourAt(u) {
    u = ((u % 1) + 1) % 1;
    for (var i = 1; i < STOPS.length; i++) {
      if (u <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i];
        var f = (u - a[0]) / (b[0] - a[0] || 1);
        var r = Math.round(a[1][0] + (b[1][0] - a[1][0]) * f);
        var g = Math.round(a[1][1] + (b[1][1] - a[1][1]) * f);
        var bl = Math.round(a[1][2] + (b[1][2] - a[1][2]) * f);
        return 'rgba(' + r + ',' + g + ',' + bl + ',';
      }
    }
    return 'rgba(34,211,238,';
  }

  var NS = 120;              /* strands */
  var SEG = 64;              /* points per strand */
  var strands = [];
  for (var i = 0; i < NS; i++) {
    strands.push({
      off: (i / (NS - 1) - 0.5),            /* -0.5..0.5 across the band */
      ph: i * 0.045,                        /* phase drift per strand */
      sp: 0.75 + (i % 7) * 0.06             /* slight speed variety */
    });
  }
  var specks = [];
  for (var j = 0; j < 70; j++) {
    specks.push({
      x: Math.random() * S, y: Math.random() * S,
      r: 0.5 + Math.random() * 1.1, ph: Math.random() * 6.283
    });
  }

  var TAU = Math.PI * 2, t0 = performance.now();

  function frame(now) {
    var t = (now - t0) / 1000;
    var state = document.body.getAttribute('data-state');
    var speaking = state === 'speaking';
    var listening = state === 'listening';
    var spd = speaking ? 1.8 : 1.0;
    var amp = speaking ? 1.35 : (listening ? 1.15 : 1.0);

    ctx.clearRect(0, 0, S, S);
    ctx.globalCompositeOperation = 'lighter';

    /* starry specks */
    for (var k = 0; k < specks.length; k++) {
      var sp2 = specks[k];
      ctx.globalAlpha = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 1.3 + sp2.ph));
      ctx.fillStyle = '#ffffff';
      ctx.beginPath(); ctx.arc(sp2.x, sp2.y, sp2.r, 0, TAU); ctx.fill();
    }
    ctx.globalAlpha = 1;

    var R0 = 146;
    ctx.lineWidth = 1.1;
    ctx.lineCap = 'round';
    for (var s = 0; s < NS; s++) {
      var st = strands[s];
      var band = st.off * 32 * (0.8 + 0.2 * Math.sin(st.ph * 3));
      var prev = null;
      for (var q = 0; q <= SEG; q++) {
        var th = (q / SEG) * TAU;
        /* the swirling contour: three soft lobes + a slow skew */
        var wob = 1
          + 0.085 * Math.sin(3 * th + st.ph + t * 0.55 * st.sp * spd) * amp
          + 0.055 * Math.sin(6 * th - st.ph * 1.3 - t * 0.4 * spd) * amp
          + 0.035 * Math.sin(2 * th + t * 0.8 * spd);
        var skew = 0.10 * Math.sin(2 * th + st.ph + t * 0.3 * spd);
        var r = R0 * wob + band * (0.7 + 0.3 * Math.sin(2 * th + st.ph));
        var a = th + skew;
        var x = CX + Math.cos(a) * r;
        var y = CY + Math.sin(a) * r * 0.96;
        if (prev) {
          var u = (Math.atan2(prev[1] - CY, prev[0] - CX) / TAU) + 0.25;
          ctx.strokeStyle = colourAt(u) + '0.5)';
          ctx.beginPath();
          ctx.moveTo(prev[0], prev[1]);
          ctx.lineTo(x, y);
          ctx.stroke();
        }
        prev = [x, y];
      }
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
