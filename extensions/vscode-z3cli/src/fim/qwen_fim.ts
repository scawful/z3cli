/**
 * FIM prompt template per model family.
 * Qwen2.5/Qwen3-Coder/Qwen3.5 Instruct all share the same special-token form,
 * but different stop tokens and repo separators.
 */

export interface FimTemplate {
  prefixTok: string;
  suffixTok: string;
  middleTok: string;
  defaultStops: string[];
}

const QWEN_DEFAULT: FimTemplate = {
  prefixTok: "<|fim_prefix|>",
  suffixTok: "<|fim_suffix|>",
  middleTok: "<|fim_middle|>",
  defaultStops: ["<|endoftext|>", "<|fim_pad|>", "<|file_separator|>", "<|repo_name|>"],
};

const QWEN_CODER: FimTemplate = {
  ...QWEN_DEFAULT,
  defaultStops: ["<|endoftext|>", "<|fim_pad|>", "<|file_separator|>"],
};

const STARCODER: FimTemplate = {
  prefixTok: "<fim_prefix>",
  suffixTok: "<fim_suffix>",
  middleTok: "<fim_middle>",
  defaultStops: ["<file_sep>", "<|endoftext|>"],
};

const TEMPLATES: Record<string, FimTemplate> = {
  default: QWEN_DEFAULT,
  qwen: QWEN_DEFAULT,
  qwen3: QWEN_DEFAULT,
  qwen35: QWEN_DEFAULT,
  qwencoder: QWEN_CODER,
  starcoder: STARCODER,
};

const MODEL_TEMPLATE_MAP: Array<[RegExp, string]> = [
  [/navi|farore|nayru|qwen3?\.5/i, "qwen35"],
  [/qwen3?-coder|oracle-coder/i, "qwencoder"],
  [/oracle/i, "qwen"],
  [/starcoder|deepseek-coder/i, "starcoder"],
];

export function pickTemplate(model: string): FimTemplate {
  for (const [re, key] of MODEL_TEMPLATE_MAP) {
    if (re.test(model)) return TEMPLATES[key] ?? TEMPLATES.default;
  }
  return TEMPLATES.default;
}

export function buildFimPrompt(prefix: string, suffix: string, model: string): string {
  const tpl = pickTemplate(model);
  return `${tpl.prefixTok}${prefix}${tpl.suffixTok}${suffix}${tpl.middleTok}`;
}

export function fimStopTokens(model: string, extra: string[]): string[] {
  const tpl = pickTemplate(model);
  return Array.from(new Set([...tpl.defaultStops, ...extra]));
}
