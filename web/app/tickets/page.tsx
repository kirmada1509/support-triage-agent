"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { formatDistanceToNow, differenceInSeconds } from "date-fns";
import { useReactTable, getCoreRowModel, type ColumnDef } from "@tanstack/react-table";
import { ArrowRight, Search } from "lucide-react";
import { $api } from "@/lib/api";
import type { components } from "@/lib/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";

type Ticket = components["schemas"]["TicketSummary"];
type Detail = components["schemas"]["TicketDetail"];

const statusStyle: Record<Ticket["status"], string> = {
  queued: "bg-muted text-muted-foreground", running: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  needs_approval: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  done: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
};
const statusName: Record<Ticket["status"], string> = {
  queued: "Queued", running: "Investigating", needs_approval: "Needs approval", done: "Done", failed: "Failed",
};
function human(value: string | null | undefined) { return value?.replaceAll("_", " ") ?? "—"; }
function duration(ticket: Ticket) {
  const seconds = differenceInSeconds(ticket.completed_at ?? new Date(), ticket.received_at);
  return seconds < 60 ? `${Math.max(seconds, 0)}s` : `${Math.floor(seconds / 60)}m`;
}

function Preview({ ticket }: { ticket: Detail | undefined }) {
  if (!ticket) return <div className="p-6 text-sm text-muted-foreground">Select a ticket</div>;
  return <div className="flex h-full flex-col">
    <div className="flex-1 space-y-5 overflow-y-auto p-6">
      <div><p className="text-xs font-semibold tracking-wide text-muted-foreground">#{ticket.id}</p><h2 className="mt-2 text-lg font-semibold leading-snug">{ticket.subject}</h2><Badge variant="secondary" className={`mt-3 ${statusStyle[ticket.status]}`}>{statusName[ticket.status]}</Badge></div>
      <Separator />
      <dl className="grid grid-cols-[90px_1fr] gap-y-3 text-sm"><dt className="text-muted-foreground">Tenant</dt><dd>{ticket.tenant_id ?? "—"}</dd><dt className="text-muted-foreground">Lane</dt><dd className="capitalize">{human(ticket.lane)}</dd><dt className="text-muted-foreground">Severity</dt><dd>{ticket.severity ? `Sev ${ticket.severity}` : "—"}</dd><dt className="text-muted-foreground">Stage</dt><dd className="capitalize">{human(ticket.current_stage)}</dd></dl>
      <Separator />
      <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Customer message</h3><p className="rounded-md bg-muted/60 p-3 text-sm leading-relaxed whitespace-pre-wrap">{ticket.body}</p></section>
      {ticket.jev && <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Classification</h3><div className="space-y-1 text-sm">{ticket.jev.answers.map((answer) => <p key={answer.question}><span className="capitalize text-muted-foreground">{human(answer.question)}:</span> {String(answer.answer)} <span className="text-xs text-muted-foreground">{Math.round(answer.confidence * 100)}%</span></p>)}</div></section>}
      {ticket.outcome && <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Outcome</h3><p className="text-sm leading-relaxed">{ticket.outcome.summary}</p></section>}
    </div>
    <div className="border-t p-4"><Button asChild className="w-full"><Link href={`/ticket/${encodeURIComponent(ticket.id)}`}>Open investigation <ArrowRight size={15} /></Link></Button></div>
  </div>;
}

