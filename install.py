"""
STMapOverscan v2 installer for Nuke.

Usage:
    Open the Nuke Script Editor and run:
        exec(open('/path/to/install.py').read())

    Or copy the contents of this file into the Script Editor and run.

This builds a self-contained Group node named "STMapOverscan" with the
BlinkScript kernel embedded. The kernel is also written to
~/.nuke/STMapOverscan_kernel.rpp so the BlinkScript can load it from disk.

v2 features:
    - Quadratic extrapolation order (1=linear, 2=quadratic)
    - Trim region (uniform + per-edge override + auto-detect)

Repo: https://github.com/bratgot/STMapExtension
"""
import nuke
import os

KERNEL = r'''kernel STMapOverscan : ImageComputationKernel<ePixelWise>
{
  Image<eRead, eAccessRandom, eEdgeClamped> src;
  Image<eWrite> dst;

  param:
    int2 padOffset;
    int  extrapolation;
    int  smoothing;
    int  order;
    int4 trim;

  local:
    int2 srcOrigin;
    int2 srcSize;
    int2 trustedMin;
    int2 trustedMax;

  void define() {
    defineParam(padOffset,     "padOffset",     int2(192, 108));
    defineParam(extrapolation, "extrapolation", 1);
    defineParam(smoothing,     "smoothing",     8);
    defineParam(order,         "order",         1);
    defineParam(trim,          "trim",          int4(0, 0, 0, 0));
  }

  void init() {
    srcOrigin = int2(src.bounds.x1, src.bounds.y1);
    srcSize   = int2(src.bounds.x2 - src.bounds.x1,
                     src.bounds.y2 - src.bounds.y1);

    int trimL = max(0, trim.x);
    int trimR = max(0, trim.y);
    int trimB = max(0, trim.z);
    int trimT = max(0, trim.w);

    trustedMin = int2(trimL, trimB);
    trustedMax = int2(srcSize.x - 1 - trimR, srcSize.y - 1 - trimT);

    if (trustedMax.x < trustedMin.x) {
      int mid = (trustedMin.x + trustedMax.x) / 2;
      trustedMin.x = mid; trustedMax.x = mid;
    }
    if (trustedMax.y < trustedMin.y) {
      int mid = (trustedMin.y + trustedMax.y) / 2;
      trustedMin.y = mid; trustedMax.y = mid;
    }
  }

  float2 sampleUV(int2 srcP) {
    float4 s = src(srcP.x + srcOrigin.x, srcP.y + srcOrigin.y);
    return float2(s.x, s.y);
  }

  float2 sampleSmoothed(int2 srcP, int axis, int radius) {
    if (radius <= 0) return sampleUV(srcP);
    float2 sum = float2(0.0f, 0.0f);
    float count = 0.0f;
    for (int i = -radius; i <= radius; i++) {
      int2 p = srcP;
      if (axis == 0) p.x = clamp(p.x + i, trustedMin.x, trustedMax.x);
      else           p.y = clamp(p.y + i, trustedMin.y, trustedMax.y);
      sum = sum + sampleUV(p);
      count = count + 1.0f;
    }
    return sum / count;
  }

  float2 quadEval(float t, float2 f0, float2 f1, float2 f2,
                  float b1, float b2) {
    float L0 = (t + b1) * (t + b2) / (b1 * b2);
    float L1 = -t * (t + b2) / (b1 * (b2 - b1));
    float L2 =  t * (t + b1) / (b2 * (b2 - b1));
    return f0 * L0 + f1 * L1 + f2 * L2;
  }

  void process(int2 pos) {
    int2 srcPos = pos - padOffset;
    bool inside = srcPos.x >= trustedMin.x && srcPos.y >= trustedMin.y &&
                  srcPos.x <= trustedMax.x && srcPos.y <= trustedMax.y;

    float2 uv = float2(0.0f, 0.0f);

    if (inside) {
      uv = sampleUV(srcPos);
    } else if (extrapolation == 2) {
      uv = float2(0.0f, 0.0f);
    } else {
      int2 clamped = int2(clamp(srcPos.x, trustedMin.x, trustedMax.x),
                          clamp(srcPos.y, trustedMin.y, trustedMax.y));
      int2 step = srcPos - clamped;
      float2 anchor = sampleUV(clamped);

      if (extrapolation == 0) {
        uv = anchor;
      } else if (extrapolation == 3) {
        int steps  = max(abs(step.x), abs(step.y));
        int padDim = max(padOffset.x, padOffset.y);
        float fade = 0.0f;
        if (padDim > 0) {
          fade = 1.0f - float(steps) / float(padDim);
          if (fade < 0.0f) fade = 0.0f;
        }
        uv = anchor * fade;
      } else {
        int N = max(1, smoothing);
        float2 deltaX = float2(0.0f, 0.0f);
        float2 deltaY = float2(0.0f, 0.0f);

        if (step.x != 0) {
          int dirX = (step.x > 0) ? 1 : -1;
          int x1 = clamp(clamped.x - dirX * N,         trustedMin.x, trustedMax.x);
          int x2 = clamp(clamped.x - dirX * 2 * N,     trustedMin.x, trustedMax.x);
          int b1 = abs(clamped.x - x1);
          int b2 = abs(clamped.x - x2);
          float2 f0 = sampleSmoothed(int2(clamped.x, clamped.y), 1, N);
          float2 f1 = sampleSmoothed(int2(x1,        clamped.y), 1, N);
          float dx = float(abs(step.x));

          if (order >= 2 && b2 > b1 && b1 > 0) {
            float2 f2 = sampleSmoothed(int2(x2, clamped.y), 1, N);
            float2 q  = quadEval(dx, f0, f1, f2, float(b1), float(b2));
            deltaX = q - f0;
          } else if (b1 > 0) {
            float2 slope = (f0 - f1) / float(b1);
            deltaX = slope * dx;
          }
        }

        if (step.y != 0) {
          int dirY = (step.y > 0) ? 1 : -1;
          int y1 = clamp(clamped.y - dirY * N,         trustedMin.y, trustedMax.y);
          int y2 = clamp(clamped.y - dirY * 2 * N,     trustedMin.y, trustedMax.y);
          int b1 = abs(clamped.y - y1);
          int b2 = abs(clamped.y - y2);
          float2 f0 = sampleSmoothed(int2(clamped.x, clamped.y), 0, N);
          float2 f1 = sampleSmoothed(int2(clamped.x, y1),        0, N);
          float dy = float(abs(step.y));

          if (order >= 2 && b2 > b1 && b1 > 0) {
            float2 f2 = sampleSmoothed(int2(clamped.x, y2), 0, N);
            float2 q  = quadEval(dy, f0, f1, f2, float(b1), float(b2));
            deltaY = q - f0;
          } else if (b1 > 0) {
            float2 slope = (f0 - f1) / float(b1);
            deltaY = slope * dy;
          }
        }

        uv = anchor + deltaX + deltaY;
      }
    }

    dst() = float4(uv.x, uv.y, 0.0f, 1.0f);
  }
};
'''


