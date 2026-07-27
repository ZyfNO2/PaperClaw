# Academic Model Manifest

## Visual baseline

- model: `vidore/colqwen2-base`
- revision: `9fe8a713422a7cb4ef79ca77a09b381ee2243101`
- shard 1: 4,982,048,792 bytes; SHA-256 `5afb3798d74668030808362aa4a4870cf71a0cfd1780287c9c55e40fb24e51d4`
- shard 2: 3,854,759,672 bytes; SHA-256 `3da90e07b7b0c19944ee2cdcf537fa62ba5b01a9170b193d6b68353e9b033ec3`
- runtime adapter: `colpali-engine==0.3.10`
- compatibility: `transformers==4.51.3`; `peft>=0.14,<0.16`; `torch>=2.5,<2.7`
- preferred dtype/device: CUDA bfloat16
- fallback: CPU float32 after CUDA OOM

模型文件位于 Hugging Face cache，不属于 Git artifact。

## Live smoke

- platform: NVIDIA CUDA, bfloat16
- synthetic page: 768 × 1024
- elapsed: 12.857 seconds including model load
- document tokens: 779
- query tokens: 18
- late-interaction score: 0.6483108577
- result: complete; no missing/unexpected checkpoint keys

`colpali-engine==0.3.17` 与 Transformers 5.9 会把 base checkpoint 的 legacy
Qwen2-VL keys 误判为 missing/unexpected，因此没有采用该组合。