export default function TicketsPage() {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobilePreview, setMobilePreview] = useState(false);
  const { data: tickets, isLoading, error } = $api.useQuery("get", "/tickets", {}, { refetchInterval: 2000 });
  const selected = selectedId ?? tickets?.[0]?.id ?? "";
  const { data: detail } = $api.useQuery("get", "/tickets/{ticket_id}", { params: { path: { ticket_id: selected } } }, { enabled: Boolean(selected), refetchInterval: 2000 });
  const rows = useMemo(() => (tickets ?? []).filter((ticket) => {
    const match = `${ticket.id} ${ticket.subject} ${ticket.tenant_id ?? ""}`.toLowerCase().includes(search.toLowerCase());
    return match && (filter === "all" || ticket.status === filter);
  }), [tickets, search, filter]);
  const columns = useMemo<ColumnDef<Ticket>[]>(() => [
    { header: "Ticket", accessorKey: "id", cell: ({ row }) => <div><div className="font-medium">#{row.original.id}</div><div className="max-w-56 truncate text-xs text-muted-foreground">{row.original.subject}</div></div> },
    { header: "Tenant", accessorKey: "tenant_id", cell: ({ row }) => <span className="text-sm">{row.original.tenant_id ?? "—"}</span> },
    { header: "Lane", accessorKey: "lane", cell: ({ row }) => <span className="capitalize text-muted-foreground">{human(row.original.lane)}</span> },
    { header: "Current stage", accessorKey: "current_stage", cell: ({ row }) => <span className="capitalize text-muted-foreground">{human(row.original.current_stage)}</span> },
    { header: "Severity", accessorKey: "severity", cell: ({ row }) => row.original.severity ? `Sev ${row.original.severity}` : "—" },
    { header: "Status", accessorKey: "status", cell: ({ row }) => <Badge variant="secondary" className={statusStyle[row.original.status]}>{statusName[row.original.status]}</Badge> },
    { header: "Duration", id: "duration", cell: ({ row }) => <span className="text-muted-foreground">{duration(row.original)}</span> },
    { header: "Cost", accessorKey: "cost_usd", cell: ({ row }) => <span className="text-muted-foreground">${row.original.cost_usd.toFixed(3)}</span> },
    { header: "Received", accessorKey: "received_at", cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{formatDistanceToNow(row.original.received_at, { addSuffix: true })}</span> },
  ], []);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  return <div className="flex min-h-screen min-w-0">
    <main className="min-w-0 flex-1 px-6 py-7 xl:px-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">Tickets</h1><p className="mt-1 text-sm text-muted-foreground">Support investigations</p></div><div className="relative w-full max-w-xs"><Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" /><Input aria-label="Search tickets" placeholder="Search tickets..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" /></div></div>
      <Tabs value={filter} onValueChange={setFilter} className="mb-4"><TabsList variant="line"><TabsTrigger value="all">All</TabsTrigger><TabsTrigger value="running">Running</TabsTrigger><TabsTrigger value="needs_approval">Needs approval</TabsTrigger><TabsTrigger value="done">Done</TabsTrigger></TabsList></Tabs>
      {isLoading ? <div className="space-y-3">{Array.from({ length: 7 }, (_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div> : error ? <p className="py-20 text-center text-sm text-destructive">Could not load tickets. Check the API connection.</p> : rows.length === 0 ? <p className="py-20 text-center text-sm text-muted-foreground">No tickets found.</p> : <div className="overflow-x-auto rounded-md border"><Table><TableHeader>{table.getHeaderGroups().map((group) => <TableRow key={group.id}>{group.headers.map((header) => <TableHead key={header.id}>{typeof header.column.columnDef.header === "string" ? header.column.columnDef.header : ""}</TableHead>)}</TableRow>)}</TableHeader><TableBody>{table.getRowModel().rows.map((row) => <TableRow key={row.id} data-state={selected === row.original.id ? "selected" : undefined} className="h-16 cursor-pointer" onClick={() => { setSelectedId(row.original.id); setMobilePreview(true); }}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{typeof cell.column.columnDef.cell === "function" ? cell.column.columnDef.cell(cell.getContext()) : cell.getValue() as React.ReactNode}</TableCell>)}</TableRow>)}</TableBody></Table></div>}
    </main>
    <aside className="hidden w-[310px] shrink-0 border-l xl:block"><Preview ticket={detail} /></aside>
    <Sheet open={mobilePreview} onOpenChange={setMobilePreview}><SheetContent className="p-0 xl:hidden"><SheetHeader className="sr-only"><SheetTitle>Ticket preview</SheetTitle></SheetHeader><Preview ticket={detail} /></SheetContent></Sheet>
  </div>;
}
