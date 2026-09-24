# 微信群聊天总结 · Codex Skill

读取本人电脑微信中指定群聊的本地已同步记录，由当前 Codex 会话完整阅读并生成中文总结、离线 HTML 和 PNG 长图。无需额外提供模型 API Key。

**目前仅在 Apple Silicon Mac 上实测，微信版本 4.1.13 / 4.1.15。** Windows、Intel Mac 及其他微信版本未验证。不是腾讯官方工具。

## 能做什么

- 按完整群名和稳定群 ID 精确匹配；多个账号不混合，同名群需消歧。
- 默认最近 24 小时，也支持 48 / 72 小时和指定起止时间；固定截止时间，范围左闭右开。
- 提取文本、发送人、时间、引用及可解析的链接和文件卡片；未解析媒体仅标注类型。
- 总结概览、话题、待办、已确认事项和未解决问题；重要结论关联消息 ID。
- 输出 `messages.json`、`messages.txt`、`report.json`、`summary.md`、`index.html`、`report.png`。
- HTML 无远程字体或 CDN，可离线查看来源。超长 PNG 自动编号分图，不静默截断。

## 安装

需要 Python 3.12+、Homebrew 的 SQLCipher 与 zstd、Xcode Command Line Tools 提供的 LLDB，以及安装在标准位置的 Google Chrome。

```sh
git clone https://github.com/yingzi4755/wechat-group-report.git ~/.codex/skills/wechat-group-report
brew install sqlcipher zstd
python3.12 ~/.codex/skills/wechat-group-report/scripts/setup.py
```

如果安装目录已存在，请先备份或更新现有版本，不要覆盖运行中的采集会话。缺少 Command Line Tools 时执行 `xcode-select --install` 并完成系统安装。

## 在 Codex 中使用

安装后在 Codex 中调用：

> 使用 $wechat-group-report，总结“你的完整群名”最近 24 小时的聊天，生成 PNG 和网页版报告。

首次采集需要你授权短暂重启微信：工具复制微信到私有临时目录，仅重签副本以调试捕获必要密钥，结束后恢复原版；不关闭 SIP，不修改原版签名。必要时需要手机确认登录。不要在未授权的机器或账号上运行。

Codex 会读完所有导出批次、生成带来源引用的 `report.json`，再渲染与检查报告。**命令行采集器本身不提供独立 AI 总结，完整语义总结依赖当前 Codex 会话。**

## 命令行步骤

在用于保存报告的工作目录中执行：

```sh
SKILL_DIR="$HOME/.codex/skills/wechat-group-report"
PY="$SKILL_DIR/.venv/bin/python"
"$PY" "$SKILL_DIR/scripts/run.py" doctor
# 仅在本人已同意临时重启微信后执行：
"$PY" "$SKILL_DIR/scripts/run.py" collect --group '你的完整群名' --hours 24 --allow-restart
```

导出目录位于当前工作目录的 `wechat-reports/` 下。指定时间可用 `--start '2026-09-23T08:00:00+08:00' --end '2026-09-24T08:00:00+08:00'` 替代 `--hours`。同名群和多账号分别使用 `--group-id`、`--account`，值应依据实际检测结果。

让 Codex 按 [总结结构](references/report-schema.md) 阅读全部消息并生成 `report.json`，然后：

```sh
"$PY" "$SKILL_DIR/scripts/run.py" render '本次输出目录'
"$PY" "$SKILL_DIR/scripts/run.py" validate '本次输出目录'
```

## 数据与限制

- 本地已同步记录不等于完整群历史。同步不足会写入报告，不会默默扩大时间范围。
- 原始数据库只读；暂停写入期间取得独立 DB+WAL 快照，使用 SQLCipher 校验页面和 SQLite 处理有效 WAL。
- 数据库密钥只在工作器内存使用，不写入日志、配置或报告；正常和异常路径清理临时副本。断电或强制终止可能需要手动清理，详见[排查说明](references/operations.md)。
- 引用媒体省略传输参数，仅保留类型；图片、视频和语音未解析时不描述其内容。
- 采集和渲染在本机进行，但当前 Codex 会话会读取导出文本用于总结；这不是完全离线的本地模型方案。请根据所用 Codex 服务的数据设置处理聊天隐私。
- 本仓库仅包含代码、说明和虚构测试，不包含任何真实聊天记录、用户数据库、密钥或微信应用。
- 报告不会自动部署到公网或发送给群成员。分享生成的报告前请自行核对内容和隐私。

## 验证与开发

在具备上述 macOS 依赖的环境中，从仓库根目录执行：

```sh
.venv/bin/python -m pytest -q
```

测试使用虚构消息和临时加密数据库，覆盖时间边界、同名群、分片去重、已提交/未提交 WAL、错误密钥、异常清理、引用转义、PNG 分图和移动端布局。真实采集曾在上述两个微信版本成功完成；虚构测试通过不代表其他客户端版本兼容。

## 许可证与来源

本项目使用 [MIT License](LICENSE)。参考实现固定提交、兼容性审查和算法依据见 [sources.md](references/sources.md)。相关第三方 MIT 版权声明保留在 `references/*LICENSE.txt`；SQLCipher、SQLite、Playwright 等依赖沿用各自许可证。
