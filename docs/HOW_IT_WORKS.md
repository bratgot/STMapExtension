# How STMapOverscan Works

## What an ST map is

An ST map encodes a per-pixel lookup. Red and green channels hold normalized UV coordinates (0..1) telling a downstream STMap node *go fetch the pixel at this location in the source image*. Identity ST map → image returns unchanged. Warped ST map → lens distortion, morph, or whatever remap was baked in.

## What "cropped" means

When an ST map's bbox has been trimmed to only the region containing valid UV data, everything outside the bbox is missing. The values inside are still correct — there just aren't pixels beyond the edges. This is a problem when the downstream operation needs UV samples from outside that region (undistorting into an overscan plate, warping something larger than the map's bbox, etc.).

The tool's job: manufacture plausible UV values for that padded region by extending the existing function outward.

## The trusted region

Two things define what counts as "inside":

1. The source bbox (read from `src.bounds` in the kernel's `init()`)
2. The trim values, which shrink the bbox by N pixels on each side

The shrunken region is the **trusted region**. Pixels inside the trusted region are returned directly. Pixels outside (whether they were never in the source bbox, or were trimmed off because they're unreliable) get synthesized via extrapolation from the trusted boundary.

This dual-purpose framework means the same code path handles uncropping (trim=0, just extending past the original bbox) and edge replacement (trim>0, replacing bad outermost pixels with synthetic ones).

## The core algorithm

For every output pixel:

1. Compute source-space position: `srcPos = outputPos - padOffset`
2. If `srcPos` falls inside the trusted region → sample directly
3. If outside → find nearest trusted-region edge pixel, fit a function (line or parabola) using interior samples, evaluate the function at the extrapolation distance:
   ```
   uv = anchor + Δx_contribution + Δy_contribution
   ```

## Order 1: linear extrapolation

The first-order Taylor expansion: assume the field is locally linear. Estimate the slope at the edge using a wide-baseline finite difference:

$$\hat{\mathbf{s}}_x = \frac{\bar{\mathbf{f}}(\mathbf{p}^*) - \bar{\mathbf{f}}(\mathbf{p}^* - N\hat{\mathbf{e}}_x)}{N}$$

where $\bar{\mathbf{f}}$ denotes a tangent-direction box average over $2N{+}1$ samples. Project outward as a straight line.

Exact for linear fields. Gradient drifts for curving fields proportional to the squared distance from the edge.

## Order 2: quadratic extrapolation

The second-order Taylor expansion: fit a parabola through three points along the normal direction (edge, $N$ inward, $2N$ inward) using Lagrange interpolation:

$$p(t) = f_0 L_0(t) + f_1 L_1(t) + f_2 L_2(t)$$

where the basis functions $L_i$ are the Lagrange polynomials for nodes $(0, -b_1, -b_2)$ along the normal:

$$L_0(t) = \frac{(t+b_1)(t+b_2)}{b_1 b_2}, \quad L_1(t) = \frac{-t(t+b_2)}{b_1(b_2-b_1)}, \quad L_2(t) = \frac{t(t+b_1)}{b_2(b_2-b_1)}$$

Evaluate at $t = \Delta$ to get the predicted UV value.

Exact for quadratic fields. For the unevenly-clamped case (when $b_2 \neq 2 b_1$ because we hit the trusted edge), the Lagrange form still works correctly. When the curvature is zero, the parabola degenerates to a line, so order=2 reduces to order=1 for linear inputs.

The trade-off: quadratic mode amplifies noise harder than linear because the second-difference (curvature) gets multiplied by $\Delta^2$. Smoothing of 4 or more is recommended in quadratic mode.

## Why edge smoothing exists

Slope estimation from just two pixels is brutally sensitive to noise. The first working version did `slope = edge - one_pixel_inward`. Per-pixel jitter in those two samples becomes the slope, and multiplying that noisy slope by 1000+ pixels of padding turns tiny noise into massive streaks.

The smoothing parameter $N$ does two things to reduce variance:

1. **Wider baseline** — fit the slope between the edge and a pixel $N$ steps inward. Variance scales as $1/N^2$.
2. **Tangent averaging** — average $2N{+}1$ samples along the edge before computing the difference. Additional variance reduction by $1/(2N{+}1)$.

Combined variance reduction at $N{=}8$ is about 1100×, giving streak amplitude reduction of ~33×.

The bias-variance trade-off: tangent averaging is unbiased only if the field is locally constant along the tangent. Real edge curvature introduces a small bias proportional to the curvature scaled by $N^2$. The 8–16 sweet spot balances these.

## The corner case

When the output pixel is off the bbox in both axes (a corner region), each axis contributes independently:

$$\mathbf{f}(\mathbf{p}) \approx \mathbf{a} + \delta_x(\Delta_x) + \delta_y(\Delta_y)$$

This drops the bilinear cross-term $\mathbf{s}_{xy} \Delta_x \Delta_y$ that a true 2D Taylor expansion would include. For typical ST maps this is small enough to ignore.

## Anchor formulation (v2)

The anchor is `sampleUV(clamped)` — the raw value at the closest edge pixel. The per-axis contributions are *deltas from this anchor*. This means at the boundary itself ($\Delta = 0$), the contributions vanish and the output equals the raw boundary value, matching the inside-bbox sampling exactly. No discontinuity.

In v1, the anchor was the smoothed edge value, which introduced a tiny boundary jump (invisible in practice). v2 fixes this for cleanliness.

## Auto-analyze edge detection

The auto-analyze button uses Python sampling instead of a kernel pass:

1. For each of the four edges, sample 12 points along the tangent at varying normal depths (0 through 32 pixels inward)
2. At each depth, take the median U and V across the tangent samples
3. Fit a linear trend to the inner half of the depth profile (assumed clean)
4. Walk from the outermost depth inward; first depth where both U and V residuals fall within 5σ of the trend is the trim count

This catches obvious cases — black borders, abrupt edge breaks, anti-aliasing transitions — but is a heuristic, not a perfect detector. Manual trim values remain available as a fallback.

## Bounds detection

The kernel reads `src.bounds` inside `init()`:

```c
void init() {
  srcOrigin = int2(src.bounds.x1, src.bounds.y1);
  srcSize   = int2(src.bounds.x2 - src.bounds.x1,
                   src.bounds.y2 - src.bounds.y1);
  // apply trim
  trustedMin = int2(trim.x, trim.z);
  trustedMax = int2(srcSize.x - 1 - trim.y, srcSize.y - 1 - trim.w);
}
```

`src.bounds` is the actual data window reported by Nuke — independent of any upstream Crop, Reformat, or expansion ops. The sampler uses `srcOrigin` as its base, so reads always hit real data instead of clamped-to-edge dead zones.

## Group-level Python

The BlinkScript kernel only knows pixels and slopes. The wrapping Group handles everything that talks to Nuke's node graph:

- `knobChanged` callback fires on input change or any UI knob change
- Reads input bbox via `nuke.Node.bbox()` at current frame
- Computes `padOffset` for centering (or reads manual override)
- Combines `uniform_trim` with per-edge overrides into a final `int4 trim` value
- Rewrites the BlinkScript's `format` knob to the target output size
- Pushes `padOffset`, `extrapolation`, `smoothing`, `order`, `trim` into kernel params

The kernel itself lives in `~/.nuke/STMapOverscan_kernel.rpp` rather than embedded inline. This avoids a Nuke quirk where setting `kernelSource` via Python's `setValue` doesn't always flush before recompile, throwing a syntax error on the first line of the kernel even when the source is valid. Loading via `kernelSourceFile` is the same code path BlinkScript uses for manual edits, so it behaves predictably.

## Performance

Per output pixel, in `linear` mode with `smoothing = N`:

- Inside trusted region: 1 sample
- Outside, order 1: `2 * (2N+1)` samples per active axis = up to `8N+4` for a corner
- Outside, order 2: `3 * (2N+1)` samples per active axis = up to `12N+6` for a corner

For `N=8`, order 2: 102 samples per padded corner pixel. On RTX-class GPUs, a 2500×2500 output runs in low double-digit milliseconds.

## What it doesn't do

- **Doesn't extrapolate cubic-or-higher curvature.** Order 2 is exact for quadratic fields, approximates higher orders for moderate distances. Cubic order would be the next upgrade.
- **Doesn't include the bilinear cross-term in corner extrapolation.** Each axis contributes independently. Saddle-like fields would benefit from a 2D fit but require samples deeper into the bbox interior.
- **Auto-analyze is heuristic.** Catches obvious bad edges; subtle cases need manual trim values.
