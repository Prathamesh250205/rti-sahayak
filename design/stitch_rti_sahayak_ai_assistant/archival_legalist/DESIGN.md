---
name: Archival Legalist
colors:
  surface: '#f8faf8'
  surface-dim: '#d9dad9'
  surface-bright: '#f8faf8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f2'
  surface-container: '#edeeec'
  surface-container-high: '#e7e8e7'
  surface-container-highest: '#e1e3e1'
  on-surface: '#191c1b'
  on-surface-variant: '#404946'
  inverse-surface: '#2e3130'
  inverse-on-surface: '#f0f1ef'
  outline: '#707976'
  outline-variant: '#bfc8c5'
  surface-tint: '#2f685f'
  primary: '#00352f'
  on-primary: '#ffffff'
  primary-container: '#0e4d45'
  on-primary-container: '#84bdb2'
  inverse-primary: '#98d2c7'
  secondary: '#924c00'
  on-secondary: '#ffffff'
  secondary-container: '#fda053'
  on-secondary-container: '#6f3900'
  tertiary: '#4c2313'
  on-tertiary: '#ffffff'
  tertiary-container: '#673827'
  on-tertiary-container: '#e4a38c'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#b4eee2'
  primary-fixed-dim: '#98d2c7'
  on-primary-fixed: '#00201c'
  on-primary-fixed-variant: '#124f47'
  secondary-fixed: '#ffdcc4'
  secondary-fixed-dim: '#ffb77f'
  on-secondary-fixed: '#2f1500'
  on-secondary-fixed-variant: '#6f3800'
  tertiary-fixed: '#ffdbcf'
  tertiary-fixed-dim: '#fbb79f'
  on-tertiary-fixed: '#341004'
  on-tertiary-fixed-variant: '#6a3a29'
  background: '#f8faf8'
  on-background: '#191c1b'
  surface-variant: '#e1e3e1'
typography:
  display-lg:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 60px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Source Serif 4
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  headline-md:
    fontFamily: Source Serif 4
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-hindi:
    fontFamily: Noto Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 30px
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
  caption:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 24px
  lg: 48px
  xl: 80px
  max-width: 1200px
  gutter: 24px
---

## Brand & Style

This design system is built on the principles of **Statutory Clarity** and **Archival Utility**. It draws inspiration from classic broadsheet journalism and official legal documentation, translated for a high-performance AI context. The aesthetic is "Digital Paper"—prioritizing legibility and structural permanence over decorative trends.

The interface evokes an emotional response of trust, impartiality, and civic duty. It avoids all forms of skeuomorphism, translucency, or organic gradients in favor of a strictly flat, high-contrast, and highly organized layout. It is designed for users navigating complex bureaucracy who require a calm, focused environment.

## Colors

The palette is anchored by a warm paper background to reduce eye strain during long reading sessions. 

- **Primary Ink (#12212E):** Used for all core text and structural borders to ensure maximum contrast and an authoritative "printed" feel.
- **Brand Deep Green (#0E4D45):** Reserved for statutory headers, official seals, and success-state indicators.
- **Accent Amber (#C6742A):** The primary action color. Used for citations, highlighting key legal phrases, and primary call-to-action buttons.
- **Muted Text (#5A6672):** Used for metadata, legal footnotes, and secondary labels.
- **Borders (#E3DDD2):** A low-contrast variation of the paper tone used to define document sections without visual clutter.

## Typography

The typographic system uses a strict hierarchy to separate "Statutory Content" from "UI Controls."

- **Source Serif 4** is the voice of authority. Use it for legal texts, RTI application drafts, and major headings. It should feel like a printed document.
- **Inter** provides a neutral, highly readable foundation for the functional aspects of the AI assistant and general body copy.
- **Noto Sans Devanagari** ensures that Hindi and Marathi translations maintain the same weight and legibility as the English counterparts.
- **JetBrains Mono** is used exclusively for "Section IDs," "Reference Numbers," and "Metadata Tags" to provide a modern, systematic contrast to the serif headings.

All body text must maintain a minimum of 16px to adhere to accessibility standards. Line heights are kept generous (1.6x) to facilitate scanning of long legal paragraphs.

## Layout & Spacing

This design system utilizes a **Fixed Centered Grid** for its primary reading experience. The content is constrained to a 1200px container to prevent line lengths from becoming illegible on ultra-wide monitors.

- **Rhythm:** An 8px base unit governs all padding and margins.
- **Desktop:** A 12-column grid with 24px gutters. Content should typically occupy the central 8 columns (approx. 800px) for maximum readability, with secondary metadata in the outer columns.
- **Mobile:** Margins shrink to 16px. Typography scales down slightly, and all 2-column layouts reflow to a single vertical stack.
- **Whitespace:** Use generous vertical spacing (48px+) between major legal sections to signify a change in context.

## Elevation & Depth

In keeping with the "Archival" aesthetic, this system is almost entirely flat. 

- **Tonal Layering:** Depth is achieved through color contrast rather than shadows. The `#F7F4EE` background acts as the base layer, with `#FFFFFF` surfaces used to highlight active "Work Areas" or "Document Editors."
- **Borders:** Sections are separated by 1px solid lines in `#E3DDD2`.
- **The "Ask" Bar:** The only exception to the "no shadow" rule is the floating AI input bar. It uses a very soft, highly diffused ambient shadow (`0 4px 20px rgba(18, 33, 46, 0.08)`) to indicate it sits above the document layer, always accessible to the user.

## Shapes

The shape language is disciplined and geometric. 

- **Cards:** Used for grouping RTI sections or search results, featuring a 12px radius.
- **Inputs:** Text fields and textareas use a smaller 8px radius to feel more precise and technical.
- **Interactive Elements:** Chips, tags, and status indicators use a "Pill" shape (9999px) to clearly differentiate them from layout containers.
- **Buttons:** Follow the input radius (8px) for a cohesive form-filling experience.

## Components

### Buttons
- **Primary Action:** Solid `#C6742A` (Amber) with white text. No gradients. 8px radius.
- **Secondary Action:** 1px border of `#12212E` with matching text. Background is transparent or white.
- **Ghost/Tertiary:** No border, `#12212E` text, subtle `#F7F4EE` background on hover.

### Input Fields
- White background, 1px `#E3DDD2` border.
- On focus: Border changes to `#12212E` with no "glow."
- Labels: Use `label-mono` style in `#5A6672`.

### Chips & Tags
- Pill-shaped.
- **Citation Tags:** Background `#F7F4EE`, border `#C6742A`, text `label-mono` in `#C6742A`.
- **Status Tags:** High contrast (e.g., Success uses `#1E7A5A` text on a light tint of the same color).

### Cards
- White background (`#FFFFFF`), 1px border (`#E3DDD2`). 
- No shadow.
- 12px corner radius.

### The Document Editor
- Uses the `Source Serif 4` font. 
- Features a vertical "statutory line" (2px solid `#0E4D45`) on the left side to indicate official AI-generated content.
- Inline citations should be styled with the `Accent Amber` color.