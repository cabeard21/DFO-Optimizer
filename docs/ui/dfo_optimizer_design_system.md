---
name: "DFO Optimizer Workbench"
description: "A crisp, data-dense light-mode workbench for Daggerfall Online spellcasting optimization, pairing arcane indigo authority with parchment-white clarity and tabular monospace precision."
---

## Overview

**DFO Optimizer Workbench** is a deterministic, local-first engineering interface for Daggerfall Online spellcasting theorycraft, inspired by the OSRS Gear Optimizer. It serves analytical RPG players and build engineers who need verifiable mechanics, exact legality constraints, and side-by-side numeric tradeoffs without visual clutter.

The design style is **Modern Technical Utility**: high-contrast light surfaces (`#FBF8FF` and `#FFFFFF`) paired with deep arcane indigo (`#15196C`) and warm amber-bronze (`#632C00` / `#8E4D20`) accents. Every screen prioritizes scannable data tables, locked constraint badges, and clear primary actions over decorative chrome.

## Colors

The palette anchors on a deep Arcane Indigo primary (`#15196C`) for primary actions, active states, and verified legality indicators, balanced by cool mineral slate surfaces (`#FBF8FF` to `#E4E1E9`) and warm bronze-amber tertiary tones (`#421B00` / `#8E4D20`) for Daggerfall heritage and caution states.

- **Primary:** Arcane Indigo for primary CTAs, active navigation indicators, and verified `-12` difficulty locks.
- **Secondary:** Cool slate-indigo for secondary controls, filter chips, and muted metadata.
- **Tertiary:** Warm bronze for milestone badges, enchantment highlights, and specialty tags.
- **Status:** Semantic emerald (`#146C2E`), amber (`#8A5300`), and crimson (`#BA1A1A`) used strictly for legality, warning/assumption status, and error/infeasible states.

```yaml
colors:
  success: "#146C2E"
  on-success: "#FFFFFF"
  success-container: "#D3F8DF"
  on-success-container: "#073B17"
  warning: "#8A5300"
  on-warning: "#FFFFFF"
  warning-container: "#FFE0B2"
  on-warning-container: "#4A2C00"
  light:
    primary: "#15196C"
    on-primary: "#FFFFFF"
    primary-container: "#2D3282"
    on-primary-container: "#FFFFFF"
    secondary: "#5A5C7D"
    on-secondary: "#FFFFFF"
    secondary-container: "#D6D7FE"
    on-secondary-container: "#171936"
    tertiary: "#421B00"
    on-tertiary: "#FFFFFF"
    tertiary-container: "#632C00"
    on-tertiary-container: "#FFDBC8"
    error: "#BA1A1A"
    on-error: "#FFFFFF"
    error-container: "#FFDAD6"
    on-error-container: "#410002"
    background: "#FBF8FF"
    on-background: "#1B1B20"
    surface: "#FBF8FF"
    surface-dim: "#DCD9E0"
    surface-bright: "#FFFFFF"
    surface-container-lowest: "#FFFFFF"
    surface-container-low: "#F5F2FA"
    surface-container: "#F0ECF4"
    surface-container-high: "#EAE7EF"
    surface-container-highest: "#E4E1E9"
    on-surface: "#1B1B20"
    surface-variant: "#E3E1EF"
    on-surface-variant: "#464651"
    outline: "#777682"
    outline-variant: "#C7C5D3"
    inverse-surface: "#303036"
    inverse-on-surface: "#F3EFF7"
    inverse-primary: "#BFC2FF"
  dark:
    primary: "#BFC2FF"
    on-primary: "#212576"
    primary-container: "#2D3282"
    on-primary-container: "#E0E0FF"
    secondary: "#C3C3EA"
    on-secondary: "#2C2E4C"
    secondary-container: "#424464"
    on-secondary-container: "#E0E0FF"
    tertiary: "#FFB68A"
    on-tertiary: "#522300"
    tertiary-container: "#632C00"
    on-tertiary-container: "#FFDBC8"
    error: "#FFB4AB"
    on-error: "#690005"
    error-container: "#93000A"
    on-error-container: "#FFDAD6"
    background: "#131318"
    on-background: "#E4E1E9"
    surface: "#131318"
    surface-dim: "#131318"
    surface-bright: "#39393E"
    surface-container-lowest: "#0E0E13"
    surface-container-low: "#1B1B20"
    surface-container: "#1F1F25"
    surface-container-high: "#2A292F"
    surface-container-highest: "#35343A"
    on-surface: "#E4E1E9"
    surface-variant: "#464651"
    on-surface-variant: "#C7C5D3"
    outline: "#908F9C"
    outline-variant: "#464651"
    inverse-surface: "#E4E1E9"
    inverse-on-surface: "#303036"
    inverse-primary: "#5156A7"
```

## Typography

This design system pairs **Alata** for crisp, geometric display and section headings with **Instrument Sans** for clean, legible interface controls and body copy. **Spline Sans Mono** handles all numeric metrics, difficulty scores, SP costs, DPS figures, and commit SHAs with tabular alignment (`tabular-nums`).

