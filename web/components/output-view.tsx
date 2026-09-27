"use client";

import dynamic from "next/dynamic";
import JsonView from "@uiw/react-json-view";
import { CartesianGrid, Line, LineChart, XAxis } from "recharts";
import { ExternalLink } from "lucide-react";
import { CodeBlock, CodeBlockFilename, CodeBlockHeader, CodeBlockTitle } from "@/components/ai-elements/code-block";
import { Terminal } from "@/components/ai-elements/terminal";
import { Commit, CommitContent, CommitHash, CommitHeader, CommitInfo, CommitMessage, CommitMetadata } from "@/components/ai-elements/commit";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/schema";

const LazyLog = dynamic(() => import("@melloware/react-logviewer").then((module) => module.LazyLog), { ssr: false });
type Output = NonNullable<components["schemas"]["ToolCallEvent"]["output"]>;

export function OutputView({ output }: { output: Output }) {
  switch (output.render) {
    case "code":
      return <CodeBlock code={output.code} language={output.language as React.ComponentProps<typeof CodeBlock>["language"]} showLineNumbers>
        <CodeBlockHeader><CodeBlockTitle><CodeBlockFilename>{output.file}:{output.start_line}</CodeBlockFilename></CodeBlockTitle></CodeBlockHeader>
      </CodeBlock>;
    case "diff":
      return <CodeBlock code={output.diff} language="diff" showLineNumbers>
        {output.file && <CodeBlockHeader><CodeBlockTitle><CodeBlockFilename>{output.file}</CodeBlockFilename></CodeBlockTitle></CodeBlockHeader>}
      </CodeBlock>;
    case "terminal":
      return <Terminal output={`$ ${output.command}\n${output.output}`} />;
    case "commit":
      return <Commit defaultOpen={false}><CommitHeader><CommitInfo><CommitMessage>{output.title}</CommitMessage><CommitMetadata><CommitHash>{output.sha.slice(0, 10)}</CommitHash>{output.author}</CommitMetadata></CommitInfo></CommitHeader><CommitContent className="px-3 pb-3 text-xs text-muted-foreground">{output.files.join(" · ")}</CommitContent></Commit>;
    case "log":
      return <div className="h-64 overflow-hidden rounded-md border text-xs"><LazyLog text={output.lines.join("\n")} enableSearch follow={false} /></div>;
    case "series":
      return <div className="space-y-3"><p className="font-mono text-xs text-muted-foreground">{output.query}</p>{output.series.map((series) => <div key={series.name}><p className="mb-1 text-xs text-muted-foreground">{series.name}{output.unit ? ` · ${output.unit}` : ""}</p><ChartContainer config={{ value: { label: "Value", color: "var(--chart-1)" } }} className="h-40 w-full aspect-auto"><LineChart data={series.points}><CartesianGrid vertical={false} /><XAxis dataKey="ts" tickFormatter={(value: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} tickLine={false} axisLine={false} /><ChartTooltip content={<ChartTooltipContent />} /><Line dataKey="value" type="monotone" stroke="var(--color-value)" dot={false} strokeWidth={2} /></LineChart></ChartContainer></div>)}</div>;
    case "trace":
      return <div className="space-y-2">{output.url && <Button variant="link" size="sm" asChild className="h-auto p-0"><a href={output.url} target="_blank" rel="noreferrer">Open trace <ExternalLink size={12} /></a></Button>}<p className="font-mono text-xs text-muted-foreground">{output.trace_id}</p><Table><TableHeader><TableRow><TableHead>Service</TableHead><TableHead>Span</TableHead><TableHead>Duration</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{output.spans.map((span) => <TableRow key={span.span_id}><TableCell>{span.service}</TableCell><TableCell>{span.name}</TableCell><TableCell>{span.duration_ms.toFixed(0)} ms</TableCell><TableCell>{span.status}</TableCell></TableRow>)}</TableBody></Table></div>;
    case "table":
      return <div className="overflow-x-auto"><Table><TableHeader><TableRow>{output.columns.map((column) => <TableHead key={column}>{column}</TableHead>)}</TableRow></TableHeader><TableBody>{output.rows.map((row, index) => <TableRow key={index}>{row.map((cell, column) => <TableCell key={column}>{String(cell ?? "")}</TableCell>)}</TableRow>)}</TableBody></Table></div>;
    case "json":
      return <JsonView value={output.data !== null && typeof output.data === "object" ? output.data : { value: output.data }} collapsed={2} />;
  }
}
