# preserve-widget-public-api-during-refactor

When refactoring a widget's internal visual implementation, preserve its public method signatures (start/stop, add_tokens, show_notice) to avoid forcing cascading changes in dependent code; constrain refactoring to the internal component tree and internal logic.

_Category: UI_
