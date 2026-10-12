/* GENERATED from packages/design-tokens/tokens.json by build.mjs. Do not edit. */
export const tokens = {
  "color": {
    "space": {
      "0": "#05070D",
      "1": "#0A0F1C",
      "2": "#111829",
      "3": "#1A2236"
    },
    "nebula": {
      "violet": "#1B1240",
      "teal": "#0B2A3A"
    },
    "accent": "#3EE0FF",
    "accent-2": "#9B7BFF",
    "cyan": "#3EE0FF",
    "violet": "#9B7BFF",
    "amber": "#FFB547",
    "rose": "#FF5FA2",
    "green": "#5BE49B",
    "blue": "#5B8CFF",
    "slate": "#8A97B5",
    "danger": "#FF5C5C",
    "ink": {
      "1": "#E8EEFF",
      "2": "#A9B4D0",
      "3": "#808CAC"
    },
    "glass": {
      "1": "rgba(16, 24, 42, 0.55)",
      "2": "rgba(16, 24, 42, 0.78)"
    },
    "hairline": {
      "1": "rgba(160, 190, 255, 0.12)",
      "2": "rgba(160, 190, 255, 0.24)"
    }
  },
  "font": {
    "display": "'Space Grotesk Variable', 'Space Grotesk', system-ui, sans-serif",
    "body": "'Inter Variable', Inter, system-ui, sans-serif",
    "mono": "'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, monospace"
  },
  "text": {
    "xs": "12px",
    "sm": "14px",
    "md": "16px",
    "lg": "20px",
    "xl": "24px",
    "2xl": "32px"
  },
  "radius": {
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "24px"
  },
  "blur": {
    "glass": "20px"
  },
  "motion": {
    "fast": "150ms",
    "base": "200ms",
    "slow": "250ms",
    "flight-min": "600ms",
    "flight-max": "1200ms",
    "ease": "cubic-bezier(0.2, 0.8, 0.2, 1)"
  },
  "z": {
    "universe": 0,
    "hud": 10,
    "panel": 20,
    "command": 30,
    "dialog": 40,
    "consent": 50
  }
} as const;

export type Tokens = typeof tokens;
