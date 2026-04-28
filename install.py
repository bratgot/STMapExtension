"""
STMapOverscan installer for Nuke.

Usage:
    Open the Nuke Script Editor and run:
        exec(open('/path/to/install.py').read())

    Or copy the contents of this file into the Script Editor and run.

This builds a self-contained Group node named "STMapOverscan" with the
BlinkScript kernel embedded. The kernel is also written to
~/.nuke/STMapOverscan_kernel.rpp so the BlinkScript can load it from disk
(this avoids a Nuke quirk where setting kernelSource via Python can fail
to flush before recompile).

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

  local:
    int2 srcOrigin;
    int2 srcSize;

  void define() {
    defineParam(padOffset,     "padOffset",     int2(192, 108));
    defineParam(extrapolation, "extrapolation", 1);
    defineParam(smoothing,     "smoothing",     8);
  }

  void init() {
    srcOrigin = int2(src.bounds.x1, src.bounds.y1);
    srcSize   = int2(src.bounds.x2 - src.bounds.x1,
                     src.bounds.y2 - src.bounds.y1);
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
      if (axis == 0) p.x = clamp(p.x + i, 0, srcSize.x - 1);
      else           p.y = clamp(p.y + i, 0, srcSize.y - 1);
      sum = sum + sampleUV(p);
      count = count + 1.0f;
    }
    return sum / count;
  }

  void process(int2 pos) {
    int2 srcPos = pos - padOffset;
    bool inside = srcPos.x >= 0 && srcPos.y >= 0 &&
                  srcPos.x < srcSize.x && srcPos.y < srcSize.y;

    float2 uv = float2(0.0f, 0.0f);

    if (inside) {
      uv = sampleUV(srcPos);
    } else if (extrapolation == 2) {
      uv = float2(0.0f, 0.0f);
    } else {
      int2 clamped = int2(clamp(srcPos.x, 0, srcSize.x - 1),
                          clamp(srcPos.y, 0, srcSize.y - 1));
      int2 step = srcPos - clamped;
      float2 edge = sampleUV(clamped);

      if (extrapolation == 0) {
        uv = edge;
      } else if (extrapolation == 3) {
        int steps  = max(abs(step.x), abs(step.y));
        int padDim = max(padOffset.x, padOffset.y);
        float fade = 0.0f;
        if (padDim > 0) {
          fade = 1.0f - float(steps) / float(padDim);
          if (fade < 0.0f) fade = 0.0f;
        }
        uv = edge * fade;
      } else {
        int baseline = max(1, smoothing);
        int smoothR  = smoothing;

        float2 slopeX = float2(0.0f, 0.0f);
        float2 slopeY = float2(0.0f, 0.0f);
        float2 anchor = edge;

        if (step.x != 0) {
          int dirX = 1;
          if (step.x < 0) dirX = -1;
          int innerX = clamp(clamped.x - dirX * baseline, 0, srcSize.x - 1);
          int actualB = abs(clamped.x - innerX);
          float2 edgeS  = sampleSmoothed(clamped, 1, smoothR);
          float2 innerS = sampleSmoothed(int2(innerX, clamped.y), 1, smoothR);
          if (actualB > 0) slopeX = (edgeS - innerS) / float(actualB);
          anchor = edgeS;
        }

        if (step.y != 0) {
          int dirY = 1;
          if (step.y < 0) dirY = -1;
          int innerY = clamp(clamped.y - dirY * baseline, 0, srcSize.y - 1);
          int actualB = abs(clamped.y - innerY);
          float2 edgeS  = sampleSmoothed(clamped, 0, smoothR);
          float2 innerS = sampleSmoothed(int2(clamped.x, innerY), 0, smoothR);
          if (actualB > 0) slopeY = (edgeS - innerS) / float(actualB);
          if (step.x == 0) anchor = edgeS;
        }

        uv = anchor + slopeX * float(abs(step.x)) + slopeY * float(abs(step.y));
      }
    }

    dst() = float4(uv.x, uv.y, 0.0f, 1.0f);
  }
};
'''


def build_stmap_overscan():
    """Create an STMapOverscan group node in the current Nuke script."""

    # write kernel to ~/.nuke for BlinkScript to load
    kernel_dir = os.path.join(os.path.expanduser('~'), '.nuke')
    if not os.path.isdir(kernel_dir):
        os.makedirs(kernel_dir)
    kernel_path = os.path.join(kernel_dir, 'STMapOverscan_kernel.rpp').replace('\\', '/')
    with open(kernel_path, 'w', newline='\n') as f:
        f.write(KERNEL)

    # build group + internal graph
    grp = nuke.createNode('Group', inpanel=False)
    grp['name'].setValue('STMapOverscan1')

    with grp:
        i = nuke.nodes.Input(name='src')
        bs = nuke.nodes.BlinkScript(name='stmap_kernel')
        bs['kernelSourceFile'].setValue(kernel_path)
        bs.setInput(0, i)
        o = nuke.nodes.Output()
        o.setInput(0, bs)

    # trigger load + recompile
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

    # title + subtitle
    title = (
        '<p style="margin:0;">'
        '<span style="color:#f0b24a; font-size:15px; font-weight:bold;">ST Map Overscan</span><br>'
        '<span style="color:#9aa; font-style:italic;">'
        'Extrapolate cropped ST maps beyond their original bounds</span>'
        '</p>'
    )
    grp.addKnob(nuke.Text_Knob('title_hdr', '', title))

    # output format section
    grp.addKnob(nuke.Text_Knob('sec_fmt', '<b>Output Format</b>'))
    kw = nuke.Int_Knob('dst_width', 'width')
    kw.setRange(100, 16384)
    kw.setValue(2500)
    grp.addKnob(kw)
    kh = nuke.Int_Knob('dst_height', 'height')
    kh.setRange(100, 16384)
    kh.setValue(2500)
    grp.addKnob(kh)
    kc = nuke.Boolean_Knob('auto_center', 'auto-center source')
    kc.setValue(True)
    kc.setFlag(nuke.STARTLINE)
    grp.addKnob(kc)
    kp = nuke.XY_Knob('pad_offset', 'pad offset')
    kp.setValue([0, 0])
    grp.addKnob(kp)

    # extrapolation section
    grp.addKnob(nuke.Text_Knob('sec_ext', '<b>Extrapolation</b>'))
    ke = nuke.Enumeration_Knob('extrap_mode', 'mode',
                               ['clamp', 'linear', 'zero', 'fade'])
    ke.setValue('linear')
    grp.addKnob(ke)
    ks = nuke.Int_Knob('smoothing', 'edge smoothing')
    ks.setRange(0, 64)
    ks.setValue(8)
    ks.setTooltip(
        'Averages edge samples along the tangent axis. '
        '0 = noisy raw slope. 8-16 good for most ST maps. '
        'Only affects "linear" mode.'
    )
    grp.addKnob(ks)

    # notes
    grp.addKnob(nuke.Text_Knob('sec_notes', '<b>Notes</b>'))
    notes = (
        '<p style="color:#b8b8b8; font-size:11px; line-height:1.4;">'
        'Extends ST map UV values past the source bbox by fitting a per-axis slope '
        'to the outermost pixels and projecting it outward. Edge smoothing averages '
        'samples tangent to each edge so per-pixel noise in the input doesn&rsquo;t '
        'get multiplied into streaks across the padded region.<br><br>'
        '<b>Modes</b><br>'
        '&nbsp;&nbsp;<i>clamp</i> &mdash; repeat edge values<br>'
        '&nbsp;&nbsp;<i>linear</i> &mdash; extend the gradient (default)<br>'
        '&nbsp;&nbsp;<i>zero</i> &mdash; fill padding with black<br>'
        '&nbsp;&nbsp;<i>fade</i> &mdash; soft falloff to black<br><br>'
        '<b>Tips</b><br>'
        '&middot; Bbox is read from <tt>src.bounds</tt>, so any upstream Crop is respected.<br>'
        '&middot; Smoothing only affects <i>linear</i> mode.<br>'
        '&middot; For real lens maps, keep smoothing modest (8-16) so edge curvature survives.'
        '</p>'
    )
    grp.addKnob(nuke.Text_Knob('notes_body', '', notes))

    # credit
    grp.addKnob(nuke.Text_Knob('sec_div', ''))
    credit = (
        '<p style="color:#777; font-size:10px; margin:0;">'
        'Marten Blumen &middot; '
        '<a href="https://github.com/bratgot/STMapExtension" style="color:#888;">'
        'github.com/bratgot/STMapExtension</a> '
        '&middot; v1.0'
        '</p>'
    )
    grp.addKnob(nuke.Text_Knob('credit', '', credit))

    # callback
    cb = "\n".join([
        'grp = nuke.thisNode()',
        'kk = nuke.thisKnob()',
        'kn = kk.name() if kk else ""',
        'if kn in ("dst_width","dst_height","auto_center","pad_offset","extrap_mode","smoothing","inputChange"):',
        ' bs = grp.node("stmap_kernel")',
        ' if bs is not None:',
        '  try:',
        '   modes = {"clamp":0,"linear":1,"zero":2,"fade":3}',
        '   bs["STMapOverscan_extrapolation"].setValue(modes[grp["extrap_mode"].value()])',
        '   bs["STMapOverscan_smoothing"].setValue(int(grp["smoothing"].value()))',
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
    except Exception:
        pass
    grp['pad_offset'].setEnabled(False)

    return grp


# auto-run when sourced
if __name__ == '__main__' or 'nuke' in dir():
    try:
        node = build_stmap_overscan()
        print('STMapOverscan group created: ' + node.name())
    except Exception as e:
        print('STMapOverscan install failed: ' + str(e))
        raise
