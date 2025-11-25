import { z } from "zod";

export const hardCaps = {
  chunkMaxOutputTokens: 4000,
  agentReportTokens: 12000,
  agentTestimonyTokens: 8000,
  judgeTokens: 12000,
  litReviewMaxOutputTokens: 8000,
  claimEvalMaxOutputTokens: 5000
};

export const jobConfigSchema = z.object({
  pdf_dir: z.string().min(1, "PDF directory is required."),
  research_focus: z.string().min(6, "Add a short research focus."),
  chunk_words: z.number().int().min(300).max(6000).default(1500),
  chunk_overlap: z.number().int().min(0).max(1000).default(150),
  chunk_model: z.string().default("gpt-5.1"),
  chunk_reasoning: z.enum(["low", "medium", "high"]).default("medium"),
  chunk_max_output_tokens: z.number().int().min(200).max(hardCaps.chunkMaxOutputTokens).default(1200),

  agent_model: z.string().default("gpt-5.1"),
  agent_report_reasoning: z.enum(["low", "medium", "high"]).default("high"),
  agent_report_tokens: z.number().int().min(1000).max(hardCaps.agentReportTokens).default(6000),
  agent_testimony_tokens: z.number().int().min(500).max(hardCaps.agentTestimonyTokens).default(5000),

  judge_model: z.string().default("gpt-5.1"),
  judge_reasoning: z.enum(["low", "medium", "high"]).default("high"),
  judge_tokens: z.number().int().min(2000).max(hardCaps.judgeTokens).default(7000),

  lit_review_model: z.string().default("gpt-5.1"),
  lit_review_reasoning: z.enum(["low", "medium", "high"]).default("high"),
  lit_review_text_verbosity: z.enum(["low", "medium", "high"]).default("high"),
  lit_review_max_output_tokens: z.number().int().min(500).max(hardCaps.litReviewMaxOutputTokens).default(4000),

  claim_eval_model: z.string().default("gpt-5.1"),
  claim_eval_reasoning: z.enum(["low", "medium", "high"]).default("medium"),
  claim_eval_max_output_tokens: z.number().int().min(500).max(hardCaps.claimEvalMaxOutputTokens).default(3000),

  allow_pdf_ocr: z.boolean().default(true),
  allow_openai_vision: z.boolean().default(false),
  vision_model: z.string().optional(),
  vision_max_output_tokens: z.number().int().min(100).max(5000).default(900),
  use_llm_section_detection: z.boolean().default(false),
  section_detection_model: z.string().optional(),

  capture_media: z.boolean().default(false),
  describe_media: z.boolean().default(false),
  media_output_dir: z.string().optional(),
  media_max_pages: z.number().int().min(1).max(10).default(5),
  media_zoom: z.number().min(1).max(3).default(2.0),

  enable_judge: z.boolean().default(true),
  enable_claim_eval: z.boolean().default(true),
  output_dir: z.string().optional()
});

export type JobConfig = z.infer<typeof jobConfigSchema>;

export const defaultJobConfig: JobConfig = {
  pdf_dir: "~/Documents/papers",
  research_focus: "Map methodological rigor, normative stakes, and doctrinal contributions.",
  chunk_words: 1500,
  chunk_overlap: 150,
  chunk_model: "gpt-5.1",
  chunk_reasoning: "medium",
  chunk_max_output_tokens: 1200,
  agent_model: "gpt-5.1",
  agent_report_reasoning: "high",
  agent_report_tokens: 6000,
  agent_testimony_tokens: 5000,
  judge_model: "gpt-5.1",
  judge_reasoning: "high",
  judge_tokens: 7000,
  lit_review_model: "gpt-5.1",
  lit_review_reasoning: "high",
  lit_review_text_verbosity: "high",
  lit_review_max_output_tokens: 4000,
  claim_eval_model: "gpt-5.1",
  claim_eval_reasoning: "medium",
  claim_eval_max_output_tokens: 3000,
  allow_pdf_ocr: true,
  allow_openai_vision: false,
  vision_model: "gpt-5-mini",
  vision_max_output_tokens: 900,
  use_llm_section_detection: false,
  section_detection_model: "gpt-5.1",
  capture_media: false,
  describe_media: false,
  media_output_dir: "media_assets",
  media_max_pages: 5,
  media_zoom: 2.0,
  enable_judge: true,
  enable_claim_eval: true,
  output_dir: "litrev_outputs"
};

export const presets = [
  {
    id: "fast",
    name: "Fast skim",
    description: "Smaller chunks, lower output tokens, judge + claim eval on.",
    config: {
      ...defaultJobConfig,
      chunk_words: 900,
      chunk_overlap: 80,
      chunk_max_output_tokens: 800,
      agent_report_tokens: 3500,
      agent_testimony_tokens: 2000,
      lit_review_max_output_tokens: 2500
    }
  },
  {
    id: "balanced",
    name: "Balanced",
    description: "Current defaults with judge and claim eval enabled.",
    config: defaultJobConfig
  },
  {
    id: "deep",
    name: "Exhaustive",
    description: "Larger outputs, judge + claim eval, OCR and media on.",
    config: {
      ...defaultJobConfig,
      chunk_words: 1800,
      chunk_overlap: 180,
      chunk_max_output_tokens: 2000,
      agent_report_tokens: 8000,
      agent_testimony_tokens: 5000,
      judge_tokens: 9000,
      lit_review_max_output_tokens: 6000,
      claim_eval_max_output_tokens: 4000,
      allow_pdf_ocr: true,
      allow_openai_vision: true,
      capture_media: true,
      describe_media: true
    }
  }
];
