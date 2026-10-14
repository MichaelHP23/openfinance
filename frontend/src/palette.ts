/**
 * Categorical series colours. Chosen and validated against the old dark surface for
 * colour-vision-deficiency separation (OKLab ΔE ≥ 8 on every adjacent pair); the
 * separation between hues carries over to the light theme, the contrast-against-surface
 * check has not been redone. Assigned in fixed order, never cycled — a sixth category
 * folds into "Other" rather than reusing a hue.
 */
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"] as const;

/** Single-series mark colour: a blue line over a pale fill. */
export const ACCENT = "#4f6df5";

export const OTHER = "#c3c3ca";
