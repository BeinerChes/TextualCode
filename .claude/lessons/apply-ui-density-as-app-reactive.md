# apply-ui-density-as-app-reactive

Expose UI density (compact mode, margins, borders, padding) as a single reactive property on the App with a watcher that applies changes to all widgets at once; this pattern lets future Settings pages control density by simply setting `app.compact = value` without rework.

_Category: Architecture_
