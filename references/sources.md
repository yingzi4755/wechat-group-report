# 来源与实现审查（2026-09-24）

本项目不运行第三方安装/引导脚本。以下源代码已下载并逐项检查；研究副本在忽略目录 research/，不含用户记录。

| 项目 | 固定提交 | 许可证 | 结论 |
|---|---|---|---|
| [r266-tech/wxkey](https://github.com/r266-tech/wxkey) | 01e96fa58ce3ff061dce83e4c36f62104ebc6b16 | MIT，许可证副本 wxkey-LICENSE.txt | 有 macOS WeChat 4.x 的 LLDB/PBKDF 实现，main.go 中 pbkdfProbePython；有 Apple Silicon 寄存器参数和 page-1 HMAC 验证。上游会保存密钥/管理员凭据，本项目不采用其 bootstrap。 |
| [dylan121322/wxkey-hook](https://github.com/dylan121322/wxkey-hook) | c2d98859c66fffa8dc39580daeb1bb40215a3f9f | MIT，许可证副本 wxkey-hook-LICENSE.txt | 有 macOS 4.1.x CommonCrypto hook 和逐页解密；上游声明 Apple Silicon 实测，Intel 未测。解密程序未校验每一页且不处理 WAL，因此不采用该解密器。 |
| [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) | 5d6d094d8a77c9837d0b7479f79dc6a6c8c677b2 | README 声明 MIT | 当前提交仅有文档/图片，无读取实现，无法据此验证本机兼容性，不采用。 |

数据库引擎：[SQLCipher 官方 API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)，本机 Homebrew 安装4.15.0。使用 sqlite3_key 原始密钥模式、兼容级别4、每页HMAC验证。原始密钥并非口令：只在匹配数据库盐并通过 page-1 HMAC 后使用。

一致性依据：[SQLite WAL 文档](https://www.sqlite.org/wal.html)。数据库写入进程全部线程停住时复制 DB+WAL，私有目录由引擎重建 SHM；查询不设置 immutable（以免忽略 WAL）。由引擎处理 WAL 校验和、提交边界与页面选择，不手工拼接帧。对加密合成数据库已测试提交与未提交的区分。

捕获参数：仅支持 arm64 的 CCKeyDerivationPBKDF 符号，x0=算法2、x1/2=输入地址与长度、x3/4=盐地址与长度、x5=PRF5（SHA512）、x6=轮数。只处理指定账号必要库的16字节盐、256000轮派生路径及2轮HMAC派生路径。密钥必须通过独立HMAC验证。未匹配调用立即跳过，不扫描其他内存，不输出原始参数。

页格式：SQLCipher4的4096字节页，page1前16字节盐，末80字节为IV16+HMAC64；HMAC盐由数据库盐异或0x3a，经2轮PBKDF2-SHA512得到HMAC密钥；page1校验输入为16..4031及小端页号1。其他页的解密与完整性由SQLCipher引擎处理。格式不符时拒绝，不降级绕过校验。

本机版本验证状态见 operations.md；不把上游声称支持等同于本机成功。
