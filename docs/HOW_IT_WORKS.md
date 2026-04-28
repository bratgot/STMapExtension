# How STMapOverscan Works

## What an ST map is

An ST map encodes a per-pixel lookup. Red and green channels hold normalized UV coordinates (0..1) telling a downstream STMap node *go fetch the pixel at this location in the source image*. Identity ST map → image returns unchanged. Warped ST map → lens distortion, morph, or whatever remap was baked in.

## What "cropped" means

When an ST map's bbox has been trimmed to only the region containing valid UV data, everything outside the bbox is missing. The values inside are still correct — there just aren't pixels beyond the edges. This is a problem when the downstream operation needs UV samples from outside that region (undistorting into an overscan plate, warping something larger than the map's bbox, etc.).

The tool's job: manufacture plausible UV values for that padded region by extending the existing gradient outward.

## The core algorithm

For every output pixel:

1. Compute source-space position: `srcPos = outputPos - padOffset`
2. If `srcPos` falls inside the source bbox → sample directly
3. If outside → find nearest edge pixel, compute local slope, project outward:
   ```
   uv = edge + slope_x * dx + slope_y * dy
   ```

For a unit ST map with constant ~0.00179/pixel gradient in R, extrapolating 1000 pixels past the left edge gives ~−1.75 — exactly what you'd want if the original map had gone from (−1.75, −1.75) to (+2.74, +2.74) before being cropped.

## Why edge smoothing exists

Slope estimation from just two pixels is brutally sensitive to noise. The first working version did `slope = edge - one_pixel_inward`. Per-pixel jitter in those two samples becomes the slope, and multiplying that noisy slope by 1000+ pixels of padding turns tiny noise into massive streaks.

The smoothing knob fixes this two ways:

1. **Wider baseline** — instead of a 1-pixel delta, fit the slope between the edge and a pixel `N` steps inward. Averages noise over a longer baseline.
2. **Tangent averaging** — before computing the slope, average `2N+1` samples along the edge direction. Each row's slope is derived from a smoothed edge strip, not one noisy pixel.

Trade-off: too much smoothing flattens real edge curvature. For synthetic linear maps, you could crank it to 64 with no harm. For real lens distortion maps, 8–16 preserves enough curvature to look right while killing the noise streaks.

## Bounds detection

The earlier broken version had `srcSize` as a knob the user (or callback) had to keep in sync. Brittle. The fixed version reads `src.bounds` inside the kernel's `init()`:

```c
void init() {
  srcOrigin = int2(src.bounds.x1, src.bounds.y1);
  srcSize   = int2(src.bounds.x2 - src.bounds.x1,
                   src.bounds.y2 - src.bounds.y1);
}
```

`src.bounds` is the actual data window reported by Nuke — independent of any upstream Crop, Reformat, or expansion ops. The sampler uses `srcOrigin` as its base, so reads always hit real data instead of clamped-to-edge dead zones.

## The four modes

| Mode | Code branch | Behavior |
|------|-------------|----------|
| `clamp` (0) | `uv = edge` | Repeat edge value into padding |
| `linear` (1) | gradient projection | Extends the gradient — default for ST maps |
| `zero` (2) | `uv = (0,0)` | Fill padding with black, debug mode |
| `fade` (3) | `uv = edge * fade_factor` | Soft falloff toward black across pad distance |

## Group-level Python

The BlinkScript kernel only knows pixels and slopes. The wrapping Group handles everything that talks to Nuke's node graph:

- `knobChanged` callback fires on input change or any UI knob change
- Reads input bbox via `nuke.Node.bbox()` at current frame
- Computes `padOffset` for centering (or reads manual override)
- Rewrites the BlinkScript's `format` knob to the target output size
- Pushes `padOffset`, `extrapolation` mode, `smoothing` into kernel params

The kernel itself lives in `~/.nuke/STMapOverscan_kernel.rpp` rather than embedded inline. This avoids a Nuke quirk where setting `kernelSource` via Python's `setValue` doesn't always flush before recompile, throwing a syntax error on the first line of the kernel even when the source is valid. Loading via `kernelSourceFile` is the same code path BlinkScript uses for manual edits, so it behaves predictably.

## What it doesn't do

- **Doesn't extrapolate non-linear functions accurately at long distances.** Linear is exact for linear gradients, very close for slowly-curving ones, drifts for strong curvature. Acceptable for most uncropping tasks; not a substitute for re-rendering the original distortion.
- **Doesn't handle animated bboxes inside the kernel.** The bbox is read in `init()` per cook, which is fine — but the *Python callback* only refires on knob changes and `inputChange`, so if your input's bbox animates wildly, scrub a knob to refresh `padOffset`. Bounds inside the kernel are always live.
- **Doesn't currently support a quadratic fit.** Linear-only by design. PR-friendly upgrade path: replace the slope computation in the `linear` branch with a least-squares fit over the last `smoothing` pixels, then evaluate the polynomial at `dx, dy`.

## Performance

Per output pixel, in `linear` mode with `smoothing = N`:

- Inside bbox: 1 sample
- Outside bbox: `2 * (2N+1) + 1` samples = `4N+3` samples
  (one smoothed edge + one smoothed inner per active axis)

For `N=8` that's 35 samples per padded pixel, 1 per inside pixel. On RTX-class GPUs, a 2500×2500 output runs in single-digit milliseconds.
