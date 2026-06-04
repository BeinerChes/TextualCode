# inject-coordinate-metadata-through-render-delegates

Explicitly inject coordinate metadata (offsets, positions) when delegating rendering to a lower-level abstraction, or features like selection will silently degrade from partial-range to whole-widget because the compositor can't map mouse positions to text coordinates.

_Category: Rendering_
