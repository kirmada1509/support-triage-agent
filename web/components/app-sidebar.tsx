"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { FlaskConical, ListTodo, Moon, Sun, ChartNoAxesCombined, Sparkles, CircleHelp, Network } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CreditBalance } from "@/components/credit-balance";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";

const items = [
  { href: "/tickets", label: "Tickets", icon: ListTodo },
  { href: "/simulator", label: "Simulator", icon: FlaskConical },
  { href: "/scorecard", label: "Scorecard", icon: ChartNoAxesCombined },
  { href: "/how-it-works", label: "How it works", icon: Network },
];

export function AppSidebar() {
  const path = usePathname();
  const { theme, setTheme } = useTheme();
  return (
    <Sidebar variant="sidebar" collapsible="offcanvas" className="border-r bg-sidebar">
      <SidebarHeader className="gap-3 border-b px-4 py-4">
        <Link href="/tickets" className="flex items-center gap-2.5 text-sm font-semibold tracking-tight">
          <span className="flex size-8 items-center justify-center rounded-lg border bg-background text-foreground"><Sparkles size={15} /></span>
          <span>Support Triage<span className="mt-0.5 block text-[10px] font-normal tracking-normal text-muted-foreground">Operations console</span></span>
        </Link>
        <CreditBalance />
      </SidebarHeader>
      <SidebarContent className="pt-5">
        <SidebarGroup><p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Workspace</p><SidebarGroupContent><SidebarMenu className="gap-1">
          {items.map(({ href, label, icon: Icon }) => (
            <SidebarMenuItem key={href}>
              <SidebarMenuButton asChild isActive={path === href || (href === "/tickets" && path.startsWith("/ticket/"))} className="h-9 rounded-md text-[13px] data-[active=true]:bg-blue-50 data-[active=true]:text-blue-700 dark:data-[active=true]:bg-blue-950/50 dark:data-[active=true]:text-blue-300">
                <Link href={href}><Icon size={16} /><span>{label}</span></Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu></SidebarGroupContent></SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-3">
        <div className="mb-2 flex items-center gap-2 px-2 text-[11px] text-muted-foreground"><CircleHelp size={13} /> Investigation activity is recorded</div>
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          <Moon size={16} className="dark:hidden" /><Sun size={16} className="hidden dark:block" /> Theme
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}
