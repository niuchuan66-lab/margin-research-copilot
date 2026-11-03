# 测试 PDF 目录

把组委会提供的测试 PDF 放在这里（该目录下的 `*.pdf` 已被 `.gitignore` 排除，不会进入公开仓库）：

- `1706.03762v1.pdf` — 标准双栏论文
- `1706.03762v7.pdf` — 同一论文的新版本，用于去重/版本对比
- `1706.03762v1_img.pdf` — 扫描件，用于 OCR
- `UnderstandingDeepLearning_02_09_26_C.pdf` — 541 页长文档

离线验证解析：

```bash
cd backend
python -m app.workers.parse_cli ../pdf/1706.03762v1.pdf --blocks 5
```

> 不要把测试 PDF 提交到公开仓库；它们只用于本地与评审环境验证。
