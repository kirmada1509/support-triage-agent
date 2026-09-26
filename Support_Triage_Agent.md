**Support Triage Agent** is an internal AI tool for B2B support teams like Zuddl's. It picks up every customer ticket, works out what kind it is, and either answers it or does the engineering investigation before any engineer looks at it.

**What it does with a ticket:**

1. **Takes it in.** A ticket arrives from Pylon through a signed webhook. An LLM call adds context such as the account, recent deploys and flag changes, and Jev categorizes it in under a second.
2. **Answers simple questions itself.** How-to questions get a reply built from the help-center sections the RAG search finds, citing the section it used. Feature and billing requests are tagged and acknowledged.
3. **Investigates suspected bugs.** Two open-source agents run in parallel:
   - HolmesGPT reads production data: metrics, traces, logs and the database.
   - mini-swe-agent reads the code at the deployed version, including what changed in the last deploy.

   Their evidence is combined into a verdict. If it's not a real bug, for example the customer's card type isn't supported, the customer gets a direct answer with the reason. If it is a real bug, the owning team gets a Linear issue with the root cause, the file and line, the commit, and links to the evidence.
4. **Remembers.** A differently worded repeat of a known bug is matched to the existing investigation by meaning, and linked in seconds.

**What admins see:** a live dashboard where each ticket's path lights up stage by stage on a flowchart. It shows every query, code snippet, diff and command the agents ran, with a button to approve customer replies before they're sent.

**Why it matters:** it answers the easy tickets immediately and stops false-alarm bugs from reaching engineering. Real bugs reach the right team already diagnosed.

**How it's built:** mostly from open-source parts: LangGraph, Pydantic AI, HolmesGPT, mini-swe-agent, pgvector, and Next.js with shadcn. It runs on cheap models like DeepSeek, at an estimated $0.10 per investigated ticket. Access to production data and code is read-only, and people approve anything uncertain.

For the demo, it runs against a real 20-service e-commerce app with four bugs planted in it, and resolves seven realistic tickets end to end in about 10 minutes.

I can see you've connected a `support-triage-agent` folder. I can scaffold the repo from the plan there when you're ready.