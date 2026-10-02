/**
 * CROOKSLDN tokens — copied from crooks.css (dark), not reinterpreted.
 * The app should be indistinguishable in palette from the website.
 */
export const colour = {
  ground: '#0B0A0E',
  panel: '#0E0C13',
  tray: '#1F1C28',
  line: '#3A2F4A',
  purple: '#542578',
  accent: '#A77AC7',
  text: '#DDD7C9',
  dim: '#8A8377',
  press: '#1A1626',
  red: '#C95450',
  onPurple: '#DDD7C9',
} as const;

/**
 * Faces. "CRX Mono" on the website is Space Mono renamed (see crooks.css);
 * VT323 is the terminal display face. Both SIL OFL, loaded in the root layout.
 */
export const font = {
  display: 'VT323_400Regular',
  mono: 'SpaceMono_400Regular',
  monoBold: 'SpaceMono_700Bold',
} as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/** House rules: square corners, 1px rules, no shadows. */
export const hairline = 1;

/** Apple's minimum comfortable tap target. */
export const TAP = 44;
