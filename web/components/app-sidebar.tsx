"use client";

import Link from "next/link";
import { BotIcon, Code2Icon, MessageCircleIcon } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "next-auth";
import { useState } from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { unstable_serialize } from "swr/infinite";
import { PlusIcon, TrashIcon } from "@/components/icons";
import { SidebarHistory } from "@/components/sidebar-history";
import { SidebarUserNav } from "@/components/sidebar-user-nav";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  useSidebar,
} from "@/components/ui/sidebar";
import { CodingTaskList } from "@/features/coding/components/coding-task-list";
import { getChatHistoryPaginationKey } from "@/lib/chat-history-pagination";
import { openAgentConversation } from "@/lib/standing-agent-api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export function AppSidebar({ user }: { user: User | undefined }) {
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const isCode = pathname.startsWith("/code");
  const { setOpenMobile } = useSidebar();
  const { mutate } = useSWRConfig();
  const [showDeleteAllDialog, setShowDeleteAllDialog] = useState(false);
  const [openingAgent, setOpeningAgent] = useState(false);

  // 트랙 Q8d -- 상시 에이전트와의 웹 대화. 채널(Slack 등) DM 과 같은 맥락을 쓴다.
  const handleOpenAgent = async () => {
    setOpeningAgent(true);
    try {
      const conversationId = await openAgentConversation();
      if (conversationId === null) {
        toast.info("No standing agent yet.");
        return;
      }
      setOpenMobile(false);
      router.push(`/chat/${conversationId}`);
    } catch (error: unknown) {
      toast.error(
        error instanceof Error ? error.message : "Could not open the agent conversation"
      );
    } finally {
      setOpeningAgent(false);
    }
  };

  const handleDeleteAll = () => {
    const deletePromise = fetch("/api/history", {
      method: "DELETE",
    });

    toast.promise(deletePromise, {
      loading: "Deleting all chats...",
      success: () => {
        mutate(unstable_serialize(getChatHistoryPaginationKey));
        setShowDeleteAllDialog(false);
        router.replace("/");
        router.refresh();
        return "All chats deleted successfully";
      },
      error: "Failed to delete all chats",
    });
  };

  return (
    <>
      <Sidebar className="group-data-[side=left]:border-sidebar-border/70 group-data-[side=left]:border-r">
        <SidebarHeader>
          <SidebarMenu>
            <div className="flex flex-row items-center justify-between">
              <Link
                className="flex flex-row items-center gap-3"
                href="/"
                onClick={() => {
                  setOpenMobile(false);
                }}
              >
                <span className="cursor-pointer rounded-md px-2 font-semibold text-lg text-sidebar-foreground tracking-normal hover:bg-sidebar-accent hover:text-sidebar-accent-foreground">
                  NEOS
                </span>
              </Link>
              <div className="flex flex-row gap-1">
                {user && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        className="h-8 p-1 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground md:h-fit md:p-2"
                        onClick={() => setShowDeleteAllDialog(true)}
                        type="button"
                        variant="ghost"
                      >
                        <TrashIcon />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent align="end" className="hidden md:block">
                      Delete All Chats
                    </TooltipContent>
                  </Tooltip>
                )}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      className="h-8 p-1 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground md:h-fit md:p-2"
                      onClick={() => {
                        setOpenMobile(false);
                        router.push("/");
                        router.refresh();
                      }}
                      type="button"
                      variant="ghost"
                    >
                      <PlusIcon />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent align="end" className="hidden md:block">
                    New Chat
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <nav className="grid gap-1 px-2 pb-3" aria-label="Products">
            <Link
              className="flex items-center gap-3 rounded-md px-2 py-2 text-sidebar-foreground text-sm hover:bg-sidebar-accent"
              href="/"
              onClick={() => setOpenMobile(false)}
            >
              <MessageCircleIcon className="size-4" />
              Chat
            </Link>
            <Link
              className="flex items-center gap-3 rounded-md px-2 py-2 text-sidebar-foreground text-sm hover:bg-sidebar-accent"
              href="/code"
              onClick={() => setOpenMobile(false)}
            >
              <Code2Icon className="size-4" />
              Code
            </Link>
            <button
              className="flex items-center gap-3 rounded-md px-2 py-2 text-left text-sidebar-foreground text-sm hover:bg-sidebar-accent disabled:opacity-60"
              disabled={openingAgent}
              onClick={handleOpenAgent}
              type="button"
            >
              <BotIcon className="size-4" />
              Agent
            </button>
          </nav>
          {isCode ? (
            <div className="px-1 pb-3">
              <p className="px-2 pb-1 font-mono text-[10px] text-amber-400 uppercase tracking-[0.18em]">
                Recent
              </p>
              <CodingTaskList compact />
            </div>
          ) : (
            <SidebarHistory user={user} />
          )}
        </SidebarContent>
        <SidebarFooter>{user && <SidebarUserNav user={user} />}</SidebarFooter>
      </Sidebar>

      <AlertDialog
        onOpenChange={setShowDeleteAllDialog}
        open={showDeleteAllDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete all chats?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. This will permanently delete all
              your chats and remove them from our servers.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteAll}>
              Delete All
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
