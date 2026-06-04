# blend-transparent-theme-against-opaque-base

When applying themed colors with transparency (e.g., primary@50%), blend them against the opaque widget style (visual_style + selection_style).rich_style() to produce a readable solid color; calling .rich_style on the transparent theme alone yields an invisible result.

_Category: UI / Color Styling_
