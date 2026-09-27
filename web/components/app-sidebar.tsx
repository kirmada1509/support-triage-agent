"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { FlaskConical, ListTodo, Moon, Sun, ChartNoAxesCombined, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";

const items = [
  { href: "/tickets", label: "Tickets", icon: ListTodo },
  { href: "/simulator", label: "Simulator", icon: FlaskConical },
  { href: "/scorecard", label: "Scorecard", icon: ChartNoAxesCombined },
];

export function AppSidebar() {
  const path = usePathname();
  const { theme, setTheme } = useTheme();
  return (
    <Sidebar variant="sidebar" collapsible="offcanvas" className="border-r bg-sidebar">
      <SidebarHeader className="h-20 justify-center border-b px-5">
        <Link href="/tickets" className="flex items-center gap-2.5 text-sm font-semibold tracking-tight">
          <span className="flex size-7 items-center justify-center rounded-md bg-foreground text-background"><Sparkles size={15} /></span>
          Support Triage
        </Link>
      </SidebarHeader>
      <SidebarContent className="pt-4">
        <SidebarGroup><SidebarGroupContent><SidebarMenu>
          {items.map(({ href, label, icon: Icon }) => (
            <SidebarMenuItem key={href}>
              <SidebarMenuButton asChild isActive={path === href || (href === "/tickets" && path.startsWith("/ticket/"))}>
                <Link href={href}><Icon size={16} /><span>{label}</span></Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu></SidebarGroupContent></SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-3">
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />} Theme
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}
