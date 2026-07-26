/**
 * Categorical series colours, stepped for this dark surface and validated for
 * colour-vision-deficiency separation (OKLab ΔE ≥ 8 on every adjacent pair),
 * chroma, and contrast against the surface. Assigned in fixed order, never
 * cycled — a sixth category folds into "Other" rather than reusing a hue.
 */
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"] as const;

/** Single-series mark colour, matching the app accent. */
export const ACCENT = "#c6f24e";

export const OTHER = "#5a5a62";
