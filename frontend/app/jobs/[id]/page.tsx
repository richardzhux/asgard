"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabaseBrowser } from "@/lib/supabaseBrowser";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";

type Job = {
  id: string;
  title: string | null;
  status: string;
  research_focus: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

type JobEvent = {
  id: number;
  event_type: string;
  message: string | null;
  created_at: string;
};

export default function JobDetailPage({ params }: { params: { id: string } }) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const sb = supabaseBrowser();
        const [{ data: jobData, error: jobErr }, { data: eventData, error: eventErr }] = await Promise.all([
          sb.from("jobs").select("*").eq("id", params.id).single(),
          sb.from("job_events").select("*").eq("job_id", params.id).order("created_at", { ascending: false })
        ]);
        if (jobErr) throw jobErr;
        if (eventErr) throw eventErr;
        if (mounted) {
          setJob(jobData as Job);
          setEvents((eventData as JobEvent[]) || []);
        }
      } catch (e: any) {
        setError(e?.message || "Failed to load job");
      } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    return () => {
      mounted = false;
    };
  }, [params.id]);

  return (
    <div className="flex flex-col gap-4">
      <Link href="/" className="text-sm text-foreground/60 hover:text-foreground">
        ← Back
      </Link>
      {error && <div className="text-sm text-red-600">{error}</div>}
      {loading && <div className="text-sm text-foreground/60">Loading…</div>}
      {job && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2">
              <span>{job.title || "Untitled job"}</span>
              <StatusBadge status={job.status} />
            </CardTitle>
            <p className="text-sm text-foreground/70">Focus: {job.research_focus}</p>
          </CardHeader>
          <CardContent className="grid gap-2 md:grid-cols-2 text-sm">
            <div className="text-foreground/60">Submitted: {new Date(job.created_at).toLocaleString()}</div>
            <div className="text-foreground/60">Started: {job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</div>
            <div className="text-foreground/60">Finished: {job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}</div>
            {job.error && <div className="text-red-600 md:col-span-2">Error: {job.error}</div>}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {events.length === 0 && <div className="text-sm text-foreground/60">No events yet.</div>}
          {events.map((evt) => (
            <div key={evt.id} className="flex gap-3">
              <div className="pt-1">
                <div className="h-2 w-2 rounded-full bg-foreground/50" />
              </div>
              <div className="flex-1 rounded-md border border-border px-3 py-2">
                <div className="text-xs uppercase tracking-wide text-foreground/60">{evt.event_type}</div>
                <div className="text-sm">{evt.message}</div>
                <div className="text-xs text-foreground/50">{new Date(evt.created_at).toLocaleString()}</div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
