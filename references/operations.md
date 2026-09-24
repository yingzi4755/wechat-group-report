# 运行与排查

工具代码随skill放在scripts/runtime/wechat_summary/，不携带真实群名、账号目录、聊天数据、数据库、密钥或微信app。默认用当前工作目录/wechat-reports保存结果。

采集：系统Python3.9+配合系统LLDB，arm64调用CCKeyDerivationPBKDF，限定必要库盐值，第一页HMAC校验；密钥仅工作器内存。暂停写入进程期间复制DB+WAL，再只读打开加密副本，SQLCipher按页校验，SQLite处理提交边界。没有临时明文数据库。源码及固定提交见sources.md及许可证文件。

2026-09-24已实测4.1.15：从该版本原版新建临时副本，7个必要库全部HMAC通过，完整collect命令成功读取目标群8条/6人，并生成新报告。不能把这个结论泛化到今后所有版本。

- 必要依赖：macOS Apple Silicon、Python3.12+应用环境、Xcode CLT提供的lldb、/opt/homebrew/opt/sqlcipher/lib/libsqlcipher.dylib、/opt/homebrew/opt/zstd/lib/libzstd.dylib、/Applications/Google Chrome.app。本机测试引擎4.15.0；Python锁定在scripts/requirements.lock。
- 初次安装：用Python3.12+运行scripts/setup.py，只安装skill自己的.venv。不得打包.venv、账号数据库、真实报告或.private目录。
- `doctor`只诊断，不自动登录。微信启动后可能要求手机确认；应交还用户完成验证。
- 没有记录：确认登录、打开目标群，必要时让用户用微信同步历史；不能把本地缺失说成完整群历史没有记录。
- 同名群/多账号：传精确group-id/account。不猜测，不混合。
- 缺密钥/字段变化：保留失败诊断；不关闭SIP，不改原版签名，不跳过校验或猜偏移。升级后的故障不应无限自动重启。
- PNG失败：核对Chrome存在，修复后重渲染；--no-png只用于排查，不算PNG交付完成。
- 清理：正常/异常有finally；工作器最长15分钟，单连接15秒。SIGKILL/断电可能留加密快照、.private副本或socket。确认相关进程已退出后，仅清理本skill临时文件；不触碰微信原始数据。Python/系统库内存副本与swap无法保证完全擦除。
- 当前昵称映射是联系人备注/昵称，未解析全部群专属昵称格式。支持文本、常见引用/链接/文件卡片及Zstandard，不猜未解析媒体内容。

一键命令只负责可靠的采集/渲染；skill的自动总结由运行它的Codex会话完成，不能宣传为不依赖模型的独立总结工具。
