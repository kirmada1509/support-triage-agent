import { ArrowUpRight, Network } from "lucide-react";
import { Button } from "@/components/ui/button";
import { diagrams } from "./diagrams";

const steps = [
  { title: "Intake", body: "A signed Pylon webhook delivers the ticket. The API checks the signature, stores the ticket and queues the run, so it answers in about 100 ms." },
  { title: "Enrich and categorize", body: "One model call pulls out IDs, a time window and the symptom, and code checks each against the ticket and the fetched context. A second call gives type, service, severity and revenue impact, each with a confidence; anything below 0.7, or a service it doesn't know, goes to a person." },
  { title: "Pick a lane", body: "How-to questions get a Layer 1 answer that cites help articles, and requests are triaged. Tech issues are checked against open investigations, then go to Layer 2." },
  { title: "Two analysts, working as a team", body: "A data analyst (HolmesGPT) reads production traces, metrics, logs, deploys and flags, while a codebase analyst (mini-swe-agent) reads the deployed code read-only. They start in parallel, then ask each other: production's exact error goes to the code, and a question about what the code implies goes back to production. At most three questions per ticket." },
  { title: "Verdict and delivery", body: "One model call decides bug, config incident, false positive or inconclusive, and rules in code check it against the evidence. Bugs go to the owning team in Linear, and a person approves any reply that is uncertain or revenue-blocking." },
];

export default function HowItWorksPage() {
  return <main className="min-w-0 flex-1 px-6 py-5 xl:px-8"><div className="mx-auto max-w-5xl">
    <div className="mb-8"><div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><Network size={13} /> Architecture</div><h1 className="text-xl font-semibold tracking-tight">How it works</h1><p className="mt-1 text-xs text-muted-foreground">How a support ticket becomes an answer, a triaged request or an engineering issue.</p></div>

    <section className="mb-10">
      <h2 className="mb-4 text-sm font-medium">The pipeline</h2>
      <ol className="space-y-3">
        {steps.map((step, i) => <li key={step.title} className="flex gap-4 rounded-lg border bg-card p-4">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">{i + 1}</span>
          <div className="min-w-0"><h3 className="text-sm font-medium">{step.title}</h3><p className="mt-1 text-sm leading-relaxed text-muted-foreground">{step.body}</p></div>
        </li>)}
      </ol>
    </section>

    <section>
      <h2 className="mb-1 text-sm font-medium">Architecture diagrams</h2>
      <p className="mb-4 text-xs text-muted-foreground">Each opens in a new tab, straight from the repo&rsquo;s <code className="font-mono">planning/</code> folder.</p>
      <div className="grid gap-3 md:grid-cols-3">
        {diagrams.map((d) => <div key={d.slug} className="flex flex-col rounded-lg border bg-card p-4">
          <h3 className="text-sm font-medium">{d.title}</h3>
          <p className="mt-1 flex-1 text-sm leading-relaxed text-muted-foreground">{d.description}</p>
          <Button asChild variant="outline" size="sm" className="mt-4 self-start"><a href={`/how-it-works/${d.slug}`} target="_blank" rel="noopener noreferrer">Open diagram <ArrowUpRight size={14} /></a></Button>
        </div>)}
      </div>
    </section>
  </div></main>;
}
