# Changelog

## v2.0.0 - 2026-05-01
### Added
- Quadratic extrapolation order (`order` knob: 1=linear, 2=quadratic)
  - Second-order Taylor expansion using Lagrange interpolation through 3 points along the normal
  - Better extrapolation for curving lens distortion (fisheye, anamorphic, wide-angle)
  - Reduces to linear when curvature is zero, so safe to leave on for any input
- Edge trim region
  - Uniform trim slider applies to all 4 edges
  - Per-edge override toggle exposes independent left/right/top/bottom sliders
  - Auto-Analyze Edges button samples the input, fits a linear trend, detects outliers, and sets per-edge trim
  - Reset Trim button to zero everything
- Trimmed pixels are now treated as outside the trusted region and replaced with extrapolated values

### Changed
- Anchor formulation cleaned up: `uv = sampleUV(clamped) + deltaX + deltaY`
  - Eliminates the small boundary discontinuity v1 had between inside-bbox and outside-bbox sampling
- Smoothing now defines both the slope baseline AND the tangent-direction average radius (was always equal in v1, now explicit)
- Sample bounds in `sampleSmoothed` clamp to the trusted region rather than the raw bbox

### Fixed
- N/A (v1 behavior preserved when order=1 and trim=0)

## v1.0.0 - 2026-04-29
### Added
- Initial release of STMapOverscan group node
- Four extrapolation modes: clamp, linear, zero, fade
- Edge smoothing knob to suppress noise streaks in linear mode
- Auto-centering and manual pad offset
- Bbox auto-detection via `src.bounds`
