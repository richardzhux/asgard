"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { defaultJobConfig, JobConfig } from "@/lib/configSchema";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function NewJobPage() {
  const [config, setConfig] = useState<JobConfig>(defaultJobConfig);
  const [title, setTitle] = useState("Lit review run");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const update = <K extends keyof JobConfig>(key: K, value: JobConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
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
      <h1 className="text-2xl font-semibold">New lit review job</h1>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Sources & focus</CardTitle>
            <p className="text-sm text-foreground/70">Where to read and what to look for.</p>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <div className="md:col-span-2 flex flex-col gap-2">
              <Label>Title</Label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="flex flex-col gap-2">
              <Label>PDF directory or storage URI</Label>
              <Input value={config.pdf_dir} onChange={(e) => update("pdf_dir", e.target.value)} />
            </div>
            <div className="md:col-span-2 flex flex-col gap-2">
              <Label>Research focus</Label>
              <Textarea rows={3} value={config.research_focus} onChange={(e) => update("research_focus", e.target.value)} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Chunking</CardTitle>
            <p className="text-sm text-foreground/70">Words per chunk, overlap, and token budget.</p>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            <div className="flex flex-col gap-2">
              <Label>Words per chunk</Label>
              <Input type="number" value={config.chunk_words} onChange={(e) => update("chunk_words", Number(e.target.value))} />
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

        <Card>
          <CardHeader>
            <CardTitle>Agents & judge</CardTitle>
            <p className="text-sm text-foreground/70">Control narrative depth.</p>
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
              <Input type="number" value={config.media_max_pages} onChange={(e) => update("media_max_pages", Number(e.target.value))} />
            </div>
            <div className="flex flex-col gap-2">
              <Label>Media zoom</Label>
              <Input type="number" step="0.1" value={config.media_zoom} onChange={(e) => update("media_zoom", Number(e.target.value))} />
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
