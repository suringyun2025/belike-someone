export const stageLabels: Record<string, string> = {
  s01_intake: "项目校验",
  s02_ingest: "资料接入",
  s03_parse: "解析与脱敏",
  s04_normalize: "规范化",
  s05_chunk: "分块与索引",
  s06_corpus_map: "资料地图",
  s07_extract: "断言提取",
  s08_ground: "证据定位",
  s09_conflicts: "冲突检测",
  s10_consolidate: "归纳与待审",
  s11_compose: "能力编排",
  s12_compile: "编译 Skills",
  s13_validate: "静态校验",
  s14_eval: "行为评测",
  s15_package: "打包导出",
};

export const protocolLabels: Record<string, string> = {
  openai_responses: "OpenAI Responses",
  openai_chat: "OpenAI Chat Completions（兼容）",
  anthropic: "Anthropic Messages",
  gemini: "Google Gemini generateContent",
};

export const sourceTypeLabels: Record<string, string> = {
  document: "文档",
  chat: "聊天记录",
  code: "代码",
  image: "图片",
  media: "音视频",
};

export const evidenceGradeLabels: Record<string, string> = {
  direct_quote: "直接引用",
  repeated_pattern: "重复模式",
  validated_workflow: "已验证流程",
  model_inference: "模型推断",
  human_verified: "人工确认",
  contradicted: "存在冲突",
  rejected: "已驳回",
};

export const claimTypeLabels: Record<string, string> = {
  observed_pattern: "行为模式",
  decision_rule: "决策规则",
  workflow: "工作流",
  style: "表达风格",
  boundary: "边界",
  fact: "事实",
};
