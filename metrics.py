from prometheus_client import Counter, Histogram


ocr_latency_seconds = Histogram(
    "ocr_latency_seconds",
    "End-to-end OCR latency",
    labelnames=("doc_type",),
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0),
)

ocr_confidence = Histogram(
    "ocr_confidence",
    "Confidence (0-100) per OCR call",
    labelnames=("doc_type",),
    buckets=(0, 25, 40, 55, 65, 78, 85, 92, 100),
)

ocr_errors_total = Counter(
    "ocr_errors_total",
    "OCR errors by code",
    labelnames=("code",),
)

# THE metric to track parser quality on real traffic.
# Increment on every successful extraction, per (doc_type, field) — True if value not None.
ocr_field_present_total = Counter(
    "ocr_field_present_total",
    "Whether a parsed field was present (1) or null (0)",
    labelnames=("doc_type", "field", "present"),
)