# auto-analyze code embedded in the group's button knob
ANALYZE_CODE = '''
import nuke

grp = nuke.thisNode()
inp = grp.input(0)
if inp is None:
    nuke.message("Connect an ST map to the input first.")
else:
    b = inp.bbox()
    x0, y0 = b.x(), b.y()
    w, h = b.w(), b.h()
    x1, y1 = x0 + w - 1, y0 + h - 1

    if w < 16 or h < 16:
        nuke.message("Source bbox too small for analysis (need 16+ px).")
    else:
        SCAN = min(32, max(8, w // 8), max(8, h // 8))
        TS = 12

        def sample_uv(x, y):
            try:
                r = inp.sample("rgba.red",   x + 0.5, y + 0.5)
                g = inp.sample("rgba.green", x + 0.5, y + 0.5)
                return (r, g)
            except Exception:
                return None

        def median(vals):
            s = sorted(vals)
            return s[len(s) // 2]

        def edge_trim(strip_func):
            profile = []
            for d in range(SCAN):
                strip = strip_func(d)
                if not strip:
                    return 0
                profile.append((d, median([s[0] for s in strip]),
                                   median([s[1] for s in strip])))

            deep = profile[SCAN // 2:]
            nd = len(deep)
            if nd < 4:
                return 0

            def linfit(idx):
                xs = [p[0] for p in deep]
                ys = [p[idx] for p in deep]
                sx = sum(xs); sy = sum(ys)
                sxx = sum(x*x for x in xs)
                sxy = sum(xs[i]*ys[i] for i in range(nd))
                denom = nd * sxx - sx * sx
                if abs(denom) < 1e-9:
                    return None
                slope = (nd * sxy - sx * sy) / denom
                intercept = (sy - slope * sx) / nd
                resid = [ys[i] - (slope * xs[i] + intercept) for i in range(nd)]
                std = (sum(r*r for r in resid) / nd) ** 0.5
                return slope, intercept, std

            fu = linfit(1); fv = linfit(2)
            if fu is None or fv is None:
                return 0
            tu = max(fu[2] * 5.0, 0.005)
            tv = max(fv[2] * 5.0, 0.005)

            for d, mu, mv in profile:
                if abs(mu - (fu[0]*d + fu[1])) <= tu and \\
                   abs(mv - (fv[0]*d + fv[1])) <= tv:
                    return d
            return SCAN // 2

        def lstrip(d):
            x = x0 + d
            ys = [y0 + int((h-1) * t / (TS-1)) for t in range(TS)]
            return [s for s in (sample_uv(x, y) for y in ys) if s is not None]

        def rstrip(d):
            x = x1 - d
            ys = [y0 + int((h-1) * t / (TS-1)) for t in range(TS)]
            return [s for s in (sample_uv(x, y) for y in ys) if s is not None]

        def bstrip(d):
            y = y0 + d
            xs = [x0 + int((w-1) * t / (TS-1)) for t in range(TS)]
            return [s for s in (sample_uv(x, y) for x in xs) if s is not None]

        def tstrip(d):
            y = y1 - d
            xs = [x0 + int((w-1) * t / (TS-1)) for t in range(TS)]
            return [s for s in (sample_uv(x, y) for x in xs) if s is not None]

        tL = edge_trim(lstrip)
        tR = edge_trim(rstrip)
        tB = edge_trim(bstrip)
        tT = edge_trim(tstrip)

        grp["use_per_edge"].setValue(True)
        grp["trim_left"].setValue(tL)
        grp["trim_right"].setValue(tR)
        grp["trim_bottom"].setValue(tB)
        grp["trim_top"].setValue(tT)

        nuke.message("Auto-analyze complete:\\nL=%d  R=%d  B=%d  T=%d" %
                     (tL, tR, tB, tT))
'''