```yaml
typography:
  display-md:
    fontFamily: "Alata"
    fontSize: 36px
    fontWeight: 400
    lineHeight: 44px
    letterSpacing: -0.5px
  display-md-mobile:
    fontFamily: "Alata"
    fontSize: 28px
    fontWeight: 400
    lineHeight: 36px
    letterSpacing: -0.25px
  headline-lg:
    fontFamily: "Alata"
    fontSize: 28px
    fontWeight: 400
    lineHeight: 36px
    letterSpacing: -0.25px
  headline-md:
    fontFamily: "Alata"
    fontSize: 22px
    fontWeight: 400
    lineHeight: 28px
    letterSpacing: 0px
  title-lg:
    fontFamily: "Instrument Sans"
    fontSize: 18px
    fontWeight: 600
    lineHeight: 24px
    letterSpacing: 0px
  title-md:
    fontFamily: "Instrument Sans"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 20px
    letterSpacing: 0px
  body-lg:
    fontFamily: "Instrument Sans"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 22px
    letterSpacing: 0px
  body-md:
    fontFamily: "Instrument Sans"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
    letterSpacing: 0px
  label-lg:
    fontFamily: "Instrument Sans"
    fontSize: 14px
    fontWeight: 600
    lineHeight: 20px
    letterSpacing: 0.1px
  label-md:
    fontFamily: "Instrument Sans"
    fontSize: 12px
    fontWeight: 600
    lineHeight: 16px
    letterSpacing: 0.2px
  mono-md:
    fontFamily: "Spline Sans Mono"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 18px
    letterSpacing: 0px
  mono-sm:
    fontFamily: "Spline Sans Mono"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 16px
    letterSpacing: 0px
```

## Layout & Spacing

The desktop application uses a persistent **240px left navigation rail** paired with a fluid 12-column main workspace (`max-w-7xl`, 16px–24px gutters). An 8px base grid (with 4px half-steps for compact table cells and badges) keeps dense parameter panels, loadout slots, and progression timelines aligned.

```yaml
spacing:
  gutter-xs: 4px
  gutter-sm: 8px
  gutter-md: 16px
  gutter-lg: 24px
  gutter-xl: 32px
  section: 40px
  page-margin: 24px
```

## Elevation & Depth

Hierarchy relies on **tonal surface layering** and **crisp 1px hairline outlines** (`outline-variant`), avoiding heavy drop shadows. The page canvas sits on `surface` (`#FBF8FF`), primary workspace cards sit on `surface-container-lowest` (`#FFFFFF`), and secondary summary bands or inset panels sit on `surface-container-low` (`#F5F2FA`). Interactive hover states shift surface tint rather than lifting with blur shadows.

## Shapes

A disciplined, technical corner-radius scale: compact 4px–6px radii for chips, badges, and table inputs; 8px for primary buttons and form controls; and 12px for workspace cards and modals.

```yaml
rounded:
  sm: 4px
  DEFAULT: 8px
  md: 12px
  lg: 16px
  full: 9999px
```

## Motion & Micro-interaction

Motion is crisp and functional. Interactive state changes (button presses, tab switches, constraint toggles) complete in 120ms with `ease-out`. Panel transitions and drawer reveals settle in 200ms. No decorative looping animations; all numeric updates snap cleanly.

```yaml
motion:
  state-change:
    duration: 120ms
    delay: 0ms
    timingFunction: ease-out
  surface-enter:
    duration: 200ms
    delay: 0ms
    timingFunction: cubic-bezier(0.2, 0, 0, 1)
  surface-exit:
    duration: 140ms
    delay: 0ms
    timingFunction: cubic-bezier(0.3, 0, 1, 1)
```

## Voice & Content Strategy

- **Tone of voice:** Direct, analytical, and transparent. State exact numbers, legality rules, and assumptions plainly (e.g., `"Difficulty -12 (0.30x)"`, `"Exact over 1,420 candidates"`, `"Assumption: 100% uptime not applied"`).
- **Capitalisation:** Sentence case for headings, labels, and actions (`"Optimize character"`, `"Export class JSON"`). Title case only for proper nouns and DFO game terms (`"High Elf"`, `"Spellmaker"`, `"Dhargo PvE"`).
- **Action labels:** Verb-first, outcome-specific (`"Run class search"`, `"Compare loadouts"`, `"Lock slot"`).
- **Numbers & units:** Always use `tabular-nums` with `mono-md` or `mono-sm` for SP, HP, DPS, difficulty points, percentages, and level milestones.

## Components

Component implementations live as individual HTML sticker sheet files in
`components/`. Each file contains the canonical, styled HTML components with
`<!-- COMPONENT: name -->` comment markers. Read each file before use.

- **Badge** → `@components/badge.html` — `badge-numeric`, `badge-dot`
- **Button** → `@components/button.html` — `button-primary`, `button-icon`, `button-with-icon`
- **Card** → `@components/card.html` — `card-elevated`, `card-action`, `card-interactive`, `card-interactive-2`
- **Table** → `@components/table.html` — `table-standard`, `table-interactive`, `table-selectable`
