# ChatGPT 重试按钮自动点击器

这是一个面向 Windows 的小工具，用来检测 ChatGPT 桌面窗口中的“重试”按钮，并每隔一段时间自动点击。项目默认使用 UI Automation 直接调用按钮，截图模板只作为 UI Automation 不可用时的兜底方案。

## 功能

- 每 10 秒扫描一次 ChatGPT 窗口，启动后立即扫描。
- 优先通过 Windows UI Automation 调用名称严格匹配的“重试”按钮，避免把 `retry_clicker.py` 等普通文字误认为按钮。
- UI Automation 暂时失效时，使用横幅截图匹配：左侧区域相似度至少 95%，右侧按钮区域相似度至少 80%。两个区域必须在同一位置同时匹配。
- 支持带倒计时的按钮，例如“255 秒后重试”，并额外检查按钮的蓝色外观。
- 优先使用后台窗口消息点击，不抢占鼠标；目标窗口不接受后台消息时才短暂移动鼠标并恢复原位置。
- 窗口被其他最大化窗口完全遮挡时，优先尝试 UI Automation；无法确认按钮时暂停截图，避免把前景窗口画面误当成 ChatGPT。
- 窗口最小化时暂停识别，恢复后自动继续。
- 全局单实例保护，重复启动会自动退出。
- 控制台状态会合并连续重复消息，不写入日志文件。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10 及以上
- 正在运行的 ChatGPT Windows 桌面客户端

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 运行

直接运行：

```powershell
python retry_clicker.py
```

也可以双击 `启动重试工具.bat`。按 `Ctrl+C` 停止程序。

脚本和两张模板图片必须放在同一目录。模板图片来自当前 ChatGPT 界面样式；如果界面外观、缩放比例或语言发生较大变化，需要重新制作模板。

## 识别与点击流程

1. 查找可见的 ChatGPT 窗口，并优先选择 ChatGPT 桌面进程。
2. 遍历 UI Automation 控件树，只接受可见、启用、有有效矩形且名称严格为“重试”“重试按钮”“Retry”或“Retry Button”的按钮。
3. UI Automation 找不到可调用按钮时，抓取窗口自身内容并执行模板匹配。
4. 如果窗口内容抓取失败，才退回屏幕区域截图；完全被其他最大化窗口遮挡时不会使用屏幕截图。
5. 点击成功后恢复用户之前的前台窗口。

UI Automation 节点可能在页面刷新时瞬间失效。此时程序会忽略失效节点并继续普通识别，不会把它记录为成功点击。

## 项目文件

- `retry_clicker.py`：主程序
- `retry_template.png`：普通重试横幅模板
- `retry_template_timed.png`：带倒计时横幅模板
- `启动重试工具.bat`：Windows 启动脚本
- `requirements.txt`：Python 依赖
- `tests/`：不依赖实际 ChatGPT 窗口的识别逻辑测试

## 注意事项

程序会自动点击 ChatGPT 窗口中的重试按钮，请只在你明确需要自动重试时运行。模板匹配属于视觉兜底机制，显示缩放、主题或界面版本变化可能降低识别效果；遇到界面变化时，应先提高阈值或更新模板图片。

项目采用 MIT License。
