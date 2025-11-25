"use client";

import Link from "next/link";
import { presets } from "@/lib/configSchema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PresetsPage() {
  return (
    <div className="flex flex-col gap-4">
      <Link href="/" className="text-sm text-foreground/60 hover:text-foreground">
        ← Back to dashboard
      </Link>
      <h1 className="text-2xl font-semibold">Presets</h1>
      <p className="text-sm text-foreground/70">Suggested starting points; adjust to taste.</p>
      <div className="grid gap-3 md:grid-cols-3">
        {presets.map((preset) => (
          <Card key={preset.id}>
            <CardHeader>
              <CardTitle>{preset.name}</CardTitle>
              <p className="text-sm text-foreground/70">{preset.description}</p>
            </CardHeader>
            <CardContent className="text-sm text-foreground/70">
              <div>Chunk words: {preset.config.chunk_words}</div>
              <div>Agent report tokens: {preset.config.agent_report_tokens}</div>
              <div>Agent testimony tokens: {preset.config.agent_testimony_tokens}</div>
              <div>Judge tokens: {preset.config.judge_tokens}</div>
              <div>Lit review tokens: {preset.config.lit_review_max_output_tokens}</div>
              <div>Claim eval tokens: {preset.config.claim_eval_max_output_tokens}</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
