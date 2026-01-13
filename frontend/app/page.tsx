"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Plus } from "lucide-react";
import { supabaseBrowser } from "@/lib/supabaseBrowser";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";

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
  const [loading, setLoading] = useState(true);
  const supabaseConfigured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const sb = supabaseBrowser();
        const { data, error: err } = await sb
          .from("jobs")
          .select("id, title, status, created_at, updated_at")
          .order("created_at", { ascending: false })
          .limit(10);
        if (err) throw err;
        if (mounted && data) setJobs(data as JobRow[]);
      } catch (e: any) {
        if (mounted) setError(e?.message || "Unable to load jobs (is Supabase configured?)");
      } finally {
        if (mounted) setLoading(false);
      }
    };
    if (supabaseConfigured) {
      load();
    } else {
      setLoading(false);
      setError("Supabase not configured; showing demo state.");
    }
    return () => {
      mounted = false;
    };
  }, [supabaseConfigured]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3 rounded-xl border border-border bg-white px-5 py-4 shadow-sm">
        <div className="text-xs uppercase tracking-[0.2em] text-foreground/60">Pipeline</div>
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Literature review control</h1>
            <p className="text-sm text-foreground/70">Submit runs, monitor status, and tune presets.</p>
          </div>
          <div className="flex gap-2">
            <Link href="/jobs/new">
              <Button className="gap-2">
                <Plus size={16} />
                New job
              </Button>
            </Link>
            <Link href="/presets">
              <Button variant="ghost">Presets</Button>
            </Link>
          </div>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.15em] text-foreground/60">Queue</div>
              <div className="text-lg font-semibold">Recent jobs</div>
            </div>
            <Link href="/jobs/new" className="text-sm text-accent hover:underline">
              Start another
            </Link>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {loading && <div className="text-sm text-foreground/60">Loading…</div>}
          {!loading && error && (
            <div className="text-sm text-foreground/60 rounded-md border border-border bg-white px-3 py-2">
              {error}
            </div>
          )}
          {!loading && !error && jobs.length === 0 && (
            <div className="flex flex-col items-start gap-2 rounded-md border border-border px-4 py-3 bg-white">
              <div className="text-sm font-medium text-foreground/80">No jobs yet</div>
              <p className="text-sm text-foreground/60">Submit a PDF directory to see it here.</p>
              <Link href="/jobs/new">
                <Button size="sm">Create your first job</Button>
              </Link>
            </div>
          )}
          {!loading &&
            !error &&
            jobs.map((job) => (
              <Link key={job.id} href={`/jobs/${job.id}`} className="block">
                <div className="flex items-center justify-between rounded-lg border border-border bg-white px-4 py-3 hover:border-accent/70 transition">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {job.title || "Untitled job"}
                      <StatusBadge status={job.status} />
                    </div>
                    <div className="text-xs text-foreground/60">Submitted {new Date(job.created_at).toLocaleString()}</div>
                  </div>
                  <ChevronRight size={16} className="text-foreground/50" />
                </div>
              </Link>
            ))}
        </CardContent>
      </Card>
    </div>
  );
}
