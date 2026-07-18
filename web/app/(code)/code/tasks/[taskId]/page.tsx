import { CodingTaskWorkspace } from "@/features/coding/components/coding-task-workspace";


export default async function CodingTaskPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = await params;
  return <CodingTaskWorkspace taskId={taskId} />;
}
