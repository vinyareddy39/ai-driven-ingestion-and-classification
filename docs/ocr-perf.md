# OCR Pipeline Performance & Optimization Benchmark

## 1. System & Hardware Specification
- **GPU**: NVIDIA GeForce RTX 4050 Laptop GPU (6,141 MiB GDDR6 VRAM, Driver 591.86, CUDA Compute Capability 8.9)
- **CUDA Support**: CUDA 13.1 Driver / PyTorch CUDA 12.4 Runtime
- **PyTorch Build**: `torch-2.6.0+cu124`, `torchvision-0.21.0+cu124`
- **Python Virtual Environment**: `C:\ml\.venv311` (Python 3.11.9)
- **Baseline OCR Model**: `microsoft/trocr-base-printed`
- **Small OCR Model Variant**: `microsoft/trocr-small-printed`

---

## 2. Step 0: Baseline Performance Measurement (Unoptimized CPU, batch=1, float32, 300 DPI)

Measurement conducted on synthetic documents located in `data/test/`:
- `1page_sample.pdf` (1 page)
- `3page_sample.pdf` (3 pages)
- `10page_sample.pdf` (10 pages)
- `100page_sample.pdf` (100 pages)
- `scan_sample.png` (1-page 300 DPI image scan)

| File | Pages | Render (s/p) | Detect (s/p) | TrOCR (s/p) | Rest Pipeline (s/p) | Total (s/p) | Extrapolated Doc Total |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `1page_sample.pdf` | 1 | 0.0139 | 0.0232 | **63.5032** | 2.0543 | 65.5946 | 1.09 min |
| `3page_sample.pdf` | 3 | 0.0103 | 0.0121 | **64.3152** | 0.0507 | 64.3883 | 3.22 min |
| `10page_sample.pdf` | 10 | 0.0116 | 0.0123 | **64.9254** | 0.0716 | 65.0209 | 10.84 min |
| `100page_sample.pdf` | 100 | 0.0282 | 0.0114 | **64.9940** | 0.0583 | 65.0919 | 108.49 min |
| `scan_sample.png` | 1 | 0.0625 | 0.0120 | **62.4319** | 0.0631 | 62.5695 | 1.04 min |

### Bottleneck Analysis: Which Stage is the Slowest?
- **Page Render**: ~0.010 - 0.063 s/page (<0.1% of pipeline latency)
- **Line Detection**: ~0.011 - 0.023 s/page (<0.04% of pipeline latency)
- **TrOCR Line Recognition**: **62.43 - 64.99 s/page (96.5% - 99.8% of pipeline latency)**
- **Rest of Pipeline (Classify, Extraction, PII)**: ~0.051 - 0.072 s/page (after initial Presidio model warmup)

> [!IMPORTANT]
> **TrOCR line recognition is the overwhelming bottleneck**, taking over 62 seconds per page. The root cause is that on CPU with float32 and unbatched greedy decoding, running ~40 individual line crops per page forces 40 sequential autoregressive transformer forward passes. A 100-page document would take over 108 minutes to process under this baseline.

---

### OCR Pipeline Performance (CPU, batch=1)

| File | Pages | Render (s/p) | Detect (s/p) | TrOCR (s/p) | Rest Pipeline (s/p) | Total (s/p) | Extrapolated Doc Total |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `1page_sample.pdf` | 1 | 0.0381 | 0.0000 | **0.0000** | 2.5913 | 2.6294 | 2.63s |
| `3page_sample.pdf` | 3 | 0.0143 | 0.0000 | **0.0000** | 0.0552 | 0.0695 | 0.21s |
| `10page_sample.pdf` | 10 | 0.0138 | 0.0000 | **0.0000** | 0.0556 | 0.0694 | 0.69s |
| `100page_sample.pdf` | 100 | 0.0149 | 0.0000 | **0.0000** | 0.0658 | 0.0808 | 8.08s |
| `scan_sample.png` | 1 | 0.0652 | 0.0270 | **81.5231** | 0.0780 | 81.6932 | 1.36 min |


### OCR Pipeline Performance (CUDA, batch=16)

| File | Pages | Render (s/p) | Detect (s/p) | TrOCR (s/p) | Rest Pipeline (s/p) | Total (s/p) | Extrapolated Doc Total |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `1page_sample.pdf` | 1 | 0.0096 | 0.0000 | **0.0000** | 2.0640 | 2.0736 | 2.07s |
| `3page_sample.pdf` | 3 | 0.0055 | 0.0000 | **0.0000** | 0.0528 | 0.0584 | 0.18s |
| `10page_sample.pdf` | 10 | 0.0049 | 0.0000 | **0.0000** | 0.0517 | 0.0567 | 0.57s |
| `100page_sample.pdf` | 100 | 0.0048 | 0.0000 | **0.0000** | 0.0572 | 0.0620 | 6.20s |
| `scan_sample.png` | 1 | 0.0602 | 0.0226 | **2.0144** | 0.0617 | 2.1589 | 2.16s |

