"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabaseBrowser } from "@/lib/supabaseBrowser";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type JobRow = {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export default function DashboardPage() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const sb = supabaseBrowser();
        const { data, error: err } = await sb.from("jobs").select("id, title, status, created_at, updated_at").order("created_at", { ascending: false }).limit(8);
        if (err) throw err;
        if (mounted && data) setJobs(data as JobRow[]);
      } catch (e: any) {
        setError(e?.message || "Failed to load jobs");
      }
    };
    load();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between">
        <div>
          <div className="text-sm uppercase tracking-wide text-foreground/60">Pipeline</div>
          <h1 className="text-2xl font-semibold">Literature Review Control</h1>
          <p className="text-sm text-foreground/70">Submit new jobs, monitor status, and tweak presets.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/jobs/new">
            <Button>New Job</Button>
          </Link>
          <Link href="/presets">
            <Button variant="ghost">Presets</Button>
          </Link>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Recent jobs</CardTitle>
          <p className="text-sm text-foreground/70">Most recent submissions.</p>
        </CardHeader>
        <CardContent>
          {error && <div className="text-sm text-red-600">{error}</div>}
          {!error && jobs.length === 0 && <div className="text-sm text-foreground/60">No jobs yet.</div>}
          <div className="flex flex-col gap-2">
            {jobs.map((job) => (
              <Link key={job.id} href={`/jobs/${job.id}`} className="block">
                <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 hover:border-accent">
                  <div className="flex flex-col">
                    <span className="text-sm font-medium">{job.title || "Untitled job"}</span>
                    <span className="text-xs text-foreground/60">{new Date(job.created_at).toLocaleString()}</span>
                  </div>
                  <div className="text-xs uppercase tracking-wide text-foreground/70">{job.status}</div>
                </div>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
