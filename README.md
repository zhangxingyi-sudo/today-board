# Today Board

A todo list that lives in the [cmux](https://github.com/manaflow-ai/cmux) Dock: always visible on the right while your agents work on the left.

一个常驻在 cmux 右侧 Dock 里的待办清单。左边是你和 Claude Code、Codex 的对话，右边是今天要做的事。

```
┌──────────┬───────────────────────────┬──────────────────────────┐
│ 工作区    │                           │ Today  11月12日 周四      │
│          │  Claude Code              │ 日程 3  要推进 5  待确认 8 │
│ ▸ 周报    │                           ├──────────────────────────┤
│ ▸ 问题归拢 │  > 请帮我处理这件待办…     │ ☐ 准备周四评审稿   处理 ▸ │
│          │                           │ ☐ 回复供应商的邮件 处理 ▸ │
│          │                           │ ☑ 订一间会议室            │
└──────────┴───────────────────────────┴──────────────────────────┘
```

## 它解决什么

用 cmux 同时开好几个 agent 干活的时候，“今天到底还有哪些事”通常散落在某个对话里，或者在另一个应用里。Today Board 把它放回眼前：

- **常驻**：挂在 cmux 的全局 Dock 上，切到哪个工作区都在。
- **待办是主角，对话是工具**：每件事点一下“处理 ▸”，就新开一个以它命名的工作区，agent 已经拿到这件事的背景。一件事一个对话，上下文不串。
- **机器提的事要你点头**：脚本和 agent 加进来的事项先进“待确认”，你点“确认”才算数，点“忽略”就不再打扰，忽略了还能找回。
- **就是一个 Markdown 文件**：清单存在 `todo.md` 里，人能读，脚本能写，agent 能改。

## 功能

- 五个视图：日程、要推进、待确认、已完成、已忽略
- 日程按天分组，同一天时间重叠会标出冲突
- 点开任意一条可以改内容、填时间、写备注、换状态
- 搜索，按日期筛选
- 命令行 `today add`，给定时任务和 agent 往清单里送事项
- 多机同步：几台电脑经一个 git 仓库共用一份清单，每个文件只有一个写入者，不会冲突
- 只监听 `127.0.0.1`，零第三方依赖，Python 3.9+

## 安装

需要 macOS、Python 3.9 以上，以及带 Dock 的 cmux。界面目前只有中文。

```sh
git clone https://github.com/zhangxingyi-sudo/today-board.git
cd today-board
ln -s "$PWD/bin/today" ~/.local/bin/today   # 或任何在 PATH 里的目录

today install    # 注册为后台服务，开机自启
today dock       # 挂到 cmux 的 Dock（先打开 cmux）
```

数据默认放在 `~/.today-board/`。`today install` 会把程序复制一份到这个目录里运行，所以更新代码后要重新执行一次 `today install`。默认端口被占用时会自动换一个并写进配置。卸载服务用 `today uninstall`，数据不会被删除。

## 往清单里送事项

```sh
today add "给客户回邮件"                                   # 进“待确认”
today add "周会" --status todo --time "2026-11-13 10:00-11:00"
today add "核对周五的会议材料" --source daily-summary --note "带上上周的数据"
today list --status pending --json
today set 261113-m01 done
today ingest          # 把 inbox/ 里的 JSON 文件送进清单
today sync            # 同步模式：拉取、合并、推送
```

怎么让定时任务或 agent 每天自动整理出待办，见 [docs/feeding.md](docs/feeding.md)。

## 文件格式

```markdown
- [待确认] 261112-m01 | 准备周四评审的材料 | daily-summary | 2026-11-12
  - 时间：2026-11-13 10:00
  - 备注：先把上周的数据补齐
```

每条一行：`- [状态] 编号 | 内容 | 来源 | 首次出现日期`，下面可以跟缩进的时间和备注。
状态有五种：待确认、进行中、已完成、已推迟、已取消；也接受英文的 pending、todo、done、later、ignored。
编号是“六位日期-来源字母和序号”，`m` 是自动加入的，`b` 是在清单上手动加的，两边各自编号不会撞。

## 配置

`~/.today-board/config.json`：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mode` | `local` | `local` 单机；`sync` 多台电脑经 git 仓库共用一份清单，见 docs/feeding.md |
| `merge_here` | `false` | 同步模式下，只有负责写 `todo.md` 的那一台设为 `true` |
| `todo_file` | `todo.md` | 清单文件，相对路径以数据目录为准 |
| `events_file` | `events.jsonl` | 操作记录，只追加 |
| `applied_file` | `applied.json` | 已合并的操作，由执行合并的机器写 |
| `port` | `8787` | 本机端口 |
| `agent_command` | `claude` | “处理 ▸”启动的命令，可以换成 `codex` 等 |
| `agent_cwd` | `~` | 新对话的工作目录 |
| `status_style` | `zh` | 写文件时用中文还是英文状态 |

## 安全

- 网页只监听 `127.0.0.1`。不要把它暴露到局域网或公网。
- 多机同步用的清单仓库和这个代码仓库是两回事。清单里是待办正文，应单独放在私有 git 仓库，不要提交进本仓库，也不要改成公开。
- “处理 ▸”会在本机执行 `config.json` 里的 `agent_command`。这个值来自你自己的配置，不要设成不可信的命令。

## 状态

早期版本，接口可能变。与 cmux 官方没有关联。

## License

MIT
