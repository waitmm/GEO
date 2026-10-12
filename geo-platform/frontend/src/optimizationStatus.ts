const statuses: Record<string, string> = {
  QUEUED: '等待执行', RUNNING: '正在执行', WAITING_AUTHORIZATION: '等待调用授权',
  BLOCKED: '需要处理', INTERRUPTED: '执行中断', CANCELLED: '已取消',
  COMPLETED: '稿件已交付', COMPLETED_WITH_LIMITATIONS: '稿件已交付，有范围限制',
};

export function optimizationStatus(task: { task_kind: string; status: string; objects: { deliveries?: unknown[] } }): string {
  return task.task_kind === 'TRUTH_REPROJECTION' && task.status.startsWith('COMPLETED') && !task.objects.deliveries?.length
    ? '纠错已应用，无新增稿件' : statuses[task.status] || '状态待核对';
}
