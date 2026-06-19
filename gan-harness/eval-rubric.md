# Evaluation Rubric — SmartGen Extension Design

Score each dimension 1-10. Final score = weighted average.

---

## Design Quality (weight: 0.35)

**10**: Would win a Dribbble Shot of the Week. Immediately distinctive. Every spacing, color, and typographic decision feels intentional. Looks better than 99% of Chrome extensions on the market.

**7**: Clearly above average. Has a real visual identity. A few rough edges or safe choices.

**4**: Generic. Looks like a default theme applied to a template. Nothing that distinguishes it.

**1**: Unstyled or broken. Plain HTML.

**Ask yourself**: If this appeared in a design blog as a Chrome extension UI showcase, would it feel at home?

---

## Originality (weight: 0.30)

**10**: Something genuinely unexpected. A layout paradigm, interaction, or visual metaphor you haven't seen in a browser extension before. Makes you think "I wish more extensions looked like this."

**7**: Borrows from modern design trends (glassmorphism, dark premium) but applies them well. Not derivative.

**4**: Clearly inspired by another specific product without enough transformation.

**1**: Default browser extension boilerplate.

**Ask yourself**: What is the ONE design idea here that I haven't seen before?

---

## Craft (weight: 0.25)

**10**: Micro-animations that feel natural. Hover states that feel designed. Text reveals that feel like watching a real-time captioning tool. No visual glitches. Pixel-perfect spacing.

**7**: Most interactions feel right. Maybe one animation feels off or one state is missing a hover treatment.

**4**: Functional but rough. Animations abrupt, spacing inconsistent.

**1**: No animations, broken layouts.

**Ask yourself**: Does the Start button feel special? Do the text animations feel like a feature, not an afterthought?

---

## Functionality (weight: 0.10)

**10**: All required elements present (see spec). WebSocket connection logic in place. State machine (idle → connecting → listening → translating) wired. Word-by-word text reveal working.

**7**: Most elements present. Minor missing piece (e.g., one selector missing).

**4**: Half of required elements missing.

**1**: Skeleton only.

---

## Scoring Formula

```
final_score = (Design × 0.35) + (Originality × 0.30) + (Craft × 0.25) + (Functionality × 0.10)
```

**Pass threshold: 7.5**

## Common Failure Modes to Watch For

- Blue/purple gradient on white background (too generic)
- Cards with uniform border-radius everywhere (boring)
- Start button that looks the same as every other button
- Translation text that appears instantly (no reveal animation)
- Overlay that looks like a webpage, not a caption layer
- Font sizes too large (extension popups should be information-dense)
- Missing the dark/glass depth (flat opaque dark cards don't count)
