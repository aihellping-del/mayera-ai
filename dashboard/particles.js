/* MAYERA particle-head: dots form a human head profile (photo style),
   golden brain cluster, particles dispersing to the right, glowing
   core at the chest. Colours come from CSS vars --pc-main etc.
   Only runs when the active theme defines --pc-main; otherwise the
   canvas hides itself so other themes are unaffected. */
(function () {
  var cv = document.getElementById('pcanvas');
  if (!cv) return;
  var cs = getComputedStyle(document.body);
  function v(n, d) { var s = (cs.getPropertyValue(n) || '').trim(); return s || d; }
  var MAIN = (cs.getPropertyValue('--pc-main') || '').trim();
  if (!MAIN) { cv.style.display = 'none'; return; }
  var LIGHT = v('--pc-light', '#bae6fd'),
      BRAIN = v('--pc-brain', '#f59e0b'), BRAIN2 = v('--pc-brain2', '#fde68a'),
      GLOW = v('--pc-glow', '#2563eb');

  var ctx = cv.getContext('2d');
  var S = 440;
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  cv.width = S * dpr; cv.height = S * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  /* head profile silhouette, facing left (virtual 440x440) */
  var off = document.createElement('canvas'); off.width = S; off.height = S;
  var o = off.getContext('2d');
  var pts = [[262,26],[318,40],[362,84],[382,140],[380,196],[362,246],[352,292],
             [352,338],[392,384],[420,404],[420,424],[128,424],[140,392],[196,352],
             [238,322],[214,282],[196,262],[172,240],[158,224],[176,196],[172,152],
             [186,96],[216,48]];
  o.beginPath();
  var last = pts[pts.length - 1];
  o.moveTo((pts[0][0] + last[0]) / 2, (pts[0][1] + last[1]) / 2);
  for (var i = 0; i < pts.length; i++) {
    var p = pts[i], q = pts[(i + 1) % pts.length];
    o.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
  }
  o.closePath(); o.fillStyle = '#fff'; o.fill();
  var img = o.getImageData(0, 0, S, S).data;
  function inside(x, y) {
    if (x < 0 || y < 0 || x >= S || y >= S) return false;
    return img[(y * S + x) * 4 + 3] > 0;
  }
  var BC = { x: 282, y: 128, rx: 66, ry: 52 };
  function inBrain(x, y) {
    var dx = (x - BC.x) / BC.rx, dy = (y - BC.y) / BC.ry;
    return dx * dx + dy * dy < 1;
  }

  var N = 2400, ps = [], tries = 0;
  while (ps.length < N && tries < N * 60) {
    tries++;
    var x = Math.random() * S, y = Math.random() * S;
    if (!inside(x | 0, y | 0)) continue;
    var brain = inBrain(x, y);
    ps.push({
      x: x, y: y, ph: Math.random() * 6.283, sp: .5 + Math.random(),
      sz: brain ? (Math.random() < .3 ? 2.2 : 1.4) : (Math.random() < .25 ? 2 : 1.2),
      brain: brain,
      dr: !brain && x > 318 && Math.random() < .55,
      off: Math.random() * 170, dsp: 14 + Math.random() * 22
    });
  }

  /* golden circuit lines down the neck to the chest core */
  function qpoint(p0, p1, p2, t) {
    var u = 1 - t;
    return [u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]];
  }
  var lines = [[[268,300],[258,352],[252,404]],
               [[292,306],[286,354],[258,404]],
               [[244,306],[244,356],[248,404]]];
  var lp = [];
  lines.forEach(function (L) {
    for (var i = 0; i < 46; i++) {
      var q = qpoint(L[0], L[1], L[2], i / 46);
      lp.push({ x: q[0], y: q[1], ph: Math.random() * 6.283, sz: 1.3 });
    }
  });
  var core = { x: 252, y: 408 };
  var TAU = 6.283, t0 = performance.now();

  function frame(now) {
    var t = (now - t0) / 1000;
    var speaking = document.body.getAttribute('data-state') === 'speaking';
    var amp = speaking ? 2.6 : 1.4, spd = speaking ? 1.9 : 1.0;
    ctx.clearRect(0, 0, S, S);

    var pulse = 1 + Math.sin(t * 2.2) * .12;
    var g = ctx.createRadialGradient(core.x, core.y, 0, core.x, core.y, 34 * pulse);
    g.addColorStop(0, 'rgba(255,255,255,.95)');
    g.addColorStop(.25, GLOW);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.globalAlpha = .9; ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(core.x, core.y, 34 * pulse, 0, TAU); ctx.fill();
    ctx.globalAlpha = 1;

    ctx.fillStyle = BRAIN;
    for (var j = 0; j < lp.length; j++) {
      var L2 = lp[j];
      ctx.globalAlpha = .5 + .4 * Math.sin(t * 2 + L2.ph);
      ctx.beginPath();
      ctx.arc(L2.x + Math.sin(t * 1.3 + L2.ph) * 1.1,
              L2.y + Math.cos(t * 1.1 + L2.ph) * 1.1, L2.sz, 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    for (var i = 0; i < ps.length; i++) {
      var p = ps[i];
      var jx = Math.sin(t * p.sp * spd + p.ph) * amp;
      var jy = Math.cos(t * p.sp * .8 * spd + p.ph * 1.7) * amp;
      var dx = 0, al = 1;
      if (p.dr) {
        var cyc = (t * p.dsp + p.off) % 170;
        dx = cyc; al = Math.max(0, 1 - cyc / 170);
        jy += Math.sin(t + p.ph) * 2;
      }
      var base = p.brain ? (.65 + .35 * Math.sin(t * 2.4 + p.ph))
                         : (.45 + .45 * Math.sin(t * 1.6 + p.ph));
      ctx.globalAlpha = base * (p.dr ? al : 1);
      ctx.fillStyle = p.brain ? (i % 3 ? BRAIN : BRAIN2) : (i % 4 ? MAIN : LIGHT);
      ctx.beginPath(); ctx.arc(p.x + jx + dx, p.y + jy, p.sz, 0, TAU); ctx.fill();
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
