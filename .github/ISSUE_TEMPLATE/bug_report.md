name: 🐛 Bug 报告
description: 报告一个问题
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        感谢反馈！请先搜索已有 issue 避免重复。
        **注意：截图/日志里请先抹掉 API key。**
  - type: input
    id: version
    attributes:
      label: 版本
      description: exe 方式填 Release tag（如 v1.0.0）；源码方式填 commit
    validations:
      required: true
  - type: dropdown
    id: mode
    attributes:
      label: 运行方式
      options:
        - exe（Release 下载）
        - Python 源码
    validations:
      required: true
  - type: input
    id: env
    attributes:
      label: 环境
      description: Windows 版本 / Python 版本（源码方式）
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: 问题描述
      description: 发生了什么？预期是什么？
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: 复现步骤
      placeholder: |
        1. 来源选「系统声音」
        2. 点开始同传
        3. ...
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: 控制台错误信息（如有）
      render: text
