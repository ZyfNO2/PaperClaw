# 测试报告

- 日期：2026-07-13
- Python：3.13.5
- 平台：Windows 11 / PowerShell
- 命令：`python -m pytest -q --basetemp=tmp/pytest`
- 结果：27 passed，1 skipped，0 failed
- 覆盖：工具正向/失败路径、路径逃逸、symlink 逃逸、命令失败/超时、非法 JSON、未知 action、6 类离线 Agent Loop 与最大步数。
- 静态检查：`ruff` 未安装，未擅自安装依赖。
- 真实模型 smoke：2026-07-13 使用仓库根目录 `.env`（`https://opencode.ai/zen/go/v1` + `deepseek-v4-flash`）执行通过；真实 trace 保存在 `artifacts/v0_01/real_smoke_trace.json`。
- 真实模型兼容修复：OpenCode Go 网关在当前环境下对无 `User-Agent` 的 `urllib` 请求返回 `403` / `error code: 1010`；适配器补充 `User-Agent` 和 `Accept` 后恢复正常。
- 真实模型行为观察：模型在第一次参数名写错、第二次 `file_write` 覆盖冲突后，第三步改走 `bash` 覆写文件并完成验证，说明当前 v0.01 仍缺少真正的执行层 Permission Engine。
- 观测性调整：CLI 已支持 `--verbose-events`，在测试/调试时输出每轮 `thinking / tool / result / done`；默认普通运行仅输出最终 JSON，避免日常命令行噪声过高。
- 独立 Review：初审为 REVISE；已修复进程树超时、verification 误判、repair prompt 断言和 symlink 静默通过。任意 Shell 命令无法仅靠 denylist 保证工作区隔离，保留为已知阻塞。
