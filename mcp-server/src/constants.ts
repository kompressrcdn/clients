/** FormData field name for video quality selection, matching API contract. */
export const KMP_QUALITY_FIELD = "kmp-quality";

/** Valid video quality presets accepted by the API. */
export const VALID_QUALITIES = ["480p", "720p", "1080p", "4k"] as const;

/** Union type of valid quality values. */
export type VideoQuality = (typeof VALID_QUALITIES)[number];
