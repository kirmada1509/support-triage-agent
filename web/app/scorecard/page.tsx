"use client";

import { ChartNoAxesCombined, FileBarChart2, ShieldAlert } from "lucide-react";
import { $api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function percent(value: number | null) { return value == null ? "—" : `${Math.round(value * 100)}%`; }

export default function ScorecardPage() {
  const { data, isLoading, error } = $api.useQuery("get", "/evals/scorecard");
  return <main className="min-w-0 flex-1 px-6 py-5 xl:px-8"><div className="mx-auto max-w-6xl"><div className="mb-8"><div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><ChartNoAxesCombined size={13} /> Evaluation</div><h1 className="text-xl font-semibold tracking-tight">Scorecard</h1><p className="mt-1 text-xs text-muted-foreground">Evaluation results recorded by the backend.</p></div>
    {isLoading ? <div className="space-y-3">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div> : error ? <div className="flex flex-col items-center gap-2 rounded-md border border-dashed py-20 text-center text-sm text-destructive"><ShieldAlert size={20} />Could not load the scorecard.</div> : !data?.length ? <div className="flex flex-col items-center gap-2 rounded-md border border-dashed py-20 text-center"><span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><FileBarChart2 size={19} /></span><p className="mt-1 text-sm font-medium">No evaluation results yet</p><p className="max-w-sm text-xs leading-relaxed text-muted-foreground">Results will appear here after an evaluation run writes them to the backend.</p></div> : <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead>Run</TableHead><TableHead>Profile</TableHead><TableHead>Role</TableHead><TableHead>Model</TableHead><TableHead>Retrieval</TableHead><TableHead>Routing</TableHead><TableHead>Verdict</TableHead><TableHead>Hit rate</TableHead><TableHead>Latency p50</TableHead><TableHead>Cost / ticket</TableHead></TableRow></TableHeader><TableBody>{data.map((entry, index) => <TableRow key={`${entry.run_at}-${index}`} className="h-[60px]"><TableCell className="whitespace-nowrap text-muted-foreground">{new Date(entry.run_at).toLocaleDateString()}</TableCell><TableCell>{entry.profile ?? "—"}</TableCell><TableCell>{entry.role ?? "—"}</TableCell><TableCell>{entry.model ?? "—"}</TableCell><TableCell>{entry.with_retrieval == null ? "—" : <Badge variant="outline" className="text-[11px]">{entry.with_retrieval ? "On" : "Off"}</Badge>}</TableCell><TableCell>{percent(entry.routing_accuracy)}</TableCell><TableCell>{percent(entry.verdict_accuracy)}</TableCell><TableCell>{percent(entry.retrieval_hit_rate)}</TableCell><TableCell>{entry.p50_latency_s == null ? "—" : `${entry.p50_latency_s.toFixed(1)}s`}</TableCell><TableCell>{entry.cost_per_ticket == null ? "—" : `$${entry.cost_per_ticket.toFixed(3)}`}</TableCell></TableRow>)}</TableBody></Table></div>}
  </div></main>;
}
