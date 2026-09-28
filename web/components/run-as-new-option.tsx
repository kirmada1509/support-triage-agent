"use client";

import { Checkbox } from "@/components/ui/checkbox";

// A demo ticket usually repeats one already investigated, so the duplicate check links it and
// the analysts never run. This lets the person ask for the whole pipeline anyway.
export function RunAsNewOption({ id, checked, onChange }: { id: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <div className="flex items-start gap-2.5">
    <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} className="mt-0.5" />
    <label htmlFor={id} className="cursor-pointer text-xs leading-relaxed"><span className="font-medium">Run as new</span><span className="block text-muted-foreground">Skip the duplicate check, so the analysts investigate even if this repeats an open ticket.</span></label>
  </div>;
}
