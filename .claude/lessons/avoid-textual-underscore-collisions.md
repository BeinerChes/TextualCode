# avoid-textual-underscore-collisions

Never name instance attributes with single underscores matching parent class internals (_running on MessagePump, _render on Widget); use descriptive compound names like _turn_active to prevent silent attribute shadowing that breaks behavior without raising errors.

_Category: Textual_