def build_stmap_overscan():
    """Create an STMapOverscan group node in the current Nuke script."""

    kernel_dir = os.path.join(os.path.expanduser('~'), '.nuke')
    if not os.path.isdir(kernel_dir):
        os.makedirs(kernel_dir)
    kernel_path = os.path.join(kernel_dir, 'STMapOverscan_kernel.rpp').replace('\\', '/')
    with open(kernel_path, 'w', newline='\n') as f:
        f.write(KERNEL)

    grp = nuke.createNode('Group', inpanel=False)
    grp['name'].setValue('STMapOverscan1')

    with grp:
        i = nuke.nodes.Input(name='src')
        bs = nuke.nodes.BlinkScript(name='stmap_kernel')
        bs['kernelSourceFile'].setValue(kernel_path)
        bs.setInput(0, i)
        o = nuke.nodes.Output()
        o.setInput(0, bs)

    try:
        bs['reloadKernelSourceFile'].execute()
    except Exception:
        pass
    try:
        bs['recompile'].execute()
    except Exception:
        try:
            bs['rebuild'].execute()
        except Exception:
            pass

    title = (
        '<p style="margin:0;">'
        '<span style="color:#f0b24a; font-size:15px; font-weight:bold;">ST Map Overscan</span><br>'
        '<span style="color:#9aa; font-style:italic;">'
        'Extrapolate cropped ST maps beyond their original bounds</span>'
        '</p>'
    )
    grp.addKnob(nuke.Text_Knob('title_hdr', '', title))

    # --- output format ---
    grp.addKnob(nuke.Text_Knob('sec_fmt', '<b>Output Format</b>'))
    kw = nuke.Int_Knob('dst_width', 'width');   kw.setRange(100, 16384); kw.setValue(2500); grp.addKnob(kw)
    kh = nuke.Int_Knob('dst_height', 'height'); kh.setRange(100, 16384); kh.setValue(2500); grp.addKnob(kh)
    kc = nuke.Boolean_Knob('auto_center', 'auto-center source'); kc.setValue(True); kc.setFlag(nuke.STARTLINE); grp.addKnob(kc)
    kp = nuke.XY_Knob('pad_offset', 'pad offset'); kp.setValue([0, 0]); grp.addKnob(kp)

    # --- extrapolation ---
    grp.addKnob(nuke.Text_Knob('sec_ext', '<b>Extrapolation</b>'))
    ke = nuke.Enumeration_Knob('extrap_mode', 'mode', ['clamp', 'linear', 'zero', 'fade'])
    ke.setValue('linear'); grp.addKnob(ke)

    ko = nuke.Int_Knob('order', 'order'); ko.setRange(1, 2); ko.setValue(1)
    ko.setTooltip('1 = linear (extend gradient as a straight line). '
                  '2 = quadratic (fit a parabola for curving distortion). '
                  'Only affects "linear" extrapolation mode.')
    grp.addKnob(ko)

    ks = nuke.Int_Knob('smoothing', 'edge smoothing'); ks.setRange(0, 64); ks.setValue(8)
    ks.setTooltip('Averages edge samples along the tangent axis. '
                  '0 = noisy raw slope. 8-16 good for most ST maps. '
                  'Also sets the baseline distance for slope/curvature estimation.')
    grp.addKnob(ks)

    # --- trim ---
    grp.addKnob(nuke.Text_Knob('sec_trim', '<b>Edge Trim</b>'))
    grp.addKnob(nuke.Text_Knob('trim_help',
        '',
        '<span style="color:#888; font-size:10px; font-style:italic;">'
        'Removes unreliable outer pixels and replaces them with synthetic edge values. '
        'Use when the input has black borders, ringing, or other edge artifacts.'
        '</span>'))

    ku = nuke.Int_Knob('uniform_trim', 'uniform trim'); ku.setRange(0, 64); ku.setValue(0)
    ku.setTooltip('Pixels to trim from all four edges. Per-edge overrides take precedence when enabled.')
    grp.addKnob(ku)

    kpe = nuke.Boolean_Knob('use_per_edge', 'use per-edge overrides')
    kpe.setValue(False); kpe.setFlag(nuke.STARTLINE); grp.addKnob(kpe)

    ktl = nuke.Int_Knob('trim_left',   'left');   ktl.setRange(0, 64); ktl.setValue(0); grp.addKnob(ktl)
    ktr = nuke.Int_Knob('trim_right',  'right');  ktr.setRange(0, 64); ktr.setValue(0); grp.addKnob(ktr)
    ktb = nuke.Int_Knob('trim_bottom', 'bottom'); ktb.setRange(0, 64); ktb.setValue(0); grp.addKnob(ktb)
    ktt = nuke.Int_Knob('trim_top',    'top');    ktt.setRange(0, 64); ktt.setValue(0); grp.addKnob(ktt)

    ka = nuke.PyScript_Knob('auto_analyze', 'Auto-Analyze Edges')
    ka.setFlag(nuke.STARTLINE)
    ka.setTooltip('Sample the input ST map and detect unreliable edge pixels. '
                  'Sets the per-edge trim values and enables overrides.')
    ka.setValue(ANALYZE_CODE)
    grp.addKnob(ka)

    kreset = nuke.PyScript_Knob('reset_trim', 'Reset Trim')
    kreset.setTooltip('Zero all trim values and disable per-edge overrides.')
    kreset.setValue(
        'g = nuke.thisNode()\n'
        'g["uniform_trim"].setValue(0)\n'
        'g["use_per_edge"].setValue(False)\n'
        'g["trim_left"].setValue(0); g["trim_right"].setValue(0)\n'
        'g["trim_bottom"].setValue(0); g["trim_top"].setValue(0)\n'
    )
    grp.addKnob(kreset)

    # --- notes (collapsible) ---
    def wrap(text, n=12):
        """Basic word wrap: break text every n words with <br>."""
        words = text.split()
        lines = [' '.join(words[i:i + n]) for i in range(0, len(words), n)]
        return '<br>'.join(lines)

    p_intro = wrap(
        'Extends ST map UV values past the source bbox by fitting '
        'a per-axis function to the outermost trusted pixels and projecting '
        'it outward.'
    )
    p_trim = wrap(
        'Shrinks the trusted region by N pixels on each side; the '
        'trimmed pixels get replaced by extrapolated values. Use when input '
        'edges are unreliable (black bleeds, ringing, AA softness). '
        'Auto-Analyze samples the input and detects bad edges automatically.'
    )

    notes = (
        '<p style="color:#b8b8b8; font-size:11px; line-height:1.4;">'
        + p_intro + '<br><br>'
        '<b>Modes</b><br>'
        '&nbsp;&nbsp;<i>clamp</i> &mdash; repeat edge values<br>'
        '&nbsp;&nbsp;<i>linear</i> &mdash; extend the gradient (default; order 1 or 2)<br>'
        '&nbsp;&nbsp;<i>zero</i> &mdash; fill padding with black<br>'
        '&nbsp;&nbsp;<i>fade</i> &mdash; soft falloff to black<br><br>'
        '<b>Order</b> (linear mode only)<br>'
        '&nbsp;&nbsp;<i>1</i> &mdash; first-order Taylor (straight line). Exact for linear gradients.<br>'
        '&nbsp;&nbsp;<i>2</i> &mdash; second-order Taylor (parabola). Better for fisheye/anamorphic curvature.<br><br>'
        '<b>Edge Trim</b><br>'
        + p_trim + '<br><br>'
        '<b>Tips</b><br>'
        '&middot; Bbox is read from <tt>src.bounds</tt>; upstream Crop is respected automatically.<br>'
        '&middot; Smoothing only affects <i>linear</i> extrapolation mode.<br>'
        '&middot; Quadratic gives best results when smoothing &ge; 4.<br>'
        '&middot; For real lens maps, start with order 2 + smoothing 8-16.'
        '</p>'
    )

    grp.addKnob(nuke.Tab_Knob('notes_group', 'Notes', nuke.TABBEGINCLOSEDGROUP))
    grp.addKnob(nuke.Text_Knob('notes_body', '', notes))
    grp.addKnob(nuke.Tab_Knob('notes_group_end', '', nuke.TABENDGROUP))

    # --- credit ---
    grp.addKnob(nuke.Text_Knob('sec_div', ''))
    credit = (
        '<p style="color:#777; font-size:10px; margin:0;">'
        'Marten Blumen &middot; '
        '<a href="https://github.com/bratgot/STMapExtension" style="color:#888;">'
        'github.com/bratgot/STMapExtension</a> '
        '&middot; v2.0'
        '</p>'
    )
    grp.addKnob(nuke.Text_Knob('credit', '', credit))

    # --- callback ---
    cb = "\n".join([
        'grp = nuke.thisNode()',
        'kk = nuke.thisKnob()',
        'kn = kk.name() if kk else ""',
        'sync_keys = ("dst_width","dst_height","auto_center","pad_offset",',
        '             "extrap_mode","order","smoothing",',
        '             "uniform_trim","use_per_edge",',
        '             "trim_left","trim_right","trim_bottom","trim_top",',
        '             "inputChange")',
        'if kn in sync_keys:',
        ' bs = grp.node("stmap_kernel")',
        ' if bs is not None:',
        '  try:',
        '   modes = {"clamp":0,"linear":1,"zero":2,"fade":3}',
        '   bs["STMapOverscan_extrapolation"].setValue(modes[grp["extrap_mode"].value()])',
        '   bs["STMapOverscan_smoothing"].setValue(int(grp["smoothing"].value()))',
        '   bs["STMapOverscan_order"].setValue(int(grp["order"].value()))',
        '  except Exception: pass',
        '  use_pe = grp["use_per_edge"].value()',
        '  for kn2 in ("trim_left","trim_right","trim_bottom","trim_top"):',
        '   grp[kn2].setEnabled(use_pe)',
        '  ut = int(grp["uniform_trim"].value())',
        '  if use_pe:',
        '   tL = int(grp["trim_left"].value()); tR = int(grp["trim_right"].value())',
        '   tB = int(grp["trim_bottom"].value()); tT = int(grp["trim_top"].value())',
        '  else:',
        '   tL = ut; tR = ut; tB = ut; tT = ut',
        '  try:',
        '   bs["STMapOverscan_trim"].setValue([tL, tR, tB, tT])',
        '  except Exception: pass',
        '  grp["pad_offset"].setEnabled(not grp["auto_center"].value())',
        '  inp = grp.input(0)',
        '  if inp is not None:',
        '   b = inp.bbox()',
        '   sw, sh = b.w(), b.h()',
        '   dw = int(grp["dst_width"].value())',
        '   dh = int(grp["dst_height"].value())',
        '   if grp["auto_center"].value():',
        '    grp["pad_offset"].setValue([max(0,(dw-sw)//2), max(0,(dh-sh)//2)])',
        '   px = int(grp["pad_offset"].value(0))',
        '   py = int(grp["pad_offset"].value(1))',
        '   try:',
        '    bs["STMapOverscan_padOffset"].setValue([px, py])',
        '    bs["format"].fromScript("%d %d 0 0 %d %d 1 overscan_%dx%d" % (dw,dh,dw,dh,dw,dh))',
        '    bs["specifiedFormat"].setValue(True)',
        '   except Exception: pass',
    ])
    grp['knobChanged'].setValue(cb)

    # initial sync
    try:
        bs['STMapOverscan_extrapolation'].setValue(1)
        bs['STMapOverscan_smoothing'].setValue(8)
        bs['STMapOverscan_order'].setValue(1)
        bs['STMapOverscan_trim'].setValue([0, 0, 0, 0])
    except Exception:
        pass
    grp['pad_offset'].setEnabled(False)
    for kn2 in ('trim_left', 'trim_right', 'trim_bottom', 'trim_top'):
        grp[kn2].setEnabled(False)

    return grp


if __name__ == '__main__' or 'nuke' in dir():
    try:
        node = build_stmap_overscan()
        print('STMapOverscan v2 group created: ' + node.name())
    except Exception as e:
        print('STMapOverscan install failed: ' + str(e))
        raise
