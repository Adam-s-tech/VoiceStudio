<div align="center">
  <img src="docs/logo.png" alt="VoiceStudio" width="88" />
  <h1>VoiceStudio</h1>
  <p><strong>开源声音克隆与工作流引擎。在本地构建。</strong></p>
  <p>使用本地 AI 克隆声音、翻译配音、语音听写和制作有声书。</p>
  <p>
    <a href="https://github.com/debpalash/VoiceStudio/releases/latest">下载</a> ·
    <a href="#开始使用">开始使用</a> ·
    <a href="#文档">文档</a> ·
    <a href="https://discord.gg/bzQavDfVV9">Discord</a> ·
    <a href="README.md">English</a> ·
    <a href="README_JA.md">日本語</a>
  </p>
</div>

![Electron 应用演示：声音克隆、声音设计、视频配音和模型管理](docs/media/electron/voicestudio.gif)

<p align="center"><sub>新 Electron 桌面界面，使用此分支及内置演示声音录制。正式发布版本的界面可能有所不同。</sub></p>

## 用 VoiceStudio 创作

- **声音克隆与设计**：上传参考录音，或用文字描述你想要的声音。
- **视频配音**：转录、翻译、分配说话人，并编辑语音时间轴。
- **语音听写**：通过悬浮录音组件录制、转录和复制文字。
- **长篇创作**：制作多角色脚本、有声书和批量任务。
- **模型管理**：选择语音合成与转录引擎、语言及计算设备。

本地工作流在你的硬件上运行。远程服务为可选功能；使用情况分析须经同意才会启用。

<table>
  <tr>
    <td><img src="docs/media/electron/voice-cloning.png" alt="Electron 声音克隆工作区与内置演示声音" width="100%" /></td>
    <td><img src="docs/media/electron/dubbing.png" alt="Electron 视频配音工作区" width="100%" /></td>
  </tr>
  <tr><td align="center">声音克隆</td><td align="center">视频配音</td></tr>
  <tr>
    <td><img src="docs/media/electron/voice-design.png" alt="Electron 声音设计工作区" width="100%" /></td>
    <td><img src="docs/media/electron/models.png" alt="本地语音模型管理" width="100%" /></td>
  </tr>
  <tr><td align="center">声音设计</td><td align="center">本地模型</td></tr>
</table>

## 开始使用

从 [Releases](https://github.com/debpalash/VoiceStudio/releases/latest) 下载，然后阅读对应平台的安装指南：

**[macOS](docs/install/macos.md) · [Windows](docs/install/windows.md) · [Linux](docs/install/linux.md) · [Docker](docs/install/docker.md)**

打开声音克隆页面，选择已有声音或添加清晰的参考录音，输入文字并生成。按提示安装所需模型。硬件要求因引擎而异，详见[性能指南](docs/performance.md)。

**从源码运行 Electron 预览版：**

```bash
git clone https://github.com/debpalash/VoiceStudio.git
cd VoiceStudio
bun install
cd electron
bun run dev
```

环境要求和后端配置见 [Electron 开发指南](electron/README.md)。项目仍在积极开发中，可通过 [GitHub Issues](https://github.com/debpalash/VoiceStudio/issues) 反馈问题。

## 文档

| 需求 | 链接 |
|---|---|
| 安装帮助 | [故障排查](docs/install/troubleshooting.md) · [模型下载](docs/downloading-models.md) |
| 模型与音质 | [引擎指南](docs/engines/README.md) · [基准测试](docs/benchmarks.md) |
| 集成 | [本地 API](docs/speech-platform.md) · [MCP](docs/mcp.md) · [示例](examples/README.md) |
| 参与开发 | [贡献指南](.github/CONTRIBUTING.md) · [Electron](electron/README.md) · [更新日志](CHANGELOG.md) |

安装智能体技能：`npx skills add debpalash/VoiceStudio`

## 支持 VoiceStudio

[Ko-fi](https://ko-fi.com/debpalash) · [PayPal](https://paypal.me/palashCoder) · [赞助项目](SPONSORS.md) · [商务合作](mailto:partner@voicestudio.sh)

**让语音应用开发者看到你的品牌。** 了解应用底部栏、集成目录、文档和 README 的付费展示合作。[申请合作](https://forms.gle/2PYCvd39hbwijzX37)或[发送邮件](mailto:partner@voicestudio.sh)。

## 许可与负责任使用

应用采用 [AGPL-3.0](LICENSE) 许可。模型遵循各自的许可，商用前请确认其条款。克隆声音前须取得本人许可。详见[许可说明](LICENSE-NOTICE.md)。
