# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本仓库是 `page-debug` Skill 的**开发环境**。Skill 本身位于 `.claude/skills/page-debug/`，该目录是发布单元——用户将其复制到自己的 Claude Code 项目中即可使用。

`testcase/` 是本地的开发测试用例，不随 Skill 发布。

## 角色定位

你是 一个skill 开发专家，专门用来开发skill，你能够很好地理解项目中那些正在开发的skill，掌握它们的各种功能，对它们进行修改和完善，让skill达到用户期望的效果

## 项目结构

```
├── .claude/
│   ├── settings.json                  # Skill 注册（本地开发用）
│   └── skills/page-debug/             # ★ 发布单元
│       ├── SKILL.md                   # Skill 定义（Agent 行为指令）
│       ├── README.md                  # 用户安装文档
│       ├── requirements.txt            # Python 依赖
│       ├── .gitignore                 # Skill 级忽略规则
│       ├── scripts/
│       │   └── debug_breakpoint.py    # 断点注入器 + CDP 桥接引擎
│       ├── references/
│       │   ├── failure-taxonomy.md     # 测试失败分类与诊断方法
│       │   └── layered-debugging.md    # 分层架构项目穿透追踪
│       └── docs/
│           ├── design.md              # 架构设计与备选方案
│           └── multi-framework.md     # 多语言/多框架适配设计
├── testcase/                          # 开发测试用例（不发布）
├── .gitignore
└── CLAUDE.md
```

## 开发

```bash
# 安装依赖
pip install -r .claude/skills/page-debug/requirements.txt
playwright install chromium

# 运行测试用例（预期失败，包含故意拼错的选择器用于验证调试流程）
python -m pytest testcase/test_basic_single_keyword.py -v

# 启动断点调试
python .claude/skills/page-debug/scripts/debug_breakpoint.py --file testcase/test_basic_single_keyword.py --line 17
```

## 发布

发布 `.claude/skills/page-debug/` 目录。用户安装方式见该目录下的 README.md。
