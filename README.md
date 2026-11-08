# Codex Skill Workspace

本地 Web 技能管理台，区分「收藏库」「用户级启用」「项目级启用」。让专用技能只出现在需要它的项目中。

## 启动

需要 Python 3.11+，无需安装第三方依赖。

```powershell
python server.py
```

打开终端打印的本机地址，默认 http://127.0.0.1:8765 。指定端口：`python server.py --port 8766`。

也可以运行 `python launcher.py`，复用现有服务，或在服务离线时隐藏启动，再用默认浏览器打开控制台。

## Codex 内嵌管理台

0.2.0 起，侧栏入口直接在 Codex 应用页显示完整管理界面，包含技能列表、项目选择、搜索、详情、安装迁移预览及备份恢复。界面使用官方 MCP Apps SDK 握手，所有请求经仅供界面调用的 `console_request` 工具转发到现有本机服务。网页与内嵌界面共享同一份状态和预览令牌。不会自动打开外部浏览器，也不需要 iframe 嵌套或放宽本机 HTTP 服务的跨域设置。官方技能保护规则仍然生效。

安装：

```powershell
python setup_sidebar.py --register
codex plugin add skill-workspace-console@skill-workspace-local
```

命令会生成本项目的独立本地插件与市场，只在用户配置中新增本插件的注册；原配置有备份。客户端详情页可通过 `codex://plugins/skill-workspace-console%40skill-workspace-local` 打开。安装或升级新增 MCP 接口后，在客户端关闭再启用本插件一次，加载新进程和刷新侧栏目录，再重新打开管理台标签页。仅“已安装”不表示旧的运行中插件进程已更新。

开发者修改 `web/index.html`、`web/style.css`、`web/app.js` 或 `integration/sidebar/embedded.js` 后执行：

```powershell
npm ci
npm run build:sidebar
npm run test:sidebar
python setup_sidebar.py
```

已构建的 `integration/sidebar/launcher.html` 是自包含文件，Python 运行时不需要 Node 依赖或外部 CDN。浏览器测试使用官方 AppBridge，在禁用 HTTP 请求的 iframe 中验证完整管理流程；Python 桥接测试使用临时目录，不修改真实技能。独立网页仍可通过 `python server.py` 运行，`python launcher.py` 是可选的外部浏览器打开方式。

公开参考：[MCP Apps UI](https://developers.openai.com/plugins/build/chatgpt-ui)、[本地插件市场](https://developers.openai.com/plugins/build/plugins)。不修改客户端安装文件，不发布到外部目录。

## 第一版能力

- 只扫描后添加的独立技能：`~/.agents/skills`、兼容本机 `~/.codex/skills`。官方内置技能与插件附带技能不纳入管理，不读取其技能内容。
- 自动读取 Codex 侧边栏的本地项目名称、顺序与路径，支持多根目录；也可手动补充项目。扫描项目根目录 `.agents/skills` 与旧版 `.codex/skills`。
- 导入整个技能文件夹到收藏库。收藏不会自动让 Codex 加载技能。
- 将收藏库或已有技能复制安装到用户或指定项目的 `.agents/skills`。
- 用户级技能迁移到项目：先复制到项目，再将原用户级目录移入备份。
- 停用本地独立技能：移动到扫描目录之外的备份区，支持恢复。
- 写入前预览源、目标、影响范围；目标已有内容时拒绝覆盖；执行前重新校验源文件摘要。
- 搜索、按来源筛选、查看完整 SKILL.md、备份恢复。

数据保存在项目 `.local/`，已被 Git 忽略。可通过环境变量 `SKILL_MANAGER_HOME` 指定其他数据目录。收藏库和备份目录应始终位于 Codex 扫描路径之外。

## 自动读取项目

打开页面或点击「刷新扫描」时，只读解析 `~/.codex/.codex-global-state.json` 的 `local-projects` 与 `project-order` 字段，按侧边栏顺序合并手动项目并按路径去重。安装与迁移对话框可直接选择这些项目，无需逐个添加。多根目录项目分别提供目标目录选项；失效或链接路径标为不可用，不创建原项目目录。远程、云端及官方插件目录不作为本机安装目标。

此文件是当前桌面版本的本地兼容数据源，并非稳定的公开接口。若文件缺失或格式不兼容，仍可手动添加项目；格式错误会提示读取失败。自动发现的项目不写回管理器的手动项目清单，侧边栏移除后刷新即可同步移除（主动手动添加的项目仍保留）。整个同步过程不会写入 Codex 状态、配置、数据库或技能目录。

## 作用域说明

用户级技能会对多个项目可见。把用户级技能再复制到项目不会消除其全局可见性；应使用「迁移到项目」，或停用用户级副本后分别在需要的项目安装。

项目视图展示本管理器已发现的用户级与当前项目级独立技能，不是 Codex 进程的实时注入清单。第一版不递归扫描项目所有子目录，也不模拟从嵌套工作目录到仓库根目录的完整发现链。

管理范围按安装位置区分，而不是安装时间：用户自行新增的独立技能（包括使用本系统之前已安装的）可以管理。`.codex/skills/.system`、`.agents/skills/.system` 和 `.codex/plugins` 目录不进入技能列表、不计入数量、不读取技能内容，也不提供导入、安装、停用、迁移或恢复操作。后端同时拦截直接接口请求、旧备份恢复和执行阶段的受保护路径；不会修改官方目录或 Codex 配置。此规则同样适用于项目内相同结构的目录。无法仅凭普通文件夹判断一个手工复制到自定义目录的技能原始作者。

同名技能不会被假定为自动覆盖。页面会提示同名候选，安装不会覆盖已有目录。文件名与 SKILL.md 的名称可能不同。

Codex 通常先载入技能名称、描述与路径，选用后再读取完整 SKILL.md；减少可见候选有助于精简上下文，但不承诺固定的 token 或延迟节省。修改后建议开启新会话；已有会话里的历史内容不会被清除。

官方机制参考：[Build skills](https://learn.chatgpt.com/docs/build-skills)。当前文档推荐 `.agents/skills`；本机同时存在旧版 `.codex/skills`，因此做兼容扫描，实际宿主支持需在使用的 Codex 版本中验证。

## 本地服务边界

仅绑定 127.0.0.1，校验 Host、Origin 和每次启动生成的写入令牌，不提供网络托管功能。不会执行技能脚本。导入与变更拒绝包含符号链接或 Windows junction 的目录，避免通过链接修改其他文件。对其他程序同时修改文件的情形采取尽力检测，操作期间请勿同时编辑目标目录。

管理台运行时不修改 Codex 配置或自动迁移技能；所有技能变更均由界面预览后执行。只有显式运行 `setup_sidebar.py --register` 才会注册侧边栏插件配置。不安装依赖或创建 Git 提交。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试使用临时目录，不修改真实用户技能。

服务启动后，可选运行 `node tests/browser_smoke.mjs`，使用本机默认安装位置的 Edge 无头模式检查搜索、详情、对话框焦点及窄屏布局；截图保存在 `.local/`。测试浏览器使用独立配置，不修改日常浏览器数据。

## 后续范围

- 保持官方内置与插件内容不纳管；后续功能仅针对后添加的独立技能。
- 扫描指定工作目录到 Git 根目录的嵌套技能发现链。
- 支持项目清单导出、技能组合、版本更新与变更记录。
- 对 SKILL.md 增加完整 YAML 校验；目前仅读取常见 frontmatter 子集，文件内容原样保留。
