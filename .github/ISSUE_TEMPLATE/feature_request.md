name: ✨ 功能建议
description: 提议一个新功能或改进
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: 你的使用场景
      description: 这个功能解决什么问题？（先说场景，再说方案）
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: 期望的方案
      description: 你希望它怎么工作？
    validations:
      required: true
  - type: textarea
    id: alt
    attributes:
      label: 考虑过的替代方案
