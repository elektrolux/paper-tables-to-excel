# MinerU runtime

The skill uses the official remote endpoint `https://mineru.net` through `scripts/mineru_convert.py`. Current API documentation: `https://mineru.net/doc/docs/index_en/`.

## Token handling

- Prompt the current user for their own MinerU API token on every execution.
- On Windows, the script opens a native masked credential dialog but does not save the value. On other platforms it uses a masked terminal prompt.
- Do not read `MINERU_API_TOKEN`, a local MinerU installation, Credential Manager, keychain, config files, prior logs, chat history, or another skill's credentials.
- Do not accept a token in a command-line argument.
- Keep the token only in the converter process. Never include it in manifests, exceptions, shell history, or output files.

## Conversion command

```text
python scripts/mineru_convert.py paper.pdf --output run/mineru/paper --model-version vlm --language ch
```

For multiple PDFs, prompt once and convert them as a batch:

```text
python scripts/mineru_batch_convert.py main.pdf supplement.pdf --output-root run/mineru --model-version vlm --language ch
```

Keep table extraction enabled. Add `--ocr` when pages are scanned or table text is image-based. Do not pass `--disable-table` for this skill.

The expected output includes `mineru_manifest.json`, `full.md`, one or more `*_content_list.json` or `*_middle.json` files, and extracted images or table crops.

If authentication, network access, service limits, or parsing fails, report the exact failure. Do not switch to a local parser or fabricate a table.
