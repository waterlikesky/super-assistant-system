# file_export：一层 `.eml` 目录

M1 只支持这一种输入。不登录邮箱，不读微信、钉钉或短信，不发信。

## 已支持

- 你自己从邮件客户端导出的 `.eml`
- 只读指定目录的这一层；不进入子目录，不读点开头的隐藏文件
- 符号链接不跟随，超过 25 MiB 的文件跳过，都会打印 skipped
- 有 Message-ID 时 id 为 `email:<Message-ID>`；没有时按原信内容哈希，改文件名不变 id
- 每封信变成一条 `ChannelEvent`：`channel=email`，`metadata.ingest_via=file_export`
- 优先 `text/plain`；没有纯文本时去掉 HTML 标签
- 单独一行 `-- `（短横、短横、空格）之后的签名会丢掉；没有这行就保留正文
- 附件只记录文件名和字节数，正文里不放附件内容
- 手机号变成 `[PHONE]`；邮箱本地部分打码；含「验证码」的正文整段替换，不原样落盘
- 输出写到本地 JSONL，并且每次覆盖 `--out`。`data/processed/` 已在 `.gitignore`

无时区的 `Date` 按 UTC 记录。缺少 `Date`、日期无法解析、或正文为空的文件会被跳过。

## 命令

```bash
python -m ingest.file_export_run \
  --input fixtures/sample_exports/mail \
  --out data/processed/events.jsonl \
  --consent-tag fixture-m1
```

换成你自己的目录时，`--consent-tag` 写这批导出的同意标记，例如 `export-2026-10-07`。缺这个参数不会写文件。

夹具里有两封能写入的信，和一封坏日期的信。坏文件打印 `skipped bad-date.eml: 无法解析 Date`，其余仍写入。目录不存在、里面没有 `.eml`、或一封都写不出来时，退出码非 0，并且不会留下空的结果文件。

## 怎样导出

在邮件客户端里把单封信「另存为 .eml」，放进同一个文件夹。Apple Mail、Thunderbird 都可以。不要把整箱 mbox 或 csv 丢进来，当前解析器不读那些格式。

## 数据留在哪

结果只在你传入的 `--out`。`raw_ref` 是本机路径，程序不复制原信，也不上传。删掉这个 JSONL 就删掉这次摄入结果。原信还在你的导出目录里，需要的话自行删除。

## 还没做

邮件 OAuth、mbox、csv、微信、钉钉、短信、自动回复。微信本机解密仍然默认关闭：它绑客户端版本，也有条款和风控问题，见 `docs/problems/channel-ingestion-pitfalls.md`。
