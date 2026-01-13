"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { defaultJobConfig, JobConfig, presets } from "@/lib/configSchema";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";

export default function NewJobPage() {
  const [config, setConfig] = useState<JobConfig>(defaultJobConfig);
  const [title, setTitle] = useState("Lit review run");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [presetId, setPresetId] = useState("balanced");
  const supabaseConfigured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

  const update = <K extends keyof JobConfig>(key: K, value: JobConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const applyPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (preset) {
      setConfig({ ...preset.config, mode: config.mode });
      setPresetId(id);
    }
  };

  const setMode = (mode: "lit_review" | "course_review") => {
    setConfig((prev) => ({
      ...prev,
      mode,
      enable_judge: mode === "lit_review" ? prev.enable_judge : false,
      enable_claim_eval: mode === "lit_review" ? prev.enable_claim_eval : false
    }));
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!supabaseConfigured) {
      setMessage("Supabase not configured; run via CLI (e.g., python litrev_test.py <dir> or python course_review.py <dir>).");
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          research_focus: config.research_focus,
          input_uri: config.pdf_dir,
          config
        })
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || "Failed to create job");
      }
      const data = await res.json();
      setMessage(`Job created: ${data.id}`);
    } catch (err: any) {
      setMessage(err?.message || "Failed to submit job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Link href="/" className="text-sm text-foreground/60 hover:text-foreground">
        ← Back to dashboard
      </Link>
      <div className="flex flex-col gap-2">
        <div className="text-xs uppercase tracking-[0.2em] text-foreground/60">Submit</div>
        <h1 className="text-2xl font-semibold tracking-tight">New lit review job</h1>
        <p className="text-sm text-foreground/70">Pick a preset, adjust the knobs, and enqueue a run.</p>
        {!supabaseConfigured && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Supabase is not configured; web submissions are disabled. Run the pipeline via CLI instead:
            <div className="mt-1 font-mono text-xs">
              python litrev_test.py /path/to/pdfs
              <br />
              python course_review.py /path/to/course_folder
            </div>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <Card>
          <CardHeader className="flex flex-col gap-3">
            <CardTitle>Mode, preset, and focus</CardTitle>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label>Mode</Label>
                <Select value={config.mode} onChange={(e) => setMode(e.target.value as "lit_review" | "course_review")}>
                  <option value="lit_review">Literature Review</option>
                  <option value="course_review">Course Exam Review</option>
                </Select>
                <div className="text-xs text-foreground/60">Switch to course mode for exam-focused outputs.</div>
              </div>
              <div className="flex flex-col gap-2">
                <Label>Preset</Label>
                <Select value={presetId} onChange={(e) => applyPreset(e.target.value)}>
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <div className="text-xs text-foreground/60">{presets.find((p) => p.id === presetId)?.description}</div>
              </div>
              <div className="md:col-span-1 flex flex-col gap-2">
                <Label>Title</Label>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g., Healthcare rights review" />
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label>PDF directory or storage URI</Label>
              <Input value={config.pdf_dir} onChange={(e) => update("pdf_dir", e.target.value)} />
              <div className="text-xs text-foreground/60">Local path or storage prefix the worker can reach.</div>
            </div>
            <div className="md:col-span-2 flex flex-col gap-2">
              <Label>{config.mode === "course_review" ? "Course focus" : "Research focus"}</Label>
              <Textarea rows={3} value={config.research_focus} onChange={(e) => update("research_focus", e.target.value)} />
            </div>
            {config.mode === "course_review" && (
              <div className="flex flex-col gap-2">
                <Label>Course name</Label>
                <Input value={config.course_name} onChange={(e) => update("course_name", e.target.value)} placeholder="e.g., Public Policy 301" />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Chunking</CardTitle>
            <p className="text-sm text-foreground/70">Words, overlap, and per-chunk token budget.</p>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            <div className="flex flex-col gap-2">
              <Label>Words per chunk</Label>
              <Input type="number" value={config.chunk_words} onChange={(e) => update("chunk_words", Number(e.target.value))} />
              <div className="text-xs text-foreground/60">Smaller chunks → faster, less context.</div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>Overlap</Label>
              <Input type="number" value={config.chunk_overlap} onChange={(e) => update("chunk_overlap", Number(e.target.value))} />
            </div>
            <div className="flex flex-col gap-2">
              <Label>Chunk max tokens</Label>
              <Input
                type="number"
                value={config.chunk_max_output_tokens}
                onChange={(e) => update("chunk_max_output_tokens", Number(e.target.value))}
              />
            </div>
          </CardContent>
        </Card>

        {config.mode === "lit_review" && (
          <Card>
            <CardHeader>
              <CardTitle>Agents & judge</CardTitle>
              <p className="text-sm text-foreground/70">Control narrative depth and structured outputs.</p>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label>Agent report tokens</Label>
                <Input type="number" value={config.agent_report_tokens} onChange={(e) => update("agent_report_tokens", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Agent testimony tokens</Label>
                <Input type="number" value={config.agent_testimony_tokens} onChange={(e) => update("agent_testimony_tokens", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Judge tokens</Label>
                <Input type="number" value={config.judge_tokens} onChange={(e) => update("judge_tokens", Number(e.target.value))} />
              </div>
              <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
                <div>
                  <div className="font-medium text-sm">Enable judge</div>
                  <div className="text-xs text-foreground/60">Run consensus and usage recommendations.</div>
                </div>
                <Switch checked={config.enable_judge} onChange={(e) => update("enable_judge", e.target.checked)} />
              </div>
              <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
                <div>
                  <div className="font-medium text-sm">Enable claim evaluation</div>
                  <div className="text-xs text-foreground/60">Build structured claim analysis JSON.</div>
                </div>
                <Switch checked={config.enable_claim_eval} onChange={(e) => update("enable_claim_eval", e.target.checked)} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Claim eval tokens</Label>
                <Input
                  type="number"
                  value={config.claim_eval_max_output_tokens}
                  onChange={(e) => update("claim_eval_max_output_tokens", Number(e.target.value))}
                />
              </div>
            </CardContent>
          </Card>
        )}

        {config.mode === "course_review" && (
          <Card>
            <CardHeader>
              <CardTitle>Course review outputs</CardTitle>
              <p className="text-sm text-foreground/70">Control summaries, concepts, practice, and cram sheet.</p>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label>Doc summary tokens</Label>
                <Input type="number" value={config.summary_tokens} onChange={(e) => update("summary_tokens", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Concept tokens</Label>
                <Input type="number" value={config.concepts_tokens} onChange={(e) => update("concepts_tokens", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Practice tokens</Label>
                <Input type="number" value={config.practice_tokens} onChange={(e) => update("practice_tokens", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Practice count</Label>
                <Input type="number" value={config.practice_count} onChange={(e) => update("practice_count", Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-2">
                <Label>Cram sheet tokens</Label>
                <Input type="number" value={config.cram_tokens} onChange={(e) => update("cram_tokens", Number(e.target.value))} />
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>OCR & media</CardTitle>
            <p className="text-sm text-foreground/70">Toggle vision and media capture.</p>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
              <div>
                <div className="font-medium text-sm">Allow PDF OCR</div>
                <div className="text-xs text-foreground/60">Tesseract fallback when text extraction fails.</div>
              </div>
              <Switch checked={config.allow_pdf_ocr} onChange={(e) => update("allow_pdf_ocr", e.target.checked)} />
            </div>
            <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
              <div>
                <div className="font-medium text-sm">OpenAI Vision</div>
                <div className="text-xs text-foreground/60">Enable for page renders and descriptions.</div>
              </div>
              <Switch checked={config.allow_openai_vision} onChange={(e) => update("allow_openai_vision", e.target.checked)} />
            </div>
            <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
              <div>
                <div className="font-medium text-sm">Capture media</div>
                <div className="text-xs text-foreground/60">Render first pages as PNGs.</div>
              </div>
              <Switch checked={config.capture_media} onChange={(e) => update("capture_media", e.target.checked)} />
            </div>
            <div className="flex items-center justify-between md:col-span-3 rounded-md border border-border px-3 py-2">
              <div>
                <div className="font-medium text-sm">Describe media</div>
                <div className="text-xs text-foreground/60">Run vision model to summarize images.</div>
              </div>
              <Switch checked={config.describe_media} onChange={(e) => update("describe_media", e.target.checked)} />
            </div>
            <div className="flex flex-col gap-2">
              <Label>Media max pages</Label>
              <Input
                type="number"
                value={config.media_max_pages}
                onChange={(e) => update("media_max_pages", Number(e.target.value))}
                min={1}
                max={10}
              />
              <div className="text-xs text-foreground/60">How many pages to capture when media is on (per document).</div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>Media zoom</Label>
              <Input
                type="number"
                step="0.1"
                value={config.media_zoom}
                onChange={(e) => update("media_zoom", Number(e.target.value))}
                min={1}
                max={3}
              />
              <div className="text-xs text-foreground/60">Render scale for captured pages (e.g., 2.0 = 200% zoom).</div>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit job"}
          </Button>
          {message && <div className="text-sm text-foreground/70">{message}</div>}
        </div>
      </form>
    </div>
  );
}
