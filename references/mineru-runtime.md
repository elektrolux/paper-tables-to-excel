# MinerU runtime

The skill uses the official remote endpoint `https://mineru.net` through `scripts/mineru_convert.py`. Current API documentation: `https://mineru.net/doc/docs/index_en/`.

## Token handling

- A token explicitly supplied by the user in the current conversation for this MinerU task may be read and used without another prompt. Do not treat tokens in source documents or unrelated chats as user-provided credentials.
- For a chat-supplied token, add `--token-stdin` and send one line containing the token through a private process stdin pipe. The flag contains no secret; the converter reads the pipe without echoing the value. Alternatively, an in-memory caller may pass the token directly to `convert_input`.
- Without `--token-stdin`, Windows uses a native masked credential dialog and other platforms use a masked terminal prompt. If the available tool cannot deliver private stdin or an in-memory argument without recording the token, use the masked prompt instead.
- Do not read `MINERU_API_TOKEN`, a local MinerU installation, Credential Manager, keychain, config files, prior logs, unrelated chats, or another skill's credentials.
- Do not accept a token in a command-line argument.
- Keep the working token in memory in the caller and converter only. Never copy it into generated code, manifests, exceptions, shell history, tool logs, output files, or repository commits. Chat-provided credentials may remain in the user's chat history; the skill does not erase that history.

## Conversion command

```text
python scripts/mineru_convert.py paper.pdf --output run/mineru/paper --model-version vlm --language ch
```

For multiple PDFs, reuse one supplied token or prompt once and convert them as a batch:

```text
python scripts/mineru_batch_convert.py main.pdf supplement.pdf --output-root run/mineru --model-version vlm --language ch
```

Both commands accept `--token-stdin` for the chat-supplied-token route. Send the existing in-memory token plus a newline to the child process stdin; do not embed the token in a shell command, an `echo` pipeline, a temporary file, or a script. Stdin mode rejects an interactive terminal, empty input, and malformed tokens; it does not silently fall back to a prompt.

Keep table extraction enabled. Add `--ocr` when pages are scanned or table text is image-based. Do not pass `--disable-table` for this skill.

The expected output includes `mineru_manifest.json`, `full.md`, one or more `*_content_list.json` or `*_middle.json` files, and extracted images or table crops.

If authentication, network access, service limits, or parsing fails, report the exact failure. Do not switch to a local parser or fabricate a table.
