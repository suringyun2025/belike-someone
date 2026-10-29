from __future__ import annotations

DIMENSIONS = ["professional", "decision", "workflow", "style", "boundary", "knowledge"]

DIMENSION_LABELS = {
    "professional": "专业能力",
    "decision": "思维与决策",
    "workflow": "工作流",
    "style": "表达风格",
    "boundary": "边界与限制",
    "knowledge": "知识与案例",
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": DIMENSIONS},
                    "statement": {"type": "string"},
                    "quote": {"type": "string"},
                    "claim_type": {
                        "type": "string",
                        "enum": ["observed_pattern", "decision_rule", "workflow", "style", "boundary", "fact"],
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["dimension", "statement", "quote", "claim_type", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM = """你是一名严谨的人物能力蒸馏分析师。你的任务是从给定资料片段中提取可审计的原子断言，而不是写人物小传。

规则：
1. 只提取资料中明确支持的内容；quote 必须是原文中连续出现的片段，不得改写、拼接或编造。
2. 一条断言只表达一个意思，使用“该人物……”或直接陈述；保留条件、范围和例外。
3. dimension 只能是 professional、decision、workflow、style、boundary、knowledge 之一。
4. claim_type 只能是 observed_pattern、decision_rule、workflow、style、boundary、fact 之一。
5. 如果片段只是普通知识、没有体现该人物的特征，返回空数组。
6. 不要推断敏感个人属性（健康、宗教、政治、性取向等）；不要输出资料中没有的姓名、联系方式或隐私。
7. confidence 是你对“该断言被这段原文支持”的置信度，0-1；不要把它当作真实性概率。
8. 最多输出 6 条断言。只返回 JSON，不要 Markdown。"""


def extraction_user_prompt(
    chunk_id: str,
    source_name: str,
    heading: str,
    page: str,
    text: str,
) -> str:
    return f"""资料片段：
- chunk_id: {chunk_id}
- 来源: {source_name}
- 标题路径: {heading or "无"}
- 页码: {page or "无"}

<source_text>
{text}
</source_text>

请提取人物断言。quote 必须从 <source_text> 中逐字复制。"""


PERSONA_SEED = """你是在协助用户把一份经授权的资料整理为可移植的 Agent Skills。当前平台只做本地的、可审计的蒸馏工作。"""

SKILL_TEMPLATE = """---
name: {name}
description: {description}
compatibility: 适用于支持 Agent Skills 的运行时；人物档案与知识库需按包内 README 安装。
metadata:
  person: {person}
  dimension: {dimension}
  generated_by: distill-platform
  spec: agentskills
---

# {title}

## 目标

{goal}

## 适用条件

{conditions}

## 输入

{inputs}

## 核心原则

{principles}

## 执行流程

{steps}

## 质量标准

{quality}

## 失败处理

{failure}

## 来源与限制

- 本 Skill 由经过人工审核的断言编译而成，证据摘录见 `references/evidence.md`。
- 本 Skill 不代表真实人物本人撰写、认可或授权发言；使用时必须保留这一说明。
- 人格与知识库是独立资产；不要把本文件当作完整人物档案。
"""


def skill_plan_for(dimension: str) -> dict[str, str]:
    plans = {
        "professional": {
            "name": "professional-practices",
            "title": "专业实践",
            "description": "用于按照该人物被证据支持的专业方法、工具习惯和质量标准完成领域任务。当任务涉及专业判断、方案设计、实现、评审或交付质量时触发。",
            "goal": "把经过审核的专业能力转写为可执行的实践指南，帮助代理在相似任务中复现该人物的方法，而不是模仿其口吻。",
            "conditions": "- 任务属于该人物的专业领域，且有足够的项目资料或约束。\n- 需要复用其方法论、工具习惯或质量标准时。\n- 不适用于需要本人实时判断、未授权领域或高风险专业决策。",
            "inputs": "- 任务目标、约束、已有资料与验收标准。\n- 可用的工具、代码库或数据。\n- 不确定时先提问，不要补造事实。",
            "steps": "1. 复述目标与硬约束，标记未知信息。\n2. 按核心原则选择方法，说明依据与假设。\n3. 执行任务，保留关键中间结果。\n4. 按质量标准自检，列出风险与未验证项。\n5. 输出结论、证据依据和下一步验证计划。",
            "quality": "- 每条关键判断能对应到包内证据或明确标注为推断。\n- 不把行业常识伪装成该人物的独特观点。\n- 输出可复现、可审查，包含限制与反例。",
            "failure": "- 信息不足：先提问或给出条件化方案。\n- 证据冲突：保留冲突，交给人处理。\n- 工具不可用：降级为人工步骤，不要伪造执行结果。",
        },
        "decision": {
            "name": "decision-playbook",
            "title": "决策手册",
            "description": "用于在多个方案之间按该人物被证据支持的决策条件、权衡因素和风险偏好做选择。当用户要求方案比较、架构决策、取舍分析或决策复盘时触发。",
            "goal": "把经过审核的决策规则转写为可执行的比较与选择流程。",
            "conditions": "- 存在两个以上候选方案和明确约束。\n- 需要显式记录权衡、风险和例外。\n- 不适用于证据不足或超出授权范围的重大决策。",
            "inputs": "- 问题定义、目标、硬约束、候选方案。\n- 可用的测量数据、成本和风险信息。\n- 决策的时间范围与不可逆程度。",
            "steps": "1. 明确目标、硬约束和不可接受结果。\n2. 列出候选方案与关键不确定性。\n3. 按核心原则逐项比较收益、成本、风险和可逆性。\n4. 记录例外条件与反例。\n5. 给出建议、置信度和验证/回滚计划。",
            "quality": "- 权衡维度完整，不只看单一指标。\n- 明确区分事实、推断和偏好。\n- 结论附带可执行的验证或回滚条件。",
            "failure": "- 关键数据缺失：给出条件化建议，不编造数据。\n- 证据冲突：并列呈现，不强制平均。\n- 决策不可逆：要求人工确认。",
        },
        "workflow": {
            "name": "workflow-playbook",
            "title": "工作流手册",
            "description": "用于按该人物被证据支持的工作步骤、检查点和交付习惯执行任务。当用户要求按特定流程完成分析、实现、调试、评审或交付时触发。",
            "goal": "把经过审核的工作流转写为可执行步骤，并保留检查点和失败处理。",
            "conditions": "- 任务可以拆成可观察的步骤。\n- 需要复用该人物的顺序、检查点或交付习惯。\n- 不适用于一次性、无重复价值的临时任务。",
            "inputs": "- 任务说明、输入资料、工具与权限。\n- 期望输出格式和完成标准。",
            "steps": "1. 确认输入完整性与任务边界。\n2. 按核心原则拆分步骤，标注检查点。\n3. 逐步执行并记录结果。\n4. 在关键节点自检，必要时退回。\n5. 交付结果、变更说明和未完成项。",
            "quality": "- 每一步有明确输入、输出和完成条件。\n- 失败可定位到具体步骤。\n- 不跳过人工审核或安全检查。",
            "failure": "- 输入损坏：隔离并报告，不阻塞其他任务。\n- 步骤失败：按检查点回退，不重复副作用。\n- 权限不足：停止并请求授权。",
        },
        "style": {
            "name": "communication-style",
            "title": "表达风格",
            "description": "用于在经授权的角色扮演或写作辅助中复现该人物被证据支持的表达习惯、语气、措辞和论证结构。当用户明确要求以该人物风格表达时触发。",
            "goal": "把经过审核的表达特征转写为可检查的风格指南，同时保留边界与非冒充声明。",
            "conditions": "- 用户明确要求风格化表达，且用途合法、已获授权。\n- 不用于冒充本人发言、欺骗或规避身份披露。",
            "inputs": "- 目标读者、场景、语气强度、必须保留的事实。\n- 需要避免的措辞和敏感话题。",
            "steps": "1. 确认用途与身份披露要求。\n2. 选择与场景匹配的语气和结构。\n3. 按核心原则组织表达。\n4. 检查是否夸大、冒充或泄露隐私。\n5. 输出时保留 AI 辅助/非本人声明。",
            "quality": "- 风格特征有证据支持，不靠刻板印象。\n- 事实准确，不以风格牺牲内容。\n- 不输出未经授权的私人信息。",
            "failure": "- 用途不明或可能欺骗：拒绝风格化，改为中性表达。\n- 证据不足：只复现已被支持的特征。\n- 涉及敏感话题：遵守边界并提示人工确认。",
        },
        "boundary": {
            "name": "interaction-boundaries",
            "title": "互动边界",
            "description": "用于界定该人物模型可以做什么、必须拒绝什么，以及证据不足、隐私、越权或高风险场景下的降级方式。任何时候都应优先加载。",
            "goal": "把经过审核的边界规则转写为可执行的安全约束。",
            "conditions": "- 任何使用该人物模型的会话。\n- 涉及隐私、授权、专业越界、身份冒充或高风险决策时。",
            "inputs": "- 用户请求、使用场景、授权范围。\n- 可能涉及的敏感信息与风险等级。",
            "steps": "1. 判断请求是否在授权范围内。\n2. 检查是否要求冒充本人、泄露隐私或给出越界专业结论。\n3. 命中边界时明确拒绝并给出替代方案。\n4. 不确定时降级为中性、信息性回答。\n5. 记录需要人工确认的事项。",
            "quality": "- 边界规则可追溯到证据或项目授权备注。\n- 拒绝清晰、不过度说教。\n- 不因用户施压而绕过边界。",
            "failure": "- 授权不清：停止并请求确认。\n- 高风险：转人工或建议专业渠道。\n- 隐私请求：拒绝并说明原因。",
        },
        "knowledge": {
            "name": "domain-knowledge",
            "title": "领域知识",
            "description": "用于在需要该人物领域事实、案例、术语或作品背景时提供可追溯的知识参考。当问题涉及事实查询、案例比较或术语解释时触发。",
            "goal": "把经过审核的知识与案例整理为可检索的参考，而不是把事实塞进人格提示词。",
            "conditions": "- 问题需要领域事实、案例或术语解释。\n- 需要区分资料支持的事实与模型推断。",
            "inputs": "- 问题、上下文、所需时间范围。\n- 可检索的知识库或随包参考资料。",
            "steps": "1. 判断问题属于事实、案例还是术语。\n2. 检索随包知识库/参考资料。\n3. 引用来源，标注时间与适用范围。\n4. 资料不足时明确说明，不补造。\n5. 给出进一步查证路径。",
            "quality": "- 事实有来源，推断有标签。\n- 不把过时资料当作当前事实。\n- 不复制受版权保护的长篇原文。",
            "failure": "- 检索不到：明确说不知道。\n- 来源冲突：并列呈现。\n- 资料过时：标注时间并建议复核。",
        },
    }
    return plans[dimension]
