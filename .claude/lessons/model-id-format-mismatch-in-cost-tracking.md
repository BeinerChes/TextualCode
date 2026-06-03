# model-id-format-mismatch-in-cost-tracking

When comparing model IDs from different SDK sources, verify they use identical formatting; AssistantMessage.model lacks tier suffixes that model_usage keys carry (e.g., [1m]), so strip suffixes before comparing or cost will systematically misattribute to the wrong bucket.

_Category: Cost Tracking_
