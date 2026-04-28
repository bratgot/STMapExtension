# STMapExtension

A Nuke tool for **uncropping ST maps** — extending UV values past their original bbox by extrapolating the gradient outward.

When an ST map gets cropped (so its data window no longer covers full 0..1 in U and V), downstream STMap nodes can't sample beyond the bbox edges. This tool reconstructs plausible UV values for the padded region by fitting per-axis slopes to the outermost pixels and projecting them outward, with smoothing to suppress noise amplification.

![preview placeholder](docs/images/preview.png)

## Features

- BlinkScript GPU implementation, runs at viewer speed
- Four extrapolation modes: `clamp`, `linear`, `zero`, `fade`
- Edge smoothing knob to suppress noise streaks in the padded region
- Auto-centering of source within target canvas
- Reads source bbox from `src.bounds` — no manual size sync needed
- Self-contained Group node, no external dependencies

## Installation

### Quick start

1. Clone this repo:
   ```bash
   git clone https://github.com/bratgot/STMapExtension.git
   ```
2. In Nuke's Script Editor:
   ```python
   exec(open('/path/to/STMapExtension/install.py').read())
   ```

The first run writes the kernel to `~/.nuke/STMapOverscan_kernel.rpp` and creates a new `STMapOverscan1` group node.

### Persistent menu install

Copy `install/menu.py.example` into your `~/.nuke/menu.py` (or merge if you already have one), edit `STMAP_INSTALL_PATH` to point at your clone, and you'll get a menu entry plus an `Shift+O` hotkey.

## Usage

1. Connect a cropped ST map to the input
2. Set `width` / `height` on the **Overscan** tab to the target uncropped size
3. Pick an extrapolation `mode` (default: `linear`)
4. Adjust `edge smoothing` if you see streak artifacts (default: `8`, sweet spot: `8`–`16`)

The node reads the input's bbox at the current frame and centers the source automatically. Disable `auto-center` to drive `pad offset` manually.

## How it works

For each output pixel:

1. Find the corresponding source-space coordinate (subtract pad offset)
2. If inside the bbox → sample directly
3. If outside → walk to the nearest edge pixel, fit a slope from a `smoothing`-pixel baseline averaged along the tangent, project that slope `N` pixels outward

The tangent-direction averaging is the key to clean output. A slope built from just two pixels turns per-pixel noise in the source into multi-thousand-pixel streaks across the padded region; averaging the edge samples first keeps the slope stable.

The kernel reads `src.bounds` in `init()` so the data window is auto-detected at every cook — no manual size knobs to keep in sync.

See [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) for a deeper walkthrough.

## Modes

| Mode | Behavior |
|------|----------|
| `clamp` | Repeat edge values into the padded region |
| `linear` | Extrapolate the gradient (recommended for ST maps) |
| `zero` | Fill padding with black |
| `fade` | Soft falloff from edge values to black |

## Files

```
STMapExtension/
├── install.py                     # main installer (run in Nuke)
├── kernel/
│   └── STMapOverscan_kernel.rpp   # standalone BlinkScript kernel
├── install/
│   └── menu.py.example            # menu.py snippet for studio install
├── examples/
│   └── STMapCropped.exr           # test ST map (linear unit gradient)
├── docs/
│   ├── HOW_IT_WORKS.md
│   └── images/
├── LICENSE
└── README.md
```

## Caveats

Linear extrapolation is exact for linear gradients and very good for slowly-curving ones. For ST maps with strong curvature near the edges (fisheye, anamorphic), the extrapolated region drifts from true lens behavior the further out you go — it stays accurate near the edge and degrades smoothly. If that becomes a problem, the upgrade path is a quadratic fit; PRs welcome.

`smoothing` only affects `linear` mode. The other three modes ignore it.

## Compatibility

Tested on Nuke 14.1+. Should work on any Nuke with BlinkScript GPU support.

## License

MIT — see [LICENSE](LICENSE).

## Credit

Built by [Marten Blumen](https://github.com/bratgot).
