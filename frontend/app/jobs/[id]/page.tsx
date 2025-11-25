"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabaseBrowser } from "@/lib/supabaseBrowser";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
      {job && (
        <Card>
          <CardHeader>
            <CardTitle>{job.title || "Untitled job"}</CardTitle>
            <p className="text-sm text-foreground/70">Status: {job.status}</p>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <div className="text-foreground/80">Focus: {job.research_focus}</div>
            <div className="text-foreground/60">Started: {job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</div>
            <div className="text-foreground/60">Finished: {job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}</div>
            {job.error && <div className="text-red-600">Error: {job.error}</div>}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {events.length === 0 && <div className="text-sm text-foreground/60">No events yet.</div>}
          {events.map((evt) => (
            <div key={evt.id} className="rounded-md border border-border px-3 py-2">
              <div className="text-xs uppercase tracking-wide text-foreground/60">{evt.event_type}</div>
              <div className="text-sm">{evt.message}</div>
              <div className="text-xs text-foreground/50">{new Date(evt.created_at).toLocaleString()}</div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
